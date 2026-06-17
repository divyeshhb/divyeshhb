"""
Builds a self-contained, OFFLINE HTML PnL dashboard from a `pnl_data` DataFrame
plus daily strategy AUM.

A toggle at the top switches every number/chart between:
  * USD  — money in USD (local-ccy cost columns converted via FxRate)
  * bps  — metric_USD / AUM(date) * 10_000

Usage:
    python dashboard.py --account 631 --start 2026-05-01 --end 2026-06-16
Output: pnl_dashboard.html  (open in any browser; Plotly embedded inline).
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.offline import get_plotlyjs

import config
import metrics
from data_source import available_date_range, fetch_aum, fetch_pnl_data

POS, NEG, INK, MUTE, ACCENT = "#1a7f5a", "#c0392b", "#1f2d3d", "#7b8794", "#1f4e79"
PLOT_BG = "#ffffff"
SCALE = config.BPS_SCALE


# --------------------------------------------------------------------------- #
# Formatting                                                                  #
# --------------------------------------------------------------------------- #
def _usd(x: float, dp: int = 0) -> str:
    if pd.isna(x):
        return "—"
    return f"${x:,.{dp}f}" if x >= 0 else f"-${abs(x):,.{dp}f}"


def _bps(x: float, dp: int = 1) -> str:
    if pd.isna(x):
        return "—"
    return f"{x:+,.{dp}f} bp"


def _cls(x: float) -> str:
    if pd.isna(x):
        return "zero"
    return "pos" if x > 0 else ("neg" if x < 0 else "zero")


def dual(usd_html: str, bps_html: str) -> str:
    """A value that shows USD or bps depending on the active toggle."""
    return f'<span class="v v-usd">{usd_html}</span><span class="v v-bps">{bps_html}</span>'


def num_cell(usd_val: float, bps_val: float, dp_usd: int = 0) -> str:
    return (f'<td class="num {_cls(usd_val)}">'
            f'{dual(_usd(usd_val, dp_usd), _bps(bps_val))}</td>')


# --------------------------------------------------------------------------- #
# Charts (each metric built once per lens, wrapped so the toggle shows one)    #
# --------------------------------------------------------------------------- #
def _fig_div(fig: go.Figure, axis_usd: str = "y") -> str:
    fig.update_layout(
        margin=dict(l=48, r=20, t=40, b=40), paper_bgcolor=PLOT_BG,
        plot_bgcolor=PLOT_BG,
        font=dict(family="Inter, Segoe UI, sans-serif", size=12, color=INK),
        title_font=dict(size=15, color=ACCENT), legend=dict(font=dict(size=11)))
    return pio.to_html(fig, full_html=False, include_plotlyjs=False,
                       config={"displayModeBar": False})


def _views(usd_div: str, bps_div: str) -> str:
    return (f'<div class="v v-usd">{usd_div}</div>'
            f'<div class="v v-bps">{bps_div}</div>')


def _line(daily, col, title, prefix, fmt):
    fig = go.Figure(go.Scatter(
        x=daily.index, y=daily[col], mode="lines",
        line=dict(color=ACCENT, width=2), fill="tozeroy",
        fillcolor="rgba(31,78,121,0.08)",
        hovertemplate="%{x|%d-%b-%Y}<br>%{y:" + fmt + "}<extra></extra>"))
    fig.update_layout(title=title, yaxis_tickprefix=prefix, yaxis_tickformat=fmt)
    return _fig_div(fig)


def chart_cumulative(daily) -> str:
    usd = _line(daily, "CumPNL_USD", "Cumulative PnL (USD)", "$", ",.0s")
    bps = _line(daily, "CumPNL_bps", "Cumulative PnL (bps of AUM)", "", ",.0f")
    return _views(usd, bps)


def _bars(daily, col, title, prefix, fmt):
    colors = [POS if v >= 0 else NEG for v in daily[col]]
    fig = go.Figure(go.Bar(
        x=daily.index, y=daily[col], marker_color=colors,
        hovertemplate="%{x|%d-%b-%Y}<br>%{y:" + fmt + "}<extra></extra>"))
    fig.update_layout(title=title, yaxis_tickprefix=prefix, yaxis_tickformat=fmt)
    return _fig_div(fig)


def chart_daily_bars(daily) -> str:
    usd = _bars(daily, "PNL_USD", "Daily PnL (USD)", "$", ",.0s")
    bps = _bars(daily, "PNL_USD_bps", "Daily PnL (bps of AUM)", "", ",.1f")
    return _views(usd, bps)


def _waterfall(wf, total, value_key, title, prefix, fmt):
    labels = wf["component"].tolist() + ["Total cost"]
    values = wf[value_key].tolist() + [total]
    measure = ["relative"] * len(wf) + ["total"]
    fig = go.Figure(go.Waterfall(
        orientation="v", measure=measure, x=labels, y=values,
        connector=dict(line=dict(color=MUTE)),
        decreasing=dict(marker=dict(color=NEG)),
        increasing=dict(marker=dict(color=POS)),
        totals=dict(marker=dict(color=ACCENT)),
        hovertemplate="%{x}<br>%{y:" + fmt + "}<extra></extra>"))
    fig.update_layout(title=title, yaxis_tickprefix=prefix, yaxis_tickformat=fmt)
    return _fig_div(fig)


def chart_cost_waterfall(wf) -> str:
    # Total = sum of the components shown, so the waterfall is always internally
    # consistent (independent of which column drives the headline TC KPI).
    usd = _waterfall(wf, wf["usd"].sum(), "usd",
                     "Cost breakdown (USD)", "$", ",.0s")
    bps = _waterfall(wf, wf["bps"].sum(), "bps",
                     "Cost breakdown (bps of AUM)", "", ",.1f")
    return _views(usd, bps)


def _ampm(daily, am, pm, title, prefix, fmt):
    fig = go.Figure()
    fig.add_trace(go.Bar(x=daily.index, y=daily[am], name="AM", marker_color="#e67e22"))
    fig.add_trace(go.Bar(x=daily.index, y=daily[pm], name="PM", marker_color="#2980b9"))
    fig.update_layout(title=title, barmode="relative",
                      yaxis_tickprefix=prefix, yaxis_tickformat=fmt)
    return _fig_div(fig)


def chart_ampm(daily) -> str:
    usd = _ampm(daily, "ModelSlippage_AM", "ModelSlippage_PM",
                "Model slippage by session (USD)", "$", ",.0s")
    bps = _ampm(daily, "ModelSlippage_AM_bps", "ModelSlippage_PM_bps",
                "Model slippage by session (bps of AUM)", "", ",.1f")
    return _views(usd, bps)


def _country(by_country, col, title, prefix, fmt):
    d = by_country.sort_values(col)
    colors = [POS if v >= 0 else NEG for v in d[col]]
    fig = go.Figure(go.Bar(
        x=d[col], y=d.index, orientation="h", marker_color=colors,
        hovertemplate="%{y}<br>%{x:" + fmt + "}<extra></extra>"))
    fig.update_layout(title=title, xaxis_tickprefix=prefix, xaxis_tickformat=fmt,
                      height=max(280, 26 * len(d)))
    return _fig_div(fig)


def chart_country(by_country) -> str:
    usd = _country(by_country, "PNL_USD", "PnL by country (USD)", "$", ",.0s")
    bps = _country(by_country, "PNL_bps", "PnL by country (bps of AUM)", "", ",.1f")
    return _views(usd, bps)


# --------------------------------------------------------------------------- #
# Tables                                                                      #
# --------------------------------------------------------------------------- #
def _table(headers, rows, classes="") -> str:
    th = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(c) + "</tr>" for c in rows)
    return f'<table class="grid {classes}"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>'


def table_winners_losers(df_day, aum) -> str:
    win, los = metrics.winners_losers(df_day, aum)

    def rows(d):
        out = []
        for _, r in d.iterrows():
            out.append([
                f'<td class="tk">{r["Ticker"]}</td>',
                f'<td>{r.get("Country","")}</td>',
                num_cell(r["PNL_disp"], r["PNL_bps"]),
                num_cell(r["TC_disp"], r["TC_bps"]),
            ])
        return out

    h = ["Ticker", "Country", "PnL", "TC"]
    return (f'<div class="half"><h3>Top winners</h3>{_table(h, rows(win))}</div>'
            f'<div class="half"><h3>Top losers</h3>{_table(h, rows(los))}</div>')


def table_exceptions(ex) -> str:
    if ex.empty:
        return '<p class="ok">No exceptions flagged for this day. ✓</p>'
    rows = [[f'<td class="tk">{r.Ticker}</td>', f'<td>{r.Country}</td>',
             f'<td><span class="badge">{r.Flag}</span></td>', f'<td>{r.Detail}</td>']
            for r in ex.itertuples()]
    return _table(["Ticker", "Country", "Flag", "Detail"], rows, "ex")


def table_country(by_country, aum) -> str:
    rows = []
    for idx, r in by_country.iterrows():
        gross_bps = abs(r["Value_USD"]) / aum * SCALE if aum else np.nan
        rows.append([
            f'<td>{idx}</td>',
            num_cell(r["PNL_USD"], r.get("PNL_bps", np.nan)),
            num_cell(r["TC_disp"], r.get("TC_bps", np.nan)),
            num_cell(abs(r["Value_USD"]), gross_bps),
        ])
    return _table(["Country", "PnL", "TC", "Gross exposure"], rows)


def table_instruments(df_day, aum) -> str:
    d = df_day.copy()
    d["PNL_disp"] = metrics._usd_col(d, "PNL_USD")
    d["TC_disp"] = metrics._usd_col(d, "TC")
    d["MS_disp"] = metrics._usd_col(d, "ModelSlippage")
    d = d.sort_values("PNL_disp", ascending=False)

    def b(x):
        return x / aum * SCALE if aum else np.nan

    rows = []
    for _, r in d.iterrows():
        rows.append([
            f'<td class="tk">{r["Ticker"]}</td>',
            f'<td>{r["Country"]}</td>',
            f'<td class="num">{int(r["CurrentUnits"]):,}</td>',
            num_cell(r["PNL_disp"], b(r["PNL_disp"])),
            num_cell(r["TC_disp"], b(r["TC_disp"])),
            num_cell(r["MS_disp"], b(r["MS_disp"])),
            num_cell(abs(r["Value_USD"]), b(abs(r["Value_USD"]))),
        ])
    h = ["Ticker", "Country", "Units", "PnL", "TC", "Model slip.", "Gross exp."]
    return _table(h, rows, "scroll")


# --------------------------------------------------------------------------- #
# Page assembly                                                               #
# --------------------------------------------------------------------------- #
def _kpi_card(label, usd_val, bps_val, sub, dp_usd=0) -> str:
    val = dual(_usd(usd_val, dp_usd), _bps(bps_val))
    return (f'<div class="kpi"><div class="kpi-label">{label}</div>'
            f'<div class="kpi-value {_cls(usd_val)}">{val}</div>'
            f'<div class="kpi-sub">{sub}</div></div>')


def build_html(df: pd.DataFrame, aum: pd.Series, start: str, end: str) -> str:
    df = metrics.enrich(df, aum)
    as_of = df["Date"].max()
    df_day = df[df["Date"] == as_of]
    aum_day = float(aum.get(as_of.normalize(), np.nan)) if len(aum) else np.nan
    aum_day = aum_day if not pd.isna(aum_day) else None

    daily = metrics.daily_totals(df)
    by_country = metrics.group_totals(df_day, "Country", aum_day)
    k = metrics.kpi_summary(df_day, aum_day)
    wf = metrics.cost_waterfall(df_day, aum_day)
    ex = metrics.exceptions(df, as_of, aum_day)

    account = df_day["Account"].iloc[0] if len(df_day) else ""
    kpis = "".join([
        _kpi_card("Net PnL (day)", k["pnl_usd"], k["pnl_bps"], "PnL"),
        _kpi_card("Transaction cost", k["tc_usd"], k["tc_bps"], "TC vs VWAP"),
        _kpi_card("Model slippage", k["ms_usd"], k["ms_bps"], "vs model price"),
        _kpi_card("Opportunity cost", k["oc_usd"], k["oc_bps"], "missed / partial fills"),
        _kpi_card("Gross exposure", k["gross_exposure"], k["gross_bps"],
                  f'{k["n_instruments"]} instruments'),
        _kpi_card("Turnover", k["turnover"], k["turnover_bps"],
                  f'{k["n_winners"]}↑ / {k["n_losers"]}↓ names'),
    ])

    period_pnl_usd = daily["PNL_USD"].sum()
    period_pnl_bps = daily["PNL_USD_bps"].sum() if "PNL_USD_bps" in daily else np.nan
    aum_txt = _usd(aum_day) if aum_day else "n/a"

    plotlyjs = '<script type="text/javascript">' + get_plotlyjs() + '</script>'

    return _PAGE.format(
        plotlyjs=plotlyjs, account=account,
        as_of=as_of.strftime("%d-%b-%Y"),
        start=pd.to_datetime(start).strftime("%d-%b-%Y"),
        end=pd.to_datetime(end).strftime("%d-%b-%Y"),
        generated=datetime.now().strftime("%d-%b-%Y %H:%M"),
        n_days=daily.shape[0], aum=aum_txt,
        period_pnl=dual(_usd(period_pnl_usd), _bps(period_pnl_bps)),
        period_pnl_cls=_cls(period_pnl_usd),
        kpis=kpis, exceptions=table_exceptions(ex),
        chart_cum=chart_cumulative(daily), chart_bars=chart_daily_bars(daily),
        chart_waterfall=chart_cost_waterfall(wf),
        chart_ampm=chart_ampm(daily), chart_country=chart_country(by_country),
        table_country=table_country(by_country, aum_day),
        winners_losers=table_winners_losers(df_day, aum_day),
        table_instruments=table_instruments(df_day, aum_day),
    )


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="Build the PnL HTML dashboard.")
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--account", type=int, default=None)
    ap.add_argument("--out", default="pnl_dashboard.html")
    args = ap.parse_args()

    lo, hi = available_date_range(args.account)
    end = args.end or hi.isoformat()
    start = args.start or (pd.to_datetime(end) - pd.Timedelta(days=90)).date().isoformat()

    df = fetch_pnl_data(start, end, args.account)
    if df.empty:
        raise SystemExit(f"No data for {start}..{end} (account={args.account}).")
    aum = fetch_aum(start, end, args.account)

    html = build_html(df, aum, start, end)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"Wrote {args.out}  ({len(df):,} rows, {df['Date'].nunique()} days, "
          f"as-of {df['Date'].max().date()}, AUM days={len(aum)})")


# --------------------------------------------------------------------------- #
# Page template                                                               #
# --------------------------------------------------------------------------- #
_PAGE = """<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>PnL Dashboard — {account}</title>
{plotlyjs}
<style>
 :root{{--ink:#1f2d3d;--mute:#7b8794;--accent:#1f4e79;--line:#e4e8ee;--bg:#f5f7fa;}}
 *{{box-sizing:border-box}}
 body{{margin:0;font-family:Inter,'Segoe UI',Roboto,sans-serif;color:var(--ink);background:var(--bg)}}
 header{{background:linear-gradient(90deg,#1f4e79,#2e74b5);color:#fff;padding:18px 28px;
   display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px}}
 header h1{{margin:0;font-size:20px;font-weight:700}}
 header .meta{{font-size:13px;opacity:.92;margin-top:4px}}
 header .meta b{{font-weight:600}}
 /* toggle */
 .toggle{{display:inline-flex;background:rgba(255,255,255,.18);border-radius:9px;padding:3px}}
 .toggle button{{border:0;background:transparent;color:#fff;font:600 13px Inter,sans-serif;
   padding:7px 18px;border-radius:7px;cursor:pointer;opacity:.8}}
 .toggle button.active{{background:#fff;color:#1f4e79;opacity:1}}
 .wrap{{max-width:1280px;margin:0 auto;padding:20px 28px 60px}}
 section{{background:#fff;border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin:18px 0;box-shadow:0 1px 2px rgba(20,40,80,.04)}}
 h2{{font-size:16px;color:var(--accent);margin:0 0 14px;border-bottom:2px solid var(--line);padding-bottom:8px}}
 h3{{font-size:14px;margin:0 0 8px}}
 .kpis{{display:grid;grid-template-columns:repeat(6,1fr);gap:12px}}
 .kpi{{border:1px solid var(--line);border-radius:9px;padding:12px 14px}}
 .kpi-label{{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--mute)}}
 .kpi-value{{font-size:20px;font-weight:700;margin:4px 0 2px}}
 .kpi-sub{{font-size:11px;color:var(--mute)}}
 .grid{{width:100%;border-collapse:collapse;font-size:12.5px}}
 .grid th{{text-align:left;color:var(--mute);font-weight:600;border-bottom:2px solid var(--line);padding:7px 9px;font-size:11px;text-transform:uppercase;letter-spacing:.03em}}
 .grid td{{padding:6px 9px;border-bottom:1px solid var(--line)}}
 .grid tr:hover td{{background:#f8fafc}}
 .grid td.num{{text-align:right;font-variant-numeric:tabular-nums}}
 .grid td.tk{{font-weight:600;color:var(--accent)}}
 .pos{{color:#1a7f5a}} .neg{{color:#c0392b}} .zero{{color:var(--mute)}}
 .row2{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
 .scroll{{display:block;max-height:520px;overflow:auto}}
 .badge{{background:#fdecea;color:#c0392b;border-radius:5px;padding:2px 8px;font-size:11px;font-weight:600}}
 .ok{{color:#1a7f5a;font-weight:600}}
 .note{{font-size:11.5px;color:var(--mute);margin-top:10px}}
 /* lens visibility: default shows USD; body.show-bps shows bps.
    Only ever hide the inactive one, so the visible element keeps its natural
    display (inline for spans, block for chart divs) — no display:revert needed. */
 body:not(.show-bps) .v-bps{{display:none}}
 body.show-bps .v-usd{{display:none}}
 @media(max-width:1000px){{.kpis{{grid-template-columns:repeat(2,1fr)}}.row2{{grid-template-columns:1fr}}}}
</style></head><body>
<header>
  <div>
    <h1>PnL Dashboard — {account}</h1>
    <div class="meta">As-of <b>{as_of}</b> &nbsp;•&nbsp; period <b>{start} → {end}</b>
     ({n_days} days, period PnL <b class="{period_pnl_cls}">{period_pnl}</b>)
     &nbsp;•&nbsp; AUM <b>{aum}</b> &nbsp;•&nbsp; generated {generated}</div>
  </div>
  <div class="toggle">
    <button id="btn-usd" class="active" onclick="setLens('usd')">USD ($)</button>
    <button id="btn-bps" onclick="setLens('bps')">bps of AUM</button>
  </div>
</header>
<div class="wrap">
  <section><h2>Headline — {as_of}</h2><div class="kpis">{kpis}</div></section>
  <section><h2>⚠ What needs attention today</h2>{exceptions}
    <p class="note">Flags: PnL beyond its trailing z-score band, materially expensive
    execution, or opportunity cost. Costs are FX-converted to USD; bps = USD / AUM × 10,000.</p></section>
  <section><h2>Performance over the period</h2>
    <div class="row2"><div>{chart_cum}</div><div>{chart_bars}</div></div></section>
  <section><h2>Cost & execution quality — {as_of}</h2>
    <div class="row2"><div>{chart_waterfall}</div><div>{chart_ampm}</div></div>
    <p class="note">Transaction cost is shown vs the VWAP benchmark (TC_Trade_VWAP).
    The breakdown stacks trade cost (VWAP), commission, model slippage and opportunity cost.
    AM/PM split addresses “did we trade at the right time?”.</p></section>
  <section><h2>Geographic breakdown — {as_of}</h2>
    <div class="row2"><div>{chart_country}</div><div>{table_country}</div></div></section>
  <section><h2>Top movers — {as_of}</h2><div class="row2">{winners_losers}</div></section>
  <section><h2>All instruments — {as_of}</h2>{table_instruments}</section>
</div>
<script>
 function setLens(lens){{
   document.body.classList.toggle('show-bps', lens==='bps');
   document.getElementById('btn-usd').classList.toggle('active', lens==='usd');
   document.getElementById('btn-bps').classList.toggle('active', lens==='bps');
   // Plotly charts that were hidden render at 0 width; resize the now-visible ones.
   var vis = document.querySelectorAll((lens==='bps'?'.v-bps':'.v-usd')+' .plotly-graph-div');
   vis.forEach(function(d){{ try{{ Plotly.Plots.resize(d); }}catch(e){{}} }});
 }}
</script>
</body></html>"""


if __name__ == "__main__":
    main()
