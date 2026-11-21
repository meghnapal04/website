"""Backtest of the data-quality checks.

Question: if a known error had reached the real €STR history, would dq.py
have caught it?

Method (fault injection, fixed random seed so results are reproducible):
  * Take the real published history as the baseline and record the flags it
    already raises.
  * For each error type, run TRIALS rounds. In each round inject PER_TRIAL
    errors into €STR at random dates, at least 75 business days apart so the
    errors do not mask each other.
  * Re-run every check. An error counts as detected if a NEW flag (not in
    the baseline) appears on the injected field inside the injected window.
  * Recall = detected / injected, per error type.

It also compares the jump rule with and without the policy-rate adjustment
on the real history, to show how many alerts are caused by ECB rate decisions
rather than by data problems.
"""
import numpy as np
import pandas as pd

import dq

SEED, TRIALS, PER_TRIAL, GAP, WARMUP = 42, 10, 20, 75, 70

ERROR_TYPES = [
    ("decimal_shift", "Value delivered ×100 (unit error, e.g. 3.9 → 390)"),
    ("sign_flip", "Sign dropped or flipped (−0.5 → +0.5)"),
    ("spike_large", "One-day spike of 15–50bp"),
    ("spike_medium", "One-day spike of 5–15bp"),
    ("spike_small", "One-day spike of 2–5bp"),
    ("stale_feed", "Feed frozen: previous value repeated 4–8 days"),
    ("missing_day", "Whole business day missing from the feed"),
    ("duplicate", "Same date delivered twice"),
]


def _keys(flags):
    return {(f["date"], f["field"], f["check"]) for f in flags}


def _positions(rng, n):
    cand = np.arange(WARMUP, n - 10)
    rng.shuffle(cand)
    chosen = []
    for c in cand:
        if all(abs(c - x) >= GAP for x in chosen):
            chosen.append(c)
        if len(chosen) == PER_TRIAL:
            break
    return sorted(chosen)


def _inject(kind, daily, long_df, pos, rng):
    """Return modified copies and, per injection, the window (start, end) to look in."""
    d = daily.copy(); l = long_df
    idx = d.index
    s = d["estr_rate"]
    windows, extra = [], []
    for p in pos:
        t = idx[p]
        if kind == "decimal_shift":
            d.at[t, "estr_rate"] = s.iloc[p] * 100; windows.append((p, p))
        elif kind == "sign_flip":
            d.at[t, "estr_rate"] = -s.iloc[p] if s.iloc[p] != 0 else 0.5; windows.append((p, p))
        elif kind.startswith("spike"):
            lo, hi = {"spike_large": (15, 50), "spike_medium": (5, 15), "spike_small": (2, 5)}[kind]
            d.at[t, "estr_rate"] = s.iloc[p] + rng.choice([-1, 1]) * rng.uniform(lo, hi) / 100
            windows.append((p, p + 1))
        elif kind == "stale_feed":
            k = int(rng.integers(4, 9))
            d.iloc[p:p + k, d.columns.get_loc("estr_rate")] = s.iloc[p - 1]
            windows.append((p, p + k))
        elif kind == "missing_day":
            d.loc[t, ["estr_rate", "estr_volume", "estr_transactions"]] = np.nan; windows.append((p, p))
        elif kind == "duplicate":
            row = long_df[(long_df["field"] == "estr_rate") & (long_df["date"] == t)]
            extra.append(row); windows.append((p, p))
    if extra:
        l = pd.concat([long_df] + extra, ignore_index=True)
    return d, l, windows


def run(long_df, daily, monthly, baseline_flags, naive_flags):
    rng = np.random.default_rng(SEED)
    base = _keys(baseline_flags)
    idx = daily.index
    results = []
    for kind, desc in ERROR_TYPES:
        injected = detected = 0
        caught_by = {}
        for _ in range(TRIALS):
            pos = _positions(rng, len(idx))
            d2, l2, windows = _inject(kind, daily, long_df, pos, rng)
            new = [f for f in dq.run_all(l2, d2, monthly) if (f["date"], f["field"], f["check"]) not in base]
            new = [f for f in new if f["field"] == "estr_rate" or (kind == "missing_day" and f["field"].startswith("estr"))]
            new_dates = {}
            for f in new:
                new_dates.setdefault(pd.Timestamp(f["date"]), set()).add(f["check"])
            for a, b in windows:
                injected += 1
                hit = set()
                for t in idx[a:b + 1]:
                    hit |= new_dates.get(t, set())
                if hit:
                    detected += 1
                    for c in hit:
                        caught_by[c] = caught_by.get(c, 0) + 1
        results.append({"error_type": kind, "description": desc, "injected": injected,
                        "detected": detected, "recall_pct": round(100 * detected / injected, 1),
                        "caught_by": sorted(caught_by, key=caught_by.get, reverse=True)})

    # Policy-aware vs naive jump rule on the real history
    dfr_change_days = set(daily.index[daily["dfr"].diff().fillna(0) != 0].strftime("%Y-%m-%d"))
    naive_estr = [f for f in naive_flags if f["field"] == "estr_rate"]
    aware_estr = [f for f in baseline_flags if f["field"] == "estr_rate" and f["check"] == "abnormal_move"]
    n_obs = int(daily[["estr_rate", "estr_volume", "estr_transactions", "yc_aaa_2y", "yc_aaa_5y", "yc_aaa_10y"]].notna().sum().sum()
                + monthly.filter(like="euribor_").notna().sum().sum())
    return {
        "seed": SEED, "trials": TRIALS, "per_trial": PER_TRIAL,
        "results": results,
        "real_history": {
            "observations_checked": n_obs,
            "warn_alerts": sum(f["severity"] == "WARN" for f in baseline_flags),
            "alerts_per_1000_obs": round(1000 * sum(f["severity"] == "WARN" for f in baseline_flags) / n_obs, 2),
            "estr_jump_alerts_naive": len(naive_estr),
            "estr_jump_alerts_naive_on_policy_days": sum(f["date"] in dfr_change_days for f in naive_estr),
            "estr_jump_alerts_policy_aware": len(aware_estr),
            "policy_change_days": len(dfr_change_days),
            "naive_alert_dates": [f["date"] for f in naive_estr],
        },
    }
