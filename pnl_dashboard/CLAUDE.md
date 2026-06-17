# CLAUDE.md — PnL Dashboard project context

Context for future sessions/contributors. Read this before changing code.

## Goal

A hedge-fund desk reviews a **daily PnL report of a futures portfolio**. Today
that review is manual (eyeball the numbers, investigate anything odd). This
project automates it: read the daily PnL feed and produce a **self-contained
HTML dashboard** that surfaces meaningful insights (what made/lost money, why
cost was high, did we trade on time, what needs attention).

Primary intended delivery is an **emailed morning (T+1) summary**; the HTML is
built so it can also be opened interactively. An interactive web app (Streamlit)
is a possible later phase, not built yet.

## Data contract (THE most important thing)

All data comes through **one function** — the SQL plug-in point:

```python
# data_source.py
fetch_pnl_data(start_date, end_date, account_id=None) -> pd.DataFrame
```

It must return a DataFrame with the **`pnl_data`** schema (see
`config.REQUIRED_COLUMNS`). This is the schema of the workbook the user provided.
Currently the body reads a sample Excel; production wires `_load_from_sql()` to a
SQL query and sets `USE_SQL = True`. **Do not change the schema contract casually
— metrics & rendering depend on it.**

Grain: **one row per instrument per account per trade date.**

Sample/reference data characteristics (account 631, what we built against):
- Single account `631` = MACEQ equity-index-futures book; `AssetClassId = 2`
  (Equities); all instruments are Bloomberg index futures ("… Index").
- 494 trading days (2024-07-25 → 2026-06-16), ~32–39 instruments/day.
- 14 currencies (used as the country/region proxy — the `Country` column in the
  feed is NOT populated).

### Key columns & confirmed meanings (from the user)
- `PNL_USD` — daily P&L in USD. (`PNL_LCY` = local currency.)
- `TC` — total transaction cost; decomposes ~ into `TC_Trade` + `TC_Commission` +
  `ModelSlippage` (verified to reconcile within ~2%). **Sign convention not yet
  confirmed** — both signs appear; confirm whether negative = cost.
- `TC_Trade`, `TC_Trade_VWAP`, `TC_Trade_ExToClose` — trade cost vs different
  benchmarks.
- `ModelSlippage` (+ `_AM` / `_PM`) — realised vs model-expected price; AM+PM
  splits exactly. Used for "did we trade at the right time?".
- `OC` = **Opportunity Cost** — cost of missed / partial fills (sparse; only on
  affected names).
- `NetMoney` — **IGNORE** (dropped from views per user).
- `Value_USD` — gross notional (used as the bps denominator: `metric/|Value_USD|*1e4`).
- `Dollar_Traded` — traded notional (turnover / participation).
- `Commission`, `EB_ExecutionCost` populated; `Dividend`, `SwapNPV_TR`,
  `CH_ClearingCost`, `PB_PerTradeCost` are all zero in the sample.

### Three reporting lenses
- **USD** — actual dollars.
- **Bps** — per traded notional.
- **VolAdj Bps** — cross-strategy risk normalisation. Strategies are the SAME
  strategy run at different vol targets (MACEQ ~6–7%, EFF_GETT ~11–12%);
  `VolAdjFactor = TARGET_RISK / strategy_risk` (config). This is the correct lens
  for comparing books. Currently `metrics.lens_value()` supports all three;
  charts default to USD. **A UI lens toggle is not built yet.**

### MAC vs ETF (not yet surfaced in the dashboard)
MACEQ is futures-only, but trades **ETFs of some futures to reduce tracking
error**. The original combined report split each figure into MAC (futures sleeve)
vs ETF (tracking sleeve). The `pnl_data` feed we built against does not carry that
split; folding it in is a planned enhancement.

## Architecture

| file | role |
|------|------|
| `data_source.py` | **SQL plug-in point** (`fetch_pnl_data`) + Excel sample fallback + schema validation |
| `config.py` | column contract, `CURRENCY_GEO`, `STRATEGY_RISK`/`TARGET_RISK`, exception thresholds, account/asset-class names |
| `metrics.py` | `enrich`, `lens_value`, aggregations (`daily_totals`, `group_totals`, `kpi_summary`, `cost_waterfall`, `winners_losers`), `exceptions` |
| `dashboard.py` | Plotly chart builders + HTML table builders + page assembly (`build_html`) + CLI (`main`) |

Flow: `fetch_pnl_data` → `metrics.enrich` → aggregations/exceptions →
`dashboard.build_html` → write `pnl_dashboard.html` (Plotly via CDN).

Pure-pandas metrics, no rendering logic leaks into `metrics.py`; all HTML/CSS is
in `dashboard.py` (`_PAGE` template at the bottom of the file).

## Dashboard sections (as-of the latest date in the range)
1. Headline KPIs (net PnL USD+bps, TC, model slippage, opportunity cost, gross
   exposure, turnover, win/loss counts).
2. **"What needs attention"** — exception panel: PnL z-score vs each instrument's
   own trailing history, materially expensive execution (bps AND $ floor),
   material opportunity cost; ranked by $ impact, capped at `MAX_EXCEPTIONS`.
3. Cumulative PnL curve + daily PnL bars (period).
4. Cost waterfall (components → reported TC) + AM-vs-PM model slippage.
5. PnL by country (bar) + country table.
6. Top winners / losers.
7. Full instrument detail table.

## Run / extend

```bash
pip install -r requirements.txt
python dashboard.py --account 631 --start 2026-05-01 --end 2026-06-16
# -> pnl_dashboard.html
```

To go live: implement `data_source._load_from_sql`, set `USE_SQL = True`. Nothing
else needs to change.

## Decisions locked in
- History: years of archive exist, accessed via **SQL** (not Excel) → backfill +
  daily incremental is feasible.
- Delivery: **emailed morning summary** is the primary product (batch pipeline,
  not always-on app).
- Compliance: **no proprietary numbers may leave the firm.** Any news/macro
  feature must query only generic public info; the daily narrative must be
  template-driven or on-prem-LLM, never an external API with our data. The
  news/narrative layer is intentionally NOT built yet.

## Open items / roadmap
- Confirm **TC sign convention** (negative = cost?) — affects flag/waterfall wording.
- Populate `STRATEGY_RISK` per account to enable the VolAdj lens.
- Add a **USD / Bps / VolAdj lens toggle** on charts.
- Build the **multi-day email-summary renderer** (HTML + PDF).
- Fold in the **MAC-vs-ETF** sleeve view.
- Optional: template-based / on-prem-LLM daily narrative; targeted public-news context.

## Conventions
- bps denominator = `|Value_USD|`.
- Colours: green `#1a7f5a` (positive), red `#c0392b` (negative), accent `#1f4e79`.
- Generated `pnl_dashboard.html`, sample data, and caches are git-ignored
  (artifacts/data, not source).
