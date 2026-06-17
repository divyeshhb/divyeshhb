"""
Metric computations for the PnL dashboard.

Two lenses are supported everywhere:
  * 'usd'  -> money in USD (local-currency cost columns converted via FxRate)
  * 'bps'  -> metric_in_USD / AUM(date) * 10_000   (AUM = strategy AUM for the day)

Pure pandas; no rendering here.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

import config

# Canonical metrics: key -> source column. PNL has both LCY and USD; the cost
# columns are local-ccy; Value/Traded are already USD.
USD_NUMERATOR = {
    "PNL_USD": "PNL_USD",            # already USD (= PNL_LCY * FxRate)
    "Value_USD": "Value_USD",        # already USD
    "Dollar_Traded": "Dollar_Traded",
}
# Local-ccy columns get a "<col>_USD" companion = col * FxRate.
LCY_COLUMNS = list(config.LOCAL_CCY_COLUMNS)

# Columns we aggregate (USD basis). Each maps display-name -> USD column.
SUM_COLS_USD = {
    "PNL_USD": "PNL_USD",
    "TC": "TC_USD",
    "OC": "OC_USD",
    "TC_Trade": "TC_Trade_USD",
    "TC_Trade_VWAP": "TC_Trade_VWAP_USD",
    "TC_Trade_ExToClose": "TC_Trade_ExToClose_USD",
    "TC_Commission": "TC_Commission_USD",
    "ModelSlippage": "ModelSlippage_USD",
    "ModelSlippage_AM": "ModelSlippage_AM_USD",
    "ModelSlippage_PM": "ModelSlippage_PM_USD",
    "Commission": "Commission_USD",
    "Value_USD": "Value_USD",
    "Dollar_Traded": "Dollar_Traded",
}


# --------------------------------------------------------------------------- #
# Enrichment                                                                  #
# --------------------------------------------------------------------------- #
def enrich(df: pd.DataFrame, aum: pd.Series | None = None) -> pd.DataFrame:
    """Add geo labels, USD-converted metric columns and per-row AUM/bps."""
    df = df.copy()

    geo = df["Currency"].map(config.CURRENCY_GEO)
    df["Country"] = geo.map(lambda t: t[0] if isinstance(t, tuple) else "Other")
    df["Region"] = geo.map(lambda t: t[1] if isinstance(t, tuple) else "Other")
    df["Development"] = geo.map(lambda t: t[2] if isinstance(t, tuple) else "Other")
    df["AssetClass"] = df["AssetClassId"].map(config.ASSET_CLASS_NAMES).fillna("Other")
    df["Account"] = df["AccountId"].map(config.ACCOUNT_NAMES).fillna(
        df["AccountId"].astype(str))

    fx = df["FxRate"].replace(0, np.nan).fillna(1.0) if "FxRate" in df else 1.0
    # USD versions of local-currency cost columns (col * FxRate).
    for col in LCY_COLUMNS:
        if col in df.columns:
            df[col + "_USD"] = df[col] * fx
        else:
            df[col + "_USD"] = 0.0

    # Attach daily strategy AUM (joined on calendar date).
    if aum is not None:
        day = df["Date"].dt.normalize()
        df["AUM"] = day.map(aum).astype(float)
    else:
        df["AUM"] = np.nan

    return df


def _usd_col(df: pd.DataFrame, display: str) -> pd.Series:
    """Return the USD series for a display metric name."""
    col = SUM_COLS_USD.get(display, display)
    if col in df.columns:
        return df[col]
    return df.get(display, pd.Series(0.0, index=df.index))


# --------------------------------------------------------------------------- #
# Aggregations (always computed in USD; bps derived by dividing by AUM)        #
# --------------------------------------------------------------------------- #
def daily_totals(df: pd.DataFrame) -> pd.DataFrame:
    """One row per date with USD sums, the day's AUM, and bps versions."""
    usd_cols = [c for c in SUM_COLS_USD.values() if c in df.columns]
    g = df.groupby("Date")[usd_cols].sum()
    g.columns = [k for k, v in SUM_COLS_USD.items() if v in df.columns]
    g["AUM"] = df.groupby("Date")["AUM"].first()
    g = g.sort_index()
    g["CumPNL_USD"] = g["PNL_USD"].cumsum()
    # bps per day = USD / AUM * scale
    for c in ["PNL_USD", "TC", "OC", "ModelSlippage",
              "ModelSlippage_AM", "ModelSlippage_PM"]:
        if c in g.columns:
            g[c + "_bps"] = (g[c] / g["AUM"] * config.BPS_SCALE)
    g["CumPNL_bps"] = g["PNL_USD_bps"].cumsum() if "PNL_USD_bps" in g else np.nan
    return g


def group_totals(df: pd.DataFrame, by: str, aum_day: float | None = None) -> pd.DataFrame:
    """USD sums grouped by a column, plus bps using the day's AUM."""
    usd_cols = [c for c in SUM_COLS_USD.values() if c in df.columns]
    g = df.groupby(by)[usd_cols].sum()
    g.columns = [k for k, v in SUM_COLS_USD.items() if v in df.columns]
    if aum_day:
        g["PNL_bps"] = g["PNL_USD"] / aum_day * config.BPS_SCALE
        g["TC_bps"] = g["TC"] / aum_day * config.BPS_SCALE
    return g.sort_values("PNL_USD", ascending=False)


def kpi_summary(df_day: pd.DataFrame, aum_day: float | None) -> dict:
    pnl = _usd_col(df_day, "PNL_USD").sum()
    tc = _usd_col(df_day, "TC").sum()
    oc = _usd_col(df_day, "OC").sum()
    ms = _usd_col(df_day, "ModelSlippage").sum()
    comm = _usd_col(df_day, "TC_Commission").sum()
    gross = df_day["Value_USD"].abs().sum()
    turn = df_day["Dollar_Traded"].abs().sum()

    def bps(x):
        return x / aum_day * config.BPS_SCALE if aum_day else float("nan")

    return {
        "aum": aum_day,
        "pnl_usd": pnl, "pnl_bps": bps(pnl),
        "tc_usd": tc, "tc_bps": bps(tc),
        "oc_usd": oc, "oc_bps": bps(oc),
        "ms_usd": ms, "ms_bps": bps(ms),
        "comm_usd": comm, "comm_bps": bps(comm),
        "gross_exposure": gross, "gross_bps": bps(gross),
        "turnover": turn, "turnover_bps": bps(turn),
        "n_instruments": int((_usd_col(df_day, "PNL_USD") != 0).sum()),
        "n_winners": int((_usd_col(df_day, "PNL_USD") > 0).sum()),
        "n_losers": int((_usd_col(df_day, "PNL_USD") < 0).sum()),
    }


def cost_waterfall(df_day: pd.DataFrame, aum_day: float | None):
    """Cost components (USD and bps) ~ reconcile to reported TC."""
    rows = []
    for col, label in config.COST_COMPONENTS.items():
        usd = _usd_col(df_day, col).sum()
        rows.append({"component": label, "usd": usd,
                     "bps": usd / aum_day * config.BPS_SCALE if aum_day else np.nan})
    return pd.DataFrame(rows)


def winners_losers(df_day: pd.DataFrame, aum_day: float | None, n: int = config.TOP_N):
    d = df_day.copy()
    d["PNL_disp"] = _usd_col(d, "PNL_USD")
    d["TC_disp"] = _usd_col(d, "TC")
    d["PNL_bps"] = d["PNL_disp"] / aum_day * config.BPS_SCALE if aum_day else np.nan
    d["TC_bps"] = d["TC_disp"] / aum_day * config.BPS_SCALE if aum_day else np.nan
    ranked = d.sort_values("PNL_disp", ascending=False)
    cols = ["Ticker", "Country", "PNL_disp", "PNL_bps", "TC_disp", "TC_bps"]
    return ranked.head(n)[cols], ranked.tail(n)[cols].iloc[::-1]


# --------------------------------------------------------------------------- #
# Exception / anomaly detection (USD basis)                                    #
# --------------------------------------------------------------------------- #
def exceptions(df: pd.DataFrame, as_of: pd.Timestamp, aum_day: float | None) -> pd.DataFrame:
    lookback_start = as_of - pd.Timedelta(days=config.LOOKBACK_DAYS * 2)
    hist = df[(df["Date"] < as_of) & (df["Date"] >= lookback_start)].copy()
    today = df[df["Date"] == as_of].copy()
    hist["PNL_disp"] = _usd_col(hist, "PNL_USD")
    today["PNL_disp"] = _usd_col(today, "PNL_USD")
    today["TC_disp"] = _usd_col(today, "TC")
    today["OC_disp"] = _usd_col(today, "OC")

    stats = hist.groupby("Ticker")["PNL_disp"].agg(["mean", "std"])
    flags = []
    for _, r in today.iterrows():
        tk = r["Ticker"]
        if tk in stats.index and stats.loc[tk, "std"] and stats.loc[tk, "std"] > 0:
            z = (r["PNL_disp"] - stats.loc[tk, "mean"]) / stats.loc[tk, "std"]
            if abs(z) >= config.PNL_ZSCORE_FLAG:
                flags.append((abs(r["PNL_disp"]), tk, r["Country"], "Unusual PnL",
                              f"{r['PNL_disp']:,.0f} USD (z={z:+.1f} vs {config.LOOKBACK_DAYS}d)"))
        if aum_day and abs(r["Value_USD"]) > 0:
            tc_bps = r["TC_disp"] / aum_day * config.BPS_SCALE
            if abs(tc_bps) >= config.TC_BPS_FLAG and abs(r["TC_disp"]) >= config.MATERIAL_TC_USD:
                flags.append((abs(r["TC_disp"]), tk, r["Country"], "High transaction cost",
                              f"{tc_bps:+.1f} bps ({r['TC_disp']:,.0f} USD)"))
        if abs(r["OC_disp"]) >= config.MATERIAL_OC_USD:
            flags.append((abs(r["OC_disp"]), tk, r["Country"], "Opportunity cost",
                          f"{r['OC_disp']:,.0f} USD (missed/partial fill)"))
    flags.sort(key=lambda t: t[0], reverse=True)
    flags = flags[:config.MAX_EXCEPTIONS]
    return pd.DataFrame([f[1:] for f in flags],
                        columns=["Ticker", "Country", "Flag", "Detail"])
