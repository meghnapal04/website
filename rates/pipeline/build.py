"""Euro Rates Data Lab - end-to-end build.

    python rates/pipeline/build.py            # fetch from the ECB and rebuild
    python rates/pipeline/build.py --offline  # rebuild from the last raw snapshot

Stages (each one is visible on meghnapal.info/rates):
  1. INGEST       download each series in sources.py, snapshot raw CSV + SHA-256
  2. STANDARDISE  one tidy table: date, field, value, unit, source key
  3. TRANSFORM    align to the TARGET2 calendar, derive spreads, monthly view
  4. VALIDATE     run dq.py checks; withhold ERROR values, mark WARN values
  5. PUBLISH      write CSVs, data-quality log, data dictionary, lineage manifest
  6. BACKTEST     backtest.py measures how well the checks catch known errors
"""
import argparse
import hashlib
import io
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import backtest  # noqa: E402
import dq  # noqa: E402
from sources import SERIES, START, url_for  # noqa: E402

RAW = HERE / "raw"
OUT = HERE.parent / "data"
PIPELINE_VERSION = "1.0.0"


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# 1. INGEST ------------------------------------------------------------------
def ingest(offline: bool):
    RAW.mkdir(exist_ok=True)
    lineage = {}
    downloads = {}
    if not offline:
        # Download everything first and validate it; only then overwrite the raw
        # snapshot. If the ECB feed is down or truncated, the build stops and the
        # last good data stays published.
        for field, src in SERIES.items():
            req = urllib.request.Request(url_for(src["key"]), headers={"Accept": "text/csv"})
            with urllib.request.urlopen(req, timeout=60) as r:
                body = r.read()
            header = body.split(b"\n", 1)[0]
            if b"TIME_PERIOD" not in header or b"OBS_VALUE" not in header:
                raise SystemExit(f"ABORT: unexpected response for {field} ({src['key']})")
            old = RAW / f"{field}.csv"
            if old.exists() and body.count(b"\n") < old.read_bytes().count(b"\n"):
                raise SystemExit(f"ABORT: {field} has fewer rows than the last snapshot (truncated feed?)")
            downloads[field] = (body, datetime.now(timezone.utc).isoformat(timespec="seconds"))
        for field, (body, _) in downloads.items():
            (RAW / f"{field}.csv").write_bytes(body)
    for field, src in SERIES.items():
        path = RAW / f"{field}.csv"
        url = url_for(src["key"])
        if not offline:
            body, fetched = downloads[field]
        else:
            body = path.read_bytes()
            fetched = json.loads((OUT / "manifest.json").read_text())["sources"][field]["fetched_at_utc"]
        lineage[field] = {"ecb_key": src["key"], "url": url, "fetched_at_utc": fetched,
                          "raw_file": f"pipeline/raw/{field}.csv", "raw_sha256": sha256(body),
                          "raw_rows": body.count(b"\n") - 1}
    return lineage


# 2. STANDARDISE ---------------------------------------------------------------
def standardise():
    frames = []
    for field, src in SERIES.items():
        raw = pd.read_csv(RAW / f"{field}.csv", dtype=str)
        df = pd.DataFrame({
            "date": pd.to_datetime(raw["TIME_PERIOD"], format="%Y-%m" if src["freq"] == "monthly" else "%Y-%m-%d"),
            "field": field,
            "value": pd.to_numeric(raw["OBS_VALUE"], errors="coerce"),
            "unit": src["unit"], "freq": src["freq"], "source_key": src["key"],
        })
        frames.append(df)
    long_df = pd.concat(frames, ignore_index=True)
    return long_df[long_df["date"] >= START].sort_values(["field", "date"]).reset_index(drop=True)


# 3. TRANSFORM -----------------------------------------------------------------
def transform(long_df):
    daily_fields = [f for f, s in SERIES.items() if s["freq"] == "daily"]
    d = long_df[long_df["field"].isin(daily_fields)].drop_duplicates(["field", "date"], keep="last")
    wide = d.pivot(index="date", columns="field", values="value")

    last = wide["estr_rate"].last_valid_index()
    cal = dq.target2_days(START, last)
    # calendar = TARGET2 days, plus any day the ECB actually published €STR (never drop real data)
    idx = cal.union(wide["estr_rate"].dropna().index)
    daily = pd.DataFrame(index=idx)
    for f in daily_fields:
        if f == "dfr":  # policy rate is a step function: valid until changed -> forward-fill
            daily[f] = wide[f].reindex(wide.index.union(idx)).ffill().reindex(idx)
        else:           # market data is never forward-filled; a gap stays a gap
            daily[f] = wide[f].reindex(idx)
    daily.index.name = "date"

    m = long_df[long_df["field"].str.startswith("euribor")].pivot(index="date", columns="field", values="value")
    m["estr_rate_mavg"] = daily["estr_rate"].resample("MS").mean()
    m.index.name = "month"
    return daily, m


def add_derived(daily, monthly):
    daily["estr_dfr_spread_bp"] = (daily["estr_rate"] - daily["dfr"]) * 100
    daily["yc_slope_10y_2y_bp"] = (daily["yc_aaa_10y"] - daily["yc_aaa_2y"]) * 100
    monthly["euribor3m_estr_spread_bp"] = (monthly["euribor_3m"] - monthly["estr_rate_mavg"]) * 100
    return daily, monthly


# 4. VALIDATE ------------------------------------------------------------------
def apply_flags(daily, monthly, flags):
    daily["dq_status"] = "OK"; daily["dq_notes"] = ""
    monthly["dq_status"] = "OK"; monthly["dq_notes"] = ""
    for f in flags:
        is_monthly = f["field"].startswith("euribor")
        tbl = monthly if is_monthly else daily
        d = pd.Timestamp(f["date"])
        if d not in tbl.index:
            continue
        if f["severity"] == "ERROR" and f["value"] is not None:
            tbl.at[d, f["field"]] = np.nan  # withhold, never silently "correct"
        cur = tbl.at[d, "dq_status"]
        tbl.at[d, "dq_status"] = "ERROR" if "ERROR" in (cur, f["severity"]) else "WARN"
        tbl.at[d, "dq_notes"] = (tbl.at[d, "dq_notes"] + "; " if tbl.at[d, "dq_notes"] else "") + f"{f['field']}:{f['check']}"
    return daily, monthly


# 5. PUBLISH -------------------------------------------------------------------
DICTIONARY = [
    # file, field, type, unit, description, source / rule
    ("rates_daily.csv", "date", "date", "ISO 8601", "TARGET2 business day the rate refers to (not the publication day)", "T1, T3"),
    ("rates_daily.csv", "estr_rate", "float", "% p.a.", SERIES["estr_rate"]["label"], SERIES["estr_rate"]["key"]),
    ("rates_daily.csv", "estr_volume", "float", "EUR millions", SERIES["estr_volume"]["label"], SERIES["estr_volume"]["key"]),
    ("rates_daily.csv", "estr_transactions", "int", "count", SERIES["estr_transactions"]["label"], SERIES["estr_transactions"]["key"]),
    ("rates_daily.csv", "dfr", "float", "% p.a.", "ECB deposit facility rate in force on that day", SERIES["dfr"]["key"] + " · T3 forward-fill"),
    ("rates_daily.csv", "yc_aaa_2y", "float", "% p.a.", SERIES["yc_aaa_2y"]["label"], SERIES["yc_aaa_2y"]["key"]),
    ("rates_daily.csv", "yc_aaa_5y", "float", "% p.a.", SERIES["yc_aaa_5y"]["label"], SERIES["yc_aaa_5y"]["key"]),
    ("rates_daily.csv", "yc_aaa_10y", "float", "% p.a.", SERIES["yc_aaa_10y"]["label"], SERIES["yc_aaa_10y"]["key"]),
    ("rates_daily.csv", "estr_dfr_spread_bp", "float", "bp", "€STR minus deposit facility rate", "T4 derived"),
    ("rates_daily.csv", "yc_slope_10y_2y_bp", "float", "bp", "10-year minus 2-year AAA spot rate (curve slope)", "T4 derived"),
    ("rates_daily.csv", "dq_status", "enum", "OK / WARN / ERROR", "Worst data-quality result for the row", "T5, dq.py"),
    ("rates_daily.csv", "dq_notes", "string", "", "field:check for every flag raised on the row", "T5, dq.py"),
    ("rates_monthly.csv", "month", "date", "YYYY-MM-01", "Calendar month", "T1"),
    ("rates_monthly.csv", "euribor_1m … euribor_12m", "float", "% p.a.", "EURIBOR monthly averages (1M, 3M, 6M, 12M)", "FM/M.U2.EUR.RT.MM.EURIBOR*.HSTA"),
    ("rates_monthly.csv", "estr_rate_mavg", "float", "% p.a.", "Simple average of daily €STR in the month", "T4 derived"),
    ("rates_monthly.csv", "euribor3m_estr_spread_bp", "float", "bp", "EURIBOR 3M minus €STR monthly average (term & credit premium)", "T4 derived"),
    ("rates_long.csv", "date, field, value, unit, freq, source_key", "mixed", "", "Standardised layer: one row per observation, exactly as delivered by the ECB", "T1, T2"),
    ("dq_log.csv", "date, field, check, severity, value, detail, review, review_note", "mixed", "", "Every data-quality flag raised in this build, with its review outcome", "dq.py"),
]

TRANSFORMS = [
    ("T1", "Parse dates", "All dates converted to ISO 8601. Daily series keep the reference date (the day the rate applies to), not the publication date (€STR is published at 08:00 CET the next business day)."),
    ("T2", "Type & unit", "Values parsed as decimals exactly as delivered: no rounding, no rescaling. Rates stay in % per annum; spreads are converted to basis points only in derived fields."),
    ("T3", "Calendar alignment", "Every daily series is aligned to the TARGET2 business-day calendar. The ECB deposit rate is forward-filled because a policy rate stays in force until changed. Market series (€STR, yields) are never forward-filled: a missing value stays missing and is flagged."),
    ("T4", "Derived fields", "€STR − deposit rate spread; 10Y − 2Y curve slope; monthly average €STR; EURIBOR 3M − €STR spread. Each is computed only from fields in the same row/month."),
    ("T5", "Quality gate", "Values that fail an ERROR check are withheld (left blank) in the published files and logged; they are never silently corrected. WARN values are published with a flag."),
    ("T6", "Lineage", "Each build stores the raw ECB response, its SHA-256 hash, row count and fetch time, plus hashes of every published file, in manifest.json."),
]


def to_csv(df, name, **kw):
    path = OUT / name
    df.to_csv(path, **kw)
    return {"file": f"data/{name}", "rows": len(df), "sha256": sha256(path.read_bytes())}


def build(offline=False):
    OUT.mkdir(exist_ok=True)
    lineage = ingest(offline)
    long_df = standardise()
    daily, monthly = transform(long_df)
    daily, monthly = add_derived(daily, monthly)

    flags = dq.run_all(long_df, daily, monthly, policy_aware=True)
    naive_flags = dq.check_jumps(daily, policy_aware=False)
    # attach the human review outcome (dq_review.csv); new flags stay "Pending review"
    review = pd.read_csv(HERE / "dq_review.csv", dtype=str).set_index(["date", "field", "check"])
    for f in flags:
        k = (f["date"], f["field"], f["check"])
        f["review"] = review.at[k, "outcome"] if k in review.index else "Pending review"
        f["review_note"] = review.at[k, "note"] if k in review.index else ""
    daily, monthly = apply_flags(daily, monthly, flags)
    # recompute derived fields after withholding so they never use withheld values
    daily, monthly = add_derived(daily, monthly)

    outputs = []
    outputs.append(to_csv(daily.reset_index().assign(date=lambda x: x["date"].dt.strftime("%Y-%m-%d")),
                          "rates_daily.csv", index=False, float_format="%.6g"))
    outputs.append(to_csv(monthly.reset_index().assign(month=lambda x: x["month"].dt.strftime("%Y-%m-%d")),
                          "rates_monthly.csv", index=False, float_format="%.6g"))
    outputs.append(to_csv(long_df.assign(date=lambda x: x["date"].dt.strftime("%Y-%m-%d")),
                          "rates_long.csv", index=False, float_format="%.10g"))
    flag_df = pd.DataFrame(flags, columns=["date", "field", "check", "severity", "value", "detail", "review", "review_note"])
    outputs.append(to_csv(flag_df, "dq_log.csv", index=False))
    dict_df = pd.DataFrame(DICTIONARY, columns=["file", "field", "type", "unit", "description", "source_or_rule"])
    outputs.append(to_csv(dict_df, "data_dictionary.csv", index=False))

    bt = backtest.run(long_df, daily, monthly, flags, naive_flags)

    built = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest = {"pipeline_version": PIPELINE_VERSION, "built_at_utc": built,
                "coverage": {"from": START, "to": daily["estr_rate"].last_valid_index().strftime("%Y-%m-%d")},
                "sources": lineage, "outputs": outputs,
                "stages": ["ingest", "standardise", "transform", "validate", "publish", "backtest"]}
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2))

    page = page_payload(daily, monthly, flags, bt, manifest)
    (OUT / "page.json").write_text(json.dumps(page, separators=(",", ":")))
    print(f"Built {built}: {len(daily)} daily rows, {len(monthly)} months, "
          f"{len(flags)} flags ({sum(f['severity']=='ERROR' for f in flags)} errors)")
    return page


def _series(s, nd=4):
    s = s.dropna()
    return [[d.strftime("%Y-%m-%d"), round(float(v), nd)] for d, v in s.items()]


def page_payload(daily, monthly, flags, bt, manifest):
    last = daily["estr_rate"].last_valid_index()
    prev = daily["estr_rate"].loc[:last].dropna().index[-2]
    yc_last = daily[["yc_aaa_2y", "yc_aaa_5y", "yc_aaa_10y"]].dropna().index[-1]
    return {
        "built_at_utc": manifest["built_at_utc"], "coverage": manifest["coverage"],
        "latest": {
            "date": last.strftime("%Y-%m-%d"),
            "estr": round(daily.at[last, "estr_rate"], 3),
            "estr_chg_bp": round((daily.at[last, "estr_rate"] - daily.at[prev, "estr_rate"]) * 100, 1),
            "dfr": round(daily.at[last, "dfr"], 2),
            "spread_bp": round(daily.at[last, "estr_dfr_spread_bp"], 1),
            "volume_bn": round(daily.at[last, "estr_volume"] / 1000, 1),
            "yc_date": yc_last.strftime("%Y-%m-%d"),
            "yc_2y": round(daily.at[yc_last, "yc_aaa_2y"], 3),
            "yc_10y": round(daily.at[yc_last, "yc_aaa_10y"], 3),
            "slope_bp": round(daily.at[yc_last, "yc_slope_10y_2y_bp"], 1),
            "euribor_3m": round(monthly["euribor_3m"].dropna().iloc[-1], 3),
            "euribor_month": monthly["euribor_3m"].dropna().index[-1].strftime("%Y-%m"),
        },
        "chart": {
            "estr": _series(daily["estr_rate"], 3), "dfr": _series(daily["dfr"], 2),
            "volume": _series(daily["estr_volume"] / 1000, 1),
            "yc2": _series(daily["yc_aaa_2y"], 3), "yc5": _series(daily["yc_aaa_5y"], 3),
            "yc10": _series(daily["yc_aaa_10y"], 3),
            "eur1m": _series(monthly["euribor_1m"], 3), "eur3m": _series(monthly["euribor_3m"], 3),
            "eur6m": _series(monthly["euribor_6m"], 3), "eur12m": _series(monthly["euribor_12m"], 3),
            "estr_m": _series(monthly["estr_rate_mavg"], 3),
        },
        "dq": {
            "total_obs": int(daily[["estr_rate", "estr_volume", "estr_transactions", "yc_aaa_2y",
                                    "yc_aaa_5y", "yc_aaa_10y"]].notna().sum().sum() + monthly.filter(like="euribor_").notna().sum().sum()),
            "n_error": sum(f["severity"] == "ERROR" for f in flags),
            "n_warn": sum(f["severity"] == "WARN" for f in flags),
            "rows_ok_pct": round(100 * (daily["dq_status"] == "OK").mean(), 2),
            "n_reviewed": sum(f["review"] != "Pending review" for f in flags),
            "n_real_errors": sum(f["review"] == "Data error" for f in flags),
            "by_check": pd.Series([f["check"] for f in flags]).value_counts().to_dict() if flags else {},
            "recent": flags[::-1],
            "rules": [{"check": c, "severity": s, "rule": r} for c, s, r in dq.CHECK_DOCS],
        },
        "backtest": bt,
        "dictionary": [dict(zip(["file", "field", "type", "unit", "description", "source"], r)) for r in DICTIONARY],
        "transforms": [dict(zip(["id", "name", "rule"], t)) for t in TRANSFORMS],
        "sources": [{"field": k, **SERIES[k], **{kk: v[kk] for kk in ("fetched_at_utc", "raw_sha256", "raw_rows")}}
                    for k, v in manifest["sources"].items()],
        "outputs": manifest["outputs"],
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    build(ap.parse_args().offline)
