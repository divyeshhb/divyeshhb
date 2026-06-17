"""
Builds a self-contained HTML PnL dashboard from a `pnl_data` DataFrame.

Usage (CLI):
    python dashboard.py --start 2026-05-01 --end 2026-06-16 --account 631
    python dashboard.py                         # defaults to last 90d of data

Output: pnl_dashboard.html (open in any browser; Plotly loaded from CDN).
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.offline import get_plotlyjs

import config
import metrics
from data_source import available_date_range, fetch_pnl_data

POS, NEG, INK, MUTE = "#1a7f5a", "#c0392b", "#1f2d3d", "#7b8794"
ACCENT = "#1f4e79"
PLOT_BG = "#ffffff"


# --------------------------------------------------------------------------- #
# Formatting helpers                                                          #
# --------------------------------------------------------------------------- #
def _usd(x: float, dp: int = 0) -> str:
    return f"${x:,.{dp}f}" if x >= 0 else f"-${abs(x):,.{dp}f}"


def _signed(x: float, dp: int = 0, suffix: str = "") -> str:
    return f"{x:+,.{dp}f}{suffix}"


def _cls(x: float) -> str:
    return "pos" if x > 0 else ("neg" if x < 0 else "zero")


def _fig_div(fig: go.Figure) -> str:
    fig.update_layout(
        margin=dict(l=40, r=20, t=40, b=40), paper_bgcolor=PLOT_BG,
        plot_bgcolor=PLOT_BG, font=dict(family="Inter, Segoe UI, sans-serif",
                                        size=12, color=INK),
        title_font=dict(size=15, color=ACCENT), legend=dict(font=dict(size=11)),
    )
    return pio.to_html(fig, full_html=False, include_plotlyjs=False,
                       config={"displayModeBar": False})


# --------------------------------------------------------------------------- #
# Chart builders                                                              #
# --------------------------------------------------------------------------- #
def chart_cumulative(daily: pd.DataFrame) -> str:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=daily.index, y=daily["CumPNL_USD"], mode="lines",
        line=dict(color=ACCENT, width=2), fill="tozeroy",
        fillcolor="rgba(31,78,121,0.08)", name="Cumulative PnL",
        hovertemplate="%{x|%d-%b-%Y}<br>Cum PnL: $%{y:,.0f}<extra></extra>"))
    fig.update_layout(title="Cumulative PnL (USD)",
                      yaxis_tickprefix="$", yaxis_tickformat=",.0s")
    return _fig_div(fig)


def chart_daily_bars(daily: pd.DataFrame) -> str:
    colors = [POS if v >= 0 else NEG for v in daily["PNL_USD"]]
    fig = go.Figure(go.Bar(
        x=daily.index, y=daily["PNL_USD"], marker_color=colors,
        hovertemplate="%{x|%d-%b-%Y}<br>PnL: $%{y:,.0f}<extra></extra>"))
    fig.update_layout(title="Daily PnL (USD)", yaxis_tickprefix="$",
                      yaxis_tickformat=",.0s")
    return _fig_div(fig)


def chart_cost_waterfall(wf: pd.DataFrame, total_tc: float) -> str:
    labels = wf["component"].tolist() + ["Reported TC"]
    values = wf["value"].tolist() + [total_tc]
    measure = ["relative"] * len(wf) + ["total"]
    fig = go.Figure(go.Waterfall(
        orientation="v", measure=measure, x=labels, y=values,
        connector=dict(line=dict(color=MUTE)),
        decreasing=dict(marker=dict(color=NEG)),
        increasing=dict(marker=dict(color=POS)),
        totals=dict(marker=dict(color=ACCENT)),
        hovertemplate="%{x}<br>$%{y:,.0f}<extra></extra>"))
    fig.update_layout(title="Transaction-cost breakdown (USD)",
                      yaxis_tickprefix="$", yaxis_tickformat=",.0s")
    return _fig_div(fig)


def chart_ampm(daily: pd.DataFrame) -> str:
    fig = go.Figure()
    fig.add_trace(go.Bar(x=daily.index, y=daily["ModelSlippage_AM"],
                         name="AM", marker_color="#e67e22"))
    fig.add_trace(go.Bar(x=daily.index, y=daily["ModelSlippage_PM"],
                         name="PM", marker_color="#2980b9"))
    fig.update_layout(title="Model slippage by session (AM vs PM, USD)",
                      barmode="relative", yaxis_tickprefix="$",
                      yaxis_tickformat=",.0s")
    return _fig_div(fig)


def chart_country(by_country: pd.DataFrame) -> str:
    d = by_country.sort_values("PNL_USD")
    colors = [POS if v >= 0 else NEG for v in d["PNL_USD"]]
    fig = go.Figure(go.Bar(
        x=d["PNL_USD"], y=d.index, orientation="h", marker_color=colors,
        hovertemplate="%{y}<br>PnL: $%{x:,.0f}<extra></extra>"))
    fig.update_layout(title="PnL contribution by country (USD)",
                      xaxis_tickprefix="$", xaxis_tickformat=",.0s",
                      height=max(280, 26 * len(d)))
    return _fig_div(fig)


# --------------------------------------------------------------------------- #
# Table builders                                                              #
# --------------------------------------------------------------------------- #
def _table(headers, rows, classes="") -> str:
    th = "".join(f"<th>{h}</th>" for h in headers)
    body = "".join("<tr>" + "".join(cells) + "</tr>" for cells in rows)
    return f'<table class="grid {classes}"><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>'


def table_winners_losers(df_day: pd.DataFrame) -> str:
    win, los = metrics.winners_losers(df_day)

    def rows(d):
        out = []
        for _, r in d.iterrows():
            out.append([
                f'<td class="tk">{r["Ticker"]}</td>',
                f'<td>{r.get("Country","")}</td>',
                f'<td class="num {_cls(r["PNL_USD"])}">{_usd(r["PNL_USD"])}</td>',
                f'<td class="num {_cls(r["PNL_bps"])}">{_signed(r["PNL_bps"],1," bp")}</td>',
                f'<td class="num {_cls(r["TC"])}">{_usd(r["TC"])}</td>',
            ])
        return out

    h = ["Ticker", "Country", "PnL", "PnL (bps)", "TC"]
    return (f'<div class="half"><h3>Top winners</h3>{_table(h, rows(win))}</div>'
            f'<div class="half"><h3>Top losers</h3>{_table(h, rows(los))}</div>')


def table_exceptions(ex: pd.DataFrame) -> str:
    if ex.empty:
        return '<p class="ok">No exceptions flagged for this day. ✓</p>'
    rows = [[f'<td class="tk">{r.Ticker}</td>', f'<td>{r.Country}</td>',
             f'<td><span class="badge">{r.Flag}</span></td>', f'<td>{r.Detail}</td>']
            for r in ex.itertuples()]
    return _table(["Ticker", "Country", "Flag", "Detail"], rows, "ex")


def table_region(by_region: pd.DataFrame) -> str:
    rows = []
    for idx, r in by_region.iterrows():
        rows.append([
            f'<td>{idx}</td>',
            f'<td class="num {_cls(r["PNL_USD"])}">{_usd(r["PNL_USD"])}</td>',
            f'<td class="num {_cls(r["PNL_bps"])}">{_signed(r["PNL_bps"],1," bp")}</td>',
            f'<td class="num {_cls(r["TC"])}">{_usd(r["TC"])}</td>',
            f'<td class="num">{_usd(abs(r["Value_USD"]))}</td>',
        ])
    return _table(["Country", "PnL", "PnL (bps)", "TC", "Gross exposure"], rows)


def table_instruments(df_day: pd.DataFrame) -> str:
    cols = ["Ticker", "Country", "CurrentUnits", "PNL_USD", "PNL_bps",
            "TC", "ModelSlippage", "Value_USD", "Dollar_Traded"]
    d = df_day.sort_values("PNL_USD", ascending=False)
    rows = []
    for _, r in d.iterrows():
        rows.append([
            f'<td class="tk">{r["Ticker"]}</td>',
            f'<td>{r["Country"]}</td>',
            f'<td class="num">{int(r["CurrentUnits"]):,}</td>',
            f'<td class="num {_cls(r["PNL_USD"])}">{_usd(r["PNL_USD"])}</td>',
            f'<td class="num {_cls(r["PNL_bps"])}">{_signed(r["PNL_bps"],1)}</td>',
            f'<td class="num {_cls(r["TC"])}">{_usd(r["TC"])}</td>',
            f'<td class="num {_cls(r["ModelSlippage"])}">{_usd(r["ModelSlippage"])}</td>',
            f'<td class="num">{_usd(abs(r["Value_USD"]))}</td>',
            f'<td class="num">{_usd(abs(r["Dollar_Traded"]))}</td>',
        ])
    h = ["Ticker", "Country", "Units", "PnL", "PnL bps", "TC",
         "Model slip.", "Gross exp.", "$ Traded"]
    return _table(h, rows, "scroll")


# --------------------------------------------------------------------------- #
# Page assembly                                                               #
# --------------------------------------------------------------------------- #
def _kpi_card(label, value, sub="", cls="") -> str:
    return (f'<div class="kpi"><div class="kpi-label">{label}</div>'
            f'<div class="kpi-value {cls}">{value}</div>'
            f'<div class="kpi-sub">{sub}</div></div>')


def build_html(df: pd.DataFrame, start: str, end: str) -> str:
    df = metrics.enrich(df)
    as_of = df["Date"].max()
    df_day = df[df["Date"] == as_of]

    daily = metrics.daily_totals(df)
    by_country = metrics.group_totals(df_day, "Country")
    by_region = metrics.group_totals(df_day, "Country")  # country-level table
    k = metrics.kpi_summary(df_day)
    wf = metrics.cost_waterfall(df_day)
    ex = metrics.exceptions(df, as_of)

    account = df_day["Account"].iloc[0] if len(df_day) else ""
    kpis = "".join([
        _kpi_card("Net PnL (day)", _usd(k["pnl_usd"]),
                  _signed(k["pnl_bps"], 1, " bps"), _cls(k["pnl_usd"])),
        _kpi_card("Transaction cost", _usd(k["tc"]), "TC (all components)", _cls(k["tc"])),
        _kpi_card("Model slippage", _usd(k["model_slippage"]), "vs model price", _cls(k["model_slippage"])),
        _kpi_card("Opportunity cost", _usd(k["oc"]), "missed / partial fills", _cls(k["oc"])),
        _kpi_card("Gross exposure", _usd(k["gross_exposure"]), f'{k["n_instruments"]} instruments'),
        _kpi_card("Turnover", _usd(k["turnover"]), f'{k["n_winners"]}↑ / {k["n_losers"]}↓ names'),
    ])

    generated = datetime.now().strftime("%d-%b-%Y %H:%M")
    period_pnl = daily["PNL_USD"].sum()

    # Embed Plotly.js inline (from your installed plotly) so the HTML renders
    # with no internet / no CDN — important on locked-down machines.
    plotlyjs = '<script type="text/javascript">' + get_plotlyjs() + '</script>'

    return _PAGE.format(
        plotlyjs=plotlyjs,
        account=account, as_of=as_of.strftime("%d-%b-%Y"),
        start=pd.to_datetime(start).strftime("%d-%b-%Y"),
        end=pd.to_datetime(end).strftime("%d-%b-%Y"),
        generated=generated, n_days=daily.shape[0],
        period_pnl=_usd(period_pnl), period_pnl_cls=_cls(period_pnl),
        kpis=kpis,
        exceptions=table_exceptions(ex),
        chart_cum=chart_cumulative(daily),
        chart_bars=chart_daily_bars(daily),
        chart_waterfall=chart_cost_waterfall(wf, k["tc"]),
        chart_ampm=chart_ampm(daily),
        chart_country=chart_country(by_country),
        table_region=table_region(by_region),
        winners_losers=table_winners_losers(df_day),
        table_instruments=table_instruments(df_day),
    )


# --------------------------------------------------------------------------- #
# CLI                                                                         #
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description="Build the PnL HTML dashboard.")
    ap.add_argument("--start", help="YYYY-MM-DD")
    ap.add_argument("--end", help="YYYY-MM-DD")
    ap.add_argument("--account", type=int, default=None)
    ap.add_argument("--out", default="pnl_dashboard.html")
    args = ap.parse_args()

    lo, hi = available_date_range(args.account)
    end = args.end or hi.isoformat()
    start = args.start or (pd.to_datetime(end) - pd.Timedelta(days=90)).date().isoformat()

    df = fetch_pnl_data(start, end, args.account)
    if df.empty:
        raise SystemExit(f"No data for {start}..{end} (account={args.account}).")

    html = build_html(df, start, end)
    Path(args.out).write_text(html, encoding="utf-8")
    print(f"Wrote {args.out}  ({len(df):,} rows, {df['Date'].nunique()} days, "
          f"as-of {df['Date'].max().date()})")


# --------------------------------------------------------------------------- #
# Page template (kept at the bottom for readability)                          #
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
 header{{background:linear-gradient(90deg,#1f4e79,#2e74b5);color:#fff;padding:18px 28px}}
 header h1{{margin:0;font-size:20px;font-weight:700}}
 header .meta{{font-size:13px;opacity:.9;margin-top:4px}}
 header .meta b{{font-weight:600}}
 .wrap{{max-width:1280px;margin:0 auto;padding:20px 28px 60px}}
 section{{background:#fff;border:1px solid var(--line);border-radius:10px;padding:18px 20px;margin:18px 0;box-shadow:0 1px 2px rgba(20,40,80,.04)}}
 h2{{font-size:16px;color:var(--accent);margin:0 0 14px;border-bottom:2px solid var(--line);padding-bottom:8px}}
 h3{{font-size:14px;color:var(--ink);margin:0 0 8px}}
 .kpis{{display:grid;grid-template-columns:repeat(6,1fr);gap:12px}}
 .kpi{{background:#fff;border:1px solid var(--line);border-radius:9px;padding:12px 14px}}
 .kpi-label{{font-size:11px;text-transform:uppercase;letter-spacing:.04em;color:var(--mute)}}
 .kpi-value{{font-size:21px;font-weight:700;margin:4px 0 2px}}
 .kpi-sub{{font-size:11px;color:var(--mute)}}
 .grid{{width:100%;border-collapse:collapse;font-size:12.5px}}
 .grid th{{text-align:left;color:var(--mute);font-weight:600;border-bottom:2px solid var(--line);padding:7px 9px;font-size:11px;text-transform:uppercase;letter-spacing:.03em}}
 .grid td{{padding:6px 9px;border-bottom:1px solid var(--line)}}
 .grid tr:hover td{{background:#f8fafc}}
 .grid td.num{{text-align:right;font-variant-numeric:tabular-nums}}
 .grid td.tk{{font-weight:600;color:var(--accent)}}
 .pos{{color:#1a7f5a}} .neg{{color:#c0392b}} .zero{{color:var(--mute)}}
 .row2{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}
 .half h3{{margin-top:0}}
 .scroll{{display:block;max-height:520px;overflow:auto}}
 .badge{{background:#fdecea;color:#c0392b;border-radius:5px;padding:2px 8px;font-size:11px;font-weight:600}}
 .ok{{color:#1a7f5a;font-weight:600}}
 .note{{font-size:11.5px;color:var(--mute);margin-top:10px}}
 @media(max-width:1000px){{.kpis{{grid-template-columns:repeat(2,1fr)}}.row2{{grid-template-columns:1fr}}}}
</style></head><body>
<header>
  <h1>PnL Dashboard — {account}</h1>
  <div class="meta">As-of trade date <b>{as_of}</b> &nbsp;•&nbsp; period <b>{start} → {end}</b>
   ({n_days} trading days, period PnL <b class="{period_pnl_cls}">{period_pnl}</b>)
   &nbsp;•&nbsp; generated {generated}</div>
</header>
<div class="wrap">

  <section><h2>Headline — {as_of}</h2><div class="kpis">{kpis}</div></section>

  <section><h2>⚠ What needs attention today</h2>{exceptions}
    <p class="note">Flags: PnL beyond its trailing z-score band, execution cost above threshold,
    or opportunity cost present. Thresholds configurable in config.py.</p></section>

  <section><h2>Performance over the period</h2>
    <div class="row2"><div>{chart_cum}</div><div>{chart_bars}</div></div></section>

  <section><h2>Cost & execution quality — {as_of}</h2>
    <div class="row2"><div>{chart_waterfall}</div><div>{chart_ampm}</div></div>
    <p class="note">Components (trade cost, commission, model slippage, opportunity cost)
    approximately reconcile to reported TC. AM/PM split helps answer “did we trade at the right time?”.</p></section>

  <section><h2>Geographic breakdown — {as_of}</h2>
    <div class="row2"><div>{chart_country}</div><div>{table_region}</div></div></section>

  <section><h2>Top movers — {as_of}</h2><div class="row2">{winners_losers}</div></section>

  <section><h2>All instruments — {as_of}</h2>{table_instruments}</section>

</div></body></html>"""


if __name__ == "__main__":
    main()
