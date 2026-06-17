"""
Metric computations for the PnL dashboard.

Pure pandas; no rendering here. Everything works on the `pnl_data` schema
returned by data_source.fetch_pnl_data().
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config

BPS = 1e4


# --------------------------------------------------------------------------- #
# Enrichment                                                                  #
# --------------------------------------------------------------------------- #
def enrich(df: pd.DataFrame) -> pd.DataFrame:
    """Add derived label / lens columns used across the dashboard."""
    df = df.copy()
    geo = df["Currency"].map(config.CURRENCY_GEO)
    df["Country"] = geo.map(lambda t: t[0] if isinstance(t, tuple) else "Other")
    df["Region"] = geo.map(lambda t: t[1] if isinstance(t, tuple) else "Other")
    df["Development"] = geo.map(lambda t: t[2] if isinstance(t, tuple) else "Other")
    df["AssetClass"] = df["AssetClassId"].map(config.ASSET_CLASS_NAMES).fillna("Other")
    df["Account"] = df["AccountId"].map(config.ACCOUNT_NAMES).fillna(
        df["AccountId"].astype(str))

    # Vol-adjustment factor so strategies at different risk compare like-for-like.
    risk = df["AccountId"].map(config.STRATEGY_RISK)
    df["VolAdjFactor"] = np.where(risk.notna() & (risk != 0),
                                  config.TARGET_RISK / risk, 1.0)

    # bps lens (per-row, vs traded notional). Guard divide-by-zero.
    denom = df["Value_USD"].abs().replace(0, np.nan)
    df["PNL_bps"] = (df["PNL_USD"] / denom * BPS).fillna(0.0)
    df["TC_bps"] = (df["TC"] / denom * BPS).fillna(0.0)
    return df


def lens_value(df: pd.DataFrame, col: str, lens: str) -> pd.Series:
    """Return `col` expressed in the requested lens: 'usd' | 'bps' | 'voladj'."""
    if lens == "usd":
        return df[col]
    if lens == "voladj":
        return df[col] * df["VolAdjFactor"]
    if lens == "bps":
        denom = df["Value_USD"].abs().replace(0, np.nan)
        return (df[col] / denom * BPS).fillna(0.0)
    raise ValueError(lens)


# --------------------------------------------------------------------------- #
# Aggregations                                                                #
# --------------------------------------------------------------------------- #
SUM_COLS = ["PNL_USD", "TC", "OC", "TC_Trade", "TC_Trade_VWAP",
            "TC_Trade_ExToClose", "TC_Commission", "ModelSlippage",
            "ModelSlippage_AM", "ModelSlippage_PM", "Commission",
            "Value_USD", "Dollar_Traded"]


def daily_totals(df: pd.DataFrame) -> pd.DataFrame:
    """One row per date: summed metrics (whole book)."""
    g = df.groupby("Date")[SUM_COLS].sum().sort_index()
    g["CumPNL_USD"] = g["PNL_USD"].cumsum()
    return g


def group_totals(df: pd.DataFrame, by: str) -> pd.DataFrame:
    """Summed metrics grouped by an arbitrary column (e.g. 'Country')."""
    g = df.groupby(by)[SUM_COLS].sum()
    denom = g["Value_USD"].abs().replace(0, np.nan)
    g["PNL_bps"] = (g["PNL_USD"] / denom * BPS).fillna(0.0)
    g["TC_bps"] = (g["TC"] / denom * BPS).fillna(0.0)
    return g.sort_values("PNL_USD", ascending=False)


def kpi_summary(df_day: pd.DataFrame) -> dict:
    """Headline numbers for a single day's slice."""
    val = df_day["Value_USD"].abs().sum()
    pnl = df_day["PNL_USD"].sum()
    return {
        "pnl_usd": pnl,
        "pnl_bps": pnl / val * BPS if val else 0.0,
        "tc": df_day["TC"].sum(),
        "oc": df_day["OC"].sum(),
        "model_slippage": df_day["ModelSlippage"].sum(),
        "commission": df_day["TC_Commission"].sum(),
        "gross_exposure": val,
        "turnover": df_day["Dollar_Traded"].abs().sum(),
        "n_instruments": int((df_day["PNL_USD"] != 0).sum()),
        "n_winners": int((df_day["PNL_USD"] > 0).sum()),
        "n_losers": int((df_day["PNL_USD"] < 0).sum()),
    }


def cost_waterfall(df_day: pd.DataFrame) -> pd.DataFrame:
    """Cost-component breakdown for a day (components ~ sum to reported TC)."""
    rows = [{"component": label, "value": df_day[col].sum()}
            for col, label in config.COST_COMPONENTS.items() if col in df_day]
    return pd.DataFrame(rows)


def winners_losers(df_day: pd.DataFrame, n: int = config.TOP_N):
    cols = ["Ticker", "Country", "PNL_USD", "PNL_bps", "TC", "Value_USD"]
    cols = [c for c in cols if c in df_day.columns]
    ranked = df_day.sort_values("PNL_USD", ascending=False)
    return ranked.head(n)[cols], ranked.tail(n)[cols].iloc[::-1]


# --------------------------------------------------------------------------- #
# Exception / anomaly detection                                               #
# --------------------------------------------------------------------------- #
def exceptions(df: pd.DataFrame, as_of: pd.Timestamp) -> pd.DataFrame:
    """Flag instruments on `as_of` that are unusual vs their own trailing history
    or that show expensive execution. Returns a tidy table of flags."""
    lookback_start = as_of - pd.Timedelta(days=config.LOOKBACK_DAYS * 2)  # cal->approx
    hist = df[(df["Date"] < as_of) & (df["Date"] >= lookback_start)]
    today = df[df["Date"] == as_of]

    stats = hist.groupby("Ticker")["PNL_USD"].agg(["mean", "std"])
    flags = []  # (severity_usd, ticker, country, flag, detail)
    for _, r in today.iterrows():
        tk = r["Ticker"]
        # 1) PnL z-score vs own history
        if tk in stats.index and stats.loc[tk, "std"] and stats.loc[tk, "std"] > 0:
            z = (r["PNL_USD"] - stats.loc[tk, "mean"]) / stats.loc[tk, "std"]
            if abs(z) >= config.PNL_ZSCORE_FLAG:
                flags.append((abs(r["PNL_USD"]), tk, r["Country"], "Unusual PnL",
                              f"{r['PNL_USD']:,.0f} USD (z={z:+.1f} vs {config.LOOKBACK_DAYS}d)"))
        # 2) Expensive execution: large in bps AND material in dollars
        if r["Dollar_Traded"] and abs(r["Value_USD"]) > 0:
            tc_bps = r["TC"] / abs(r["Value_USD"]) * BPS
            if abs(tc_bps) >= config.TC_BPS_FLAG and abs(r["TC"]) >= config.MATERIAL_TC_USD:
                flags.append((abs(r["TC"]), tk, r["Country"], "High transaction cost",
                              f"{tc_bps:+.0f} bps ({r['TC']:,.0f} USD)"))
        # 3) Material opportunity cost (missed / partial fills)
        if abs(r["OC"]) >= config.MATERIAL_OC_USD:
            flags.append((abs(r["OC"]), tk, r["Country"], "Opportunity cost",
                          f"{r['OC']:,.0f} USD (missed/partial fill)"))
    flags.sort(key=lambda t: t[0], reverse=True)
    flags = flags[:config.MAX_EXCEPTIONS]
    return pd.DataFrame([f[1:] for f in flags],
                        columns=["Ticker", "Country", "Flag", "Detail"])
