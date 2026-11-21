"""Data-quality checks run before anything is published.

Each check returns a list of flags:
    {date, field, check, severity, value, detail}

Severity:
    ERROR - value is implausible or the record is broken. It is withheld
            (set to blank) in the published dataset and logged.
    WARN  - value is published but marked for review.

Thresholds live in RULES so they are documented in one place and shown on
the website exactly as the code uses them.
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd

RULES = {
    "range_pct": (-1.0, 10.0),          # any rate outside this band is implausible
    "estr_dfr_band": (-0.50, 0.50),     # €STR must sit within ±50bp of the ECB deposit rate
    "stale_run": {"estr_rate": 5, "yc_aaa_2y": 3, "yc_aaa_5y": 3, "yc_aaa_10y": 3,
                  "estr_volume": 2, "estr_transactions": 3},
    "jump_window": 60,                  # business days of history for the robust baseline
    "jump_z": 8.0,                      # robust z-score threshold
    "jump_floor_bp": {"estr_rate": 5.0, "yc_aaa_2y": 15.0, "yc_aaa_5y": 15.0, "yc_aaa_10y": 15.0},
    "euribor_estr_spread": (-0.50, 1.00),  # monthly EURIBOR 3M minus monthly avg €STR, % points
}

RATE_FIELDS = ["estr_rate", "dfr", "yc_aaa_2y", "yc_aaa_5y", "yc_aaa_10y"]


def _flag(d, field, check, severity, value, detail):
    return {"date": pd.Timestamp(d).strftime("%Y-%m-%d"), "field": field, "check": check,
            "severity": severity,
            "value": None if value is None or (isinstance(value, float) and np.isnan(value)) else round(float(value), 6),
            "detail": detail}


# ---------- calendar -------------------------------------------------------

def _easter(y: int) -> date:
    """Anonymous Gregorian algorithm."""
    a = y % 19; b, c = divmod(y, 100); d, e = divmod(b, 4); f = (b + 8) // 25
    g = (b - f + 1) // 3; h = (19 * a + b - d - g + 15) % 30; i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7; m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(y, month, day + 1)


def target2_days(start, end) -> pd.DatetimeIndex:
    """TARGET2 business days: weekdays excluding 1 Jan, Good Friday, Easter Monday,
    1 May, 25 and 26 Dec. €STR is published for each of these days."""
    days = pd.bdate_range(start, end)
    hol = set()
    for y in range(days.min().year, days.max().year + 1):
        e = _easter(y)
        hol |= {date(y, 1, 1), e - timedelta(days=2), e + timedelta(days=1),
                date(y, 5, 1), date(y, 12, 25), date(y, 12, 26)}
    return days[~days.isin(pd.to_datetime(sorted(hol)))]


# ---------- individual checks ---------------------------------------------

def check_duplicates(long_df):
    dup = long_df[long_df.duplicated(["field", "date"], keep=False)]
    return [_flag(r.date, r.field, "duplicate", "ERROR", r.value,
                  "Same series and date delivered more than once")
            for r in dup.itertuples()]


def check_completeness(daily, fields=("estr_rate", "estr_volume", "estr_transactions"), severity="ERROR"):
    expected = target2_days(daily.index.min(), daily.index.max())
    flags = []
    for f in fields:
        present = daily[f].dropna().index
        for d in expected.difference(present):
            flags.append(_flag(d, f, "missing_business_day", severity, None,
                               "No observation on an expected TARGET2 business day"))
    return flags


def check_range(daily):
    lo, hi = RULES["range_pct"]
    flags = []
    for f in RATE_FIELDS:
        s = daily[f].dropna()
        for d, v in s[(s < lo) | (s > hi)].items():
            flags.append(_flag(d, f, "out_of_range", "ERROR", v,
                               f"Outside plausible band [{lo}%, {hi}%]"))
    for f in ("estr_volume", "estr_transactions"):
        s = daily[f].dropna()
        for d, v in s[s <= 0].items():
            flags.append(_flag(d, f, "non_positive", "ERROR", v, "Volume/count must be > 0"))
    return flags


def check_policy_corridor(daily):
    lo, hi = RULES["estr_dfr_band"]
    s = (daily["estr_rate"] - daily["dfr"]).dropna()
    return [_flag(d, "estr_rate", "outside_policy_corridor", "ERROR", daily.at[d, "estr_rate"],
                  f"€STR − deposit rate = {v*100:+.1f}bp, outside [{lo*100:+.0f}bp, {hi*100:+.0f}bp]")
            for d, v in s[(s < lo) | (s > hi)].items()]


def check_stale(daily):
    flags = []
    for f, n in RULES["stale_run"].items():
        s = daily[f].dropna()
        run_id = (s != s.shift()).cumsum()
        run_len = s.groupby(run_id).transform("size")
        pos_in_run = s.groupby(run_id).cumcount() + 1
        hit = s[(run_len >= n) & (pos_in_run == n)]  # flag once, when the run reaches n
        for d, v in hit.items():
            flags.append(_flag(d, f, "stale_value", "WARN", v,
                               f"Identical value for {int(run_len[d])} consecutive observations (limit {n})"))
    return flags


def _rolling_med_mad(x, w, min_obs=20):
    """Median and MAD of the previous w values (excluding today), NaN-aware."""
    n = len(x)
    med = np.full(n, np.nan); mad = np.full(n, np.nan)
    padded = np.concatenate([np.full(w, np.nan), x])
    win = np.lib.stride_tricks.sliding_window_view(padded[:-1], w)[:n]  # window ends at t-1
    ok = np.sum(~np.isnan(win), axis=1) >= min_obs
    with np.errstate(all="ignore"):
        m = np.nanmedian(win[ok], axis=1)
        med[ok] = m
        mad[ok] = np.nanmedian(np.abs(win[ok] - m[:, None]), axis=1)
    return med, mad


def check_jumps(daily, policy_aware=True):
    """Robust jump test: today's change versus the median/MAD of the previous
    `jump_window` changes. Policy-aware mode subtracts the change in the ECB
    deposit rate first, so a rate cut does not raise a false alarm on €STR."""
    w, z_lim = RULES["jump_window"], RULES["jump_z"]
    flags = []
    for f, floor_bp in RULES["jump_floor_bp"].items():
        s = daily[f].dropna()
        chg = s.diff()
        if policy_aware and f == "estr_rate":
            chg = chg - daily["dfr"].reindex(s.index).diff().fillna(0)
        med, mad = _rolling_med_mad(chg.to_numpy(), w)
        med, mad = pd.Series(med, chg.index), pd.Series(mad * 1.4826, chg.index)
        z = (chg - med) / mad.replace(0, np.nan)
        hit = chg[(z.abs() > z_lim) & (chg.abs() * 100 > floor_bp)]
        for d, c in hit.items():
            flags.append(_flag(d, f, "abnormal_move", "WARN", s[d],
                               f"Move of {c*100:+.1f}bp (robust z = {z[d]:+.1f}); "
                               f"threshold |z|>{z_lim:g} and >{floor_bp:g}bp"
                               + (" after removing policy-rate change" if policy_aware and f == "estr_rate" else "")))
    return flags


def check_euribor_vs_estr(monthly):
    lo, hi = RULES["euribor_estr_spread"]
    s = (monthly["euribor_3m"] - monthly["estr_rate_mavg"]).dropna()
    return [_flag(d, "euribor_3m", "cross_series_inconsistency", "WARN", monthly.at[d, "euribor_3m"],
                  f"EURIBOR 3M − €STR monthly average = {v*100:+.0f}bp, outside [{lo*100:+.0f}, {hi*100:+.0f}]bp")
            for d, v in s[(s < lo) | (s > hi)].items()]


def run_all(long_df, daily, monthly, policy_aware=True):
    flags = (check_duplicates(long_df) + check_completeness(daily)
             + check_completeness(daily, ("yc_aaa_2y", "yc_aaa_5y", "yc_aaa_10y"), severity="WARN")
             + check_range(daily)
             + check_policy_corridor(daily) + check_stale(daily)
             + check_jumps(daily, policy_aware) + check_euribor_vs_estr(monthly))
    return sorted(flags, key=lambda x: (x["date"], x["field"], x["check"]))


CHECK_DOCS = [
    ("duplicate", "ERROR", "Same series and date delivered twice. Kept: neither until resolved."),
    ("missing_business_day", "ERROR", "No €STR observation on a TARGET2 business day (weekdays excl. 1 Jan, Good Friday, Easter Monday, 1 May, 25–26 Dec). A missing yield-curve day is a WARN: the gap is left blank, never filled."),
    ("out_of_range", "ERROR", "Any rate outside −1% to 10%. Catches decimal-shift and unit errors (e.g. 3.9 delivered as 390)."),
    ("non_positive", "ERROR", "€STR volume or transaction count ≤ 0."),
    ("outside_policy_corridor", "ERROR", "€STR more than 50bp away from the ECB deposit facility rate: economically implausible given how €STR is anchored."),
    ("stale_value", "WARN", "Identical value repeated for too many observations (€STR rate 5, yields 3, €STR volume 2), a typical sign of a frozen feed."),
    ("abnormal_move", "WARN", "Daily change more than 8 robust standard deviations (median/MAD of the last 60 days) from normal and above a size floor (€STR 5bp, yields 15bp). For €STR the ECB policy-rate change is removed first."),
    ("cross_series_inconsistency", "WARN", "Monthly EURIBOR 3M minus monthly average €STR outside −50bp to +100bp."),
]
