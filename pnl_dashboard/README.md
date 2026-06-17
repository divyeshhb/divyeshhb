# PnL Dashboard

Generates a self-contained **HTML** dashboard from the daily futures `pnl_data`
feed. Python builds the page; the output is a single `.html` file you can open
in any browser or attach to the morning summary email.

## Quick start

```bash
pip install -r requirements.txt
python dashboard.py --account 631                 # last 90 days of available data
python dashboard.py --account 631 --start 2026-05-01 --end 2026-06-16
open pnl_dashboard.html
```

Out of the box it reads the bundled sample workbook (`data/sample_pnl_data.xlsx`)
so it runs with no database.

## Plugging in your SQL  ← the only thing you need to do

Everything funnels through one function:

```python
# data_source.py
fetch_pnl_data(start_date, end_date, account_id) -> pd.DataFrame
```

1. Open `data_source.py`.
2. Fill in `_load_from_sql(...)` with your query (a skeleton using SQLAlchemy is
   already there). It must return a DataFrame with the `pnl_data` columns —
   exactly the schema of the Excel you provided (see `config.REQUIRED_COLUMNS`).
3. Set `USE_SQL = True`.

Nothing else changes — metrics and rendering read whatever that function returns.

## What's on the dashboard

- **Headline KPIs** for the as-of trade date: net PnL (USD + bps), transaction
  cost, model slippage, opportunity cost, gross exposure, turnover.
- **What needs attention** — automatic exception panel (PnL z-score vs each
  instrument's own trailing history, materially expensive execution, opportunity
  cost), ranked by dollar impact.
- **Performance over the period** — cumulative PnL curve + daily PnL bars.
- **Cost & execution quality** — transaction-cost waterfall (trade / commission /
  model slippage / opportunity cost → reported TC) and AM-vs-PM model slippage.
- **Geographic breakdown** — PnL by country (futures grouped via currency) + table.
- **Top movers** — winners / losers tables.
- **All instruments** — full sortable detail table.

## Files

| file | role |
|------|------|
| `data_source.py` | **SQL plug-in point** + sample fallback |
| `config.py` | column contract, currency→country map, risk/vol-adj factors, thresholds |
| `metrics.py` | enrichment, aggregations, exception detection (pure pandas) |
| `dashboard.py` | chart + table builders, HTML assembly, CLI |

## Configurable in `config.py`

- `CURRENCY_GEO` — currency → (country, region, developed/emerging).
- `STRATEGY_RISK` / `TARGET_RISK` — vol-adjustment for cross-strategy comparison.
- Thresholds: `PNL_ZSCORE_FLAG`, `TC_BPS_FLAG`, materiality floors, `TOP_N`.
- `ACCOUNT_NAMES`, `ASSET_CLASS_NAMES`.

## Notes / open items

- `PNL_bps` / `TC_bps` use `|Value_USD|` as the notional denominator.
- The **vol-adjusted** lens needs each strategy's risk level in `STRATEGY_RISK`
  (factor = `TARGET_RISK / strategy_risk`); defaults to 1.0 until populated.
- TC **sign convention** is assumed as-fed; confirm whether negative = cost so the
  waterfall/flag wording is exactly right.
- News/macro context is intentionally **not** built in here — per compliance, no
  PnL leaves the firm; that layer should query only generic public info.
