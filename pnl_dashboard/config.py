"""
Configuration for the PnL dashboard: column contract, label/grouping maps,
risk (vol-adjustment) factors and exception-detection thresholds.

Everything that is environment- or desk-specific lives here so the rest of the
code stays generic.
"""

# --------------------------------------------------------------------------- #
# 1. Column contract                                                          #
# --------------------------------------------------------------------------- #
# These are the columns the dashboard relies on. fetch_pnl_data() must return
# a DataFrame containing (at least) these. Extra columns are ignored.
REQUIRED_COLUMNS = [
    "AccountId", "Date", "SecurityId", "Ticker", "AssetClassId", "Currency",
    "CurrentUnits", "PreviousDayUnits", "TransactionUnits",
    "PNL_USD", "Value_USD", "Dollar_Traded",
    "TC", "OC", "TC_Trade", "TC_Trade_VWAP", "TC_Trade_ExToClose",
    "TC_Commission", "ModelSlippage", "ModelSlippage_AM", "ModelSlippage_PM",
    "Commission",
]

# Metrics shown in the cost-decomposition waterfall (component -> label).
# Trade cost uses the VWAP benchmark to stay consistent with the headline TC.
COST_COMPONENTS = {
    "TC_Trade_VWAP": "Trade cost (VWAP)",
    "TC_Commission": "Commission",
    "ModelSlippage": "Model slippage",
    "OC": "Opportunity cost",
}

# --------------------------------------------------------------------------- #
# 1b. Currency basis & bps                                                    #
# --------------------------------------------------------------------------- #
# PNL_USD = PNL_LCY * FxRate, i.e. FxRate converts local currency -> USD.
# The cost columns below are reported in LOCAL CURRENCY, so they must be
# multiplied by FxRate to express them in USD (and for the bps formula).
# `PNL_USD`, `Value_USD`, `Dollar_Traded` are already in USD.
LOCAL_CCY_COLUMNS = [
    "TC", "OC", "TC_Trade", "TC_Trade_VWAP", "TC_Trade_ExToClose",
    "TC_Commission", "ModelSlippage", "ModelSlippage_AM", "ModelSlippage_PM",
    "Commission",
]
# Already-USD columns (never multiplied by FxRate).
USD_COLUMNS = ["PNL_USD", "Value_USD", "Dollar_Traded"]

# The $ view sums money across many currencies, so costs must be converted to
# USD first (otherwise EUR + JPY + KRW are added blindly). Set False only if you
# deliberately want the raw, un-converted local-currency column sums.
DOLLAR_VIEW_FX_CONVERT_COSTS = True

# bps = metric_in_USD / AUM(date) * 10_000   (AUM is the strategy AUM for the day)
BPS_SCALE = 10_000.0

# Which column to display as "TC" / "Transaction cost" in the headline KPI,
# the winners/losers, country and instrument tables, and the high-cost flag.
# The feed's `TC` is a broad total; the desk reports execution cost vs the VWAP
# benchmark, so we show TC_Trade_VWAP. (The cost waterfall still shows the full
# component decomposition separately.)
TC_DISPLAY_COLUMN = "TC_Trade_VWAP"

# AUM is keyed by its own AccountId; map the PnL account -> the AUM account that
# represents the same strategy. If a PnL account is absent here, AUM is joined
# on Date only (single-strategy feed).
PNL_TO_AUM_ACCOUNT = {
    631: 630,   # MACEQ trading account 631  <-> AUM account 630
}

# --------------------------------------------------------------------------- #
# 2. Labels / grouping                                                        #
# --------------------------------------------------------------------------- #
ASSET_CLASS_NAMES = {
    2: "Equities",
    # extend as other asset-class ids appear in the data
}

ACCOUNT_NAMES = {
    631: "MACEQ (Equity Index Futures)",
    901: "ARPMSF",
    # extend with the real account-id -> name map
}

# Risk level each strategy is dialled to (annualised vol). Used to derive the
# vol-adjustment factor so books run at different risk can be compared on a
# common basis.  VolAdj metric = raw metric * (TARGET_RISK / strategy_risk).
STRATEGY_RISK = {
    631: 0.065,   # MACEQ ~ 6-7%
    # "EFF_GETT": 0.115,  # ~11-12%
}
TARGET_RISK = 0.10  # common risk level to normalise everyone to

# Currency -> (Country, Region, Development) used to group equity-index futures
# by geography (the raw `Country` column is not populated in the feed).
CURRENCY_GEO = {
    "USD": ("United States", "Americas", "Developed"),
    "CAD": ("Canada",        "Americas", "Developed"),
    "EUR": ("Eurozone",      "Europe",   "Developed"),
    "GBP": ("United Kingdom","Europe",   "Developed"),
    "SEK": ("Sweden",        "Europe",   "Developed"),
    "PLN": ("Poland",        "Europe",   "Emerging"),
    "JPY": ("Japan",         "Asia",     "Developed"),
    "HKD": ("Hong Kong",     "Asia",     "Developed"),
    "SGD": ("Singapore",     "Asia",     "Developed"),
    "AUD": ("Australia",     "Asia-Pac", "Developed"),
    "KRW": ("South Korea",   "Asia",     "Emerging"),
    "MYR": ("Malaysia",      "Asia",     "Emerging"),
    "THB": ("Thailand",      "Asia",     "Emerging"),
    "ZAR": ("South Africa",  "Africa",   "Emerging"),
}

# --------------------------------------------------------------------------- #
# 3. Exception-detection thresholds                                           #
# --------------------------------------------------------------------------- #
# Trailing window (trading days) used to build each instrument's own baseline.
LOOKBACK_DAYS = 60
# |z-score| above which an instrument's PnL is flagged as unusual.
PNL_ZSCORE_FLAG = 2.5
# Cost (bps of traded value) above which execution is flagged...
TC_BPS_FLAG = 15.0
# ...but only when the dollar impact is also material (avoids flagging huge bps
# on tiny-notional names). USD floors for each flag type:
MATERIAL_TC_USD = 10_000.0
MATERIAL_OC_USD = 5_000.0
# Cap the attention panel to the most severe items (by |USD| impact).
MAX_EXCEPTIONS = 12
# How many names to show in the winners / losers panels.
TOP_N = 8
