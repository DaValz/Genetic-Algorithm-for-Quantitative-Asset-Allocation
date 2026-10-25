"""Costruttori dei grafici Plotly (funzioni pure: dati in ingresso, figura in uscita)."""
from __future__ import annotations

from typing import Sequence

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from goalga.i18n import t
from goalga.market import Market
from goalga.plan import group_goals
from goalga.problem import Flows

from . import classes
from . import format as fmt
from .theme import ACCENT, ACCENT_SOFT, BAD, GOOD, GRID, MUTED, WARN, asset_color, hex_rgba, risk_color, style


def _hex_rgba(color: str, alpha: float) -> str:
    return hex_rgba(color, alpha)


def strategy_label(key: str) -> str:
    """Nome della strategia di confronto (``ga``, ``linear``, ``constK``) nella lingua attiva."""
    if key == "ga":
        return t("chart.s.ga")
    if key == "linear":
        return t("chart.s.linear")
    return t("chart.s.const", k=key.removeprefix("const"))


def _mark_goals(fig: go.Figure, marks: Sequence[tuple[int, float]], label_y: float | None = None,
                yref: str = "paper") -> None:
    for start, end, amount in group_goals(marks):
        fig.add_vrect(x0=start - 0.5, x1=end + 0.5, fillcolor="rgba(255,255,255,0.06)", line_width=0, layer="below")
        label = fmt.eur_compact(amount) + (t("unit.per_year") if end > start else "")
        fig.add_annotation(x=(start + end) / 2, y=1.0 if label_y is None else label_y, yref=yref, yanchor="bottom",
                           text=label, showarrow=False, font=dict(size=10, color=MUTED))


def glide_path_figure(path: np.ndarray, goal_marks: Sequence[tuple[int, float]] = (),
                      band: tuple[np.ndarray, np.ndarray] | None = None, n_portfolios: int = 9) -> go.Figure:
    path = np.asarray(path)
    years = np.arange(1, len(path) + 1)
    fig = go.Figure()
    if band is not None:
        lower, upper = band
        fig.add_trace(go.Scatter(x=years, y=upper, mode="lines", line=dict(width=0, shape="hv"),
                                 showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(x=years, y=lower, mode="lines", line=dict(width=0, shape="hv"), fill="tonexty",
                                 fillcolor=ACCENT_SOFT, name=t("chart.rob_band"), hoverinfo="skip"))
    fig.add_trace(go.Scatter(
        x=years, y=path, mode="lines", name=t("chart.glide"), line=dict(color=ACCENT, width=3.5, shape="hv"),
        hovertemplate=t("chart.pf_hover") + "<extra></extra>"))
    _mark_goals(fig, goal_marks)
    fig.update_yaxes(range=[0.4, n_portfolios + 0.6], tickmode="array", tickvals=list(range(1, n_portfolios + 1)),
                     ticktext=[f"P{i}" for i in range(1, n_portfolios + 1)], title=t("chart.risk_level"))
    fig.update_xaxes(title=t("chart.year"), range=[0.5, len(path) + 0.5], dtick=max(1, len(path) // 10))
    return style(fig, 330, legend=band is not None, legend_y=1.1 if goal_marks else 1.02)


def composition_figure(composition: pd.DataFrame, min_weight: float = 0.01,
                       names: dict[str, str] | None = None) -> go.Figure:
    comp = composition.copy()
    order = comp.mean().sort_values(ascending=False).index
    comp = comp[order]
    minor = [c for c in comp if comp[c].max() < min_weight]
    if minor:
        comp = comp.drop(columns=minor)
        comp[t("chart.other")] = composition[minor].sum(axis=1)
    fig = go.Figure()
    for i, col in enumerate(comp.columns):
        color = "#94A3B8" if col == t("chart.other") else asset_color(i)
        fig.add_trace(go.Scatter(
            x=comp.index, y=comp[col], mode="lines", name=str((names or {}).get(col, col)), stackgroup="w",
            line=dict(width=0.6, color=color, shape="hv"),
            fillcolor=_hex_rgba(color, 0.88), hovertemplate="%{y:.1%}<extra>%{fullData.name}</extra>"))
    fig.update_yaxes(range=[0, 1], tickformat=".0%", title=t("chart.weight"))
    fig.update_xaxes(title=t("chart.year"), dtick=max(1, len(comp) // 10), range=[1, len(comp)])
    return style(fig, 330)


def fan_figure(fan: pd.DataFrame, goal_marks: Sequence[tuple[int, float]] = ()) -> go.Figure:
    x = fan.index
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=fan["P95"], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=fan["P5"], mode="lines", line=dict(width=0), fill="tonexty",
                             fillcolor=_hex_rgba(ACCENT, 0.10), name=t("chart.band_5_95"), hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=fan["P75"], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=fan["P25"], mode="lines", line=dict(width=0), fill="tonexty",
                             fillcolor=_hex_rgba(ACCENT, 0.22), name=t("chart.band_25_75"), hoverinfo="skip"))
    for col, name in (("P95", t("chart.p95")), ("P50", t("chart.median")), ("P5", t("chart.p5"))):
        fig.add_trace(go.Scatter(
            x=x, y=fan[col], mode="lines", name=name, showlegend=col == "P50",
            line=dict(color=ACCENT, width=2.6 if col == "P50" else 1, dash="solid" if col == "P50" else "dot"),
            hovertemplate="€ %{y:,.0f}<extra>" + name + "</extra>"))
    fig.add_trace(go.Scatter(x=x, y=fan["Atteso"], mode="lines", name=t("chart.expected"),
                             line=dict(color=MUTED, width=1.6, dash="dash"),
                             hovertemplate="€ %{y:,.0f}<extra>" + t("chart.expected_hover") + "</extra>"))
    fig.add_hline(y=0, line=dict(color=BAD, width=1, dash="dot"))
    _mark_goals(fig, goal_marks)
    fig.update_yaxes(tickprefix="€ ", tickformat="~s", title=t("chart.wealth_after"))
    fig.update_xaxes(title=t("chart.year"), dtick=max(1, (len(x) - 1) // 10))
    return style(fig, 400, legend_y=1.1 if goal_marks else 1.02)


def goals_figure(goals: pd.DataFrame, pr_target: float) -> go.Figure:
    colors = [GOOD if p >= pr_target - 1e-9 else (WARN if p >= pr_target - 0.05 else BAD)
              for p in goals["Probabilità cumulata di successo"]]
    fig = go.Figure(go.Bar(
        x=[t("chart.year_n", n=y) for y in goals["Anno"]], y=goals["Probabilità cumulata di successo"],
        marker_color=colors, text=[fmt.pct(p, 1) for p in goals["Probabilità cumulata di successo"]],
        textposition="outside", textfont=dict(size=10), cliponaxis=False,
        customdata=np.column_stack([goals["Obiettivo"], goals["Copertura mediana"]]),
        hovertemplate=t("chart.goal_hover") + "<extra></extra>"))
    fig.add_hline(y=pr_target, line=dict(color=MUTED, width=1.2, dash="dash"))
    fig.update_yaxes(range=[0, 1.12], tickformat=".0%", title=t("chart.cum_prob", target=fmt.pct(pr_target, 0)))
    fig.update_xaxes(tickangle=-40)
    fig.update_layout(bargap=0.35)
    return style(fig, 320, legend=False, hovermode="closest")


def terminal_figure(terminal: np.ndarray, alpha: float) -> go.Figure:
    cutoff = float(np.quantile(terminal, alpha))
    hi = float(np.percentile(terminal, 99))
    lo = float(terminal.min())
    counts, edges = np.histogram(terminal[terminal <= hi], bins=60, range=(lo, hi))
    centers = 0.5 * (edges[:-1] + edges[1:])
    share = counts / terminal.size
    colors = [BAD if c <= cutoff else ACCENT for c in centers]
    fig = go.Figure(go.Bar(x=centers, y=share, marker_color=colors, width=np.diff(edges) * 0.95,
                           hovertemplate="€ %{x:,.0f}<br>" + t("chart.share_hover") + "<extra></extra>"))
    fig.add_vline(x=0, line=dict(color=MUTED, width=1.2, dash="dot"))
    fig.add_annotation(x=cutoff, y=1, yref="paper", yanchor="bottom", showarrow=False,
                       text=t("chart.worst_alpha", alpha=fmt.pct_short(alpha)), font=dict(size=11, color=BAD))
    fig.update_xaxes(title=t("chart.final_wealth"), tickprefix="€ ", tickformat="~s")
    fig.update_yaxes(tickformat=".0%", title=t("chart.scenario_share"))
    return style(fig, 300, legend=False, hovermode="closest")


def benchmark_figure(bench: pd.DataFrame, pr_target: float) -> go.Figure:
    """Barre orizzontali dell'IRR di coda; tratteggiate le strategie sotto la soglia di probabilità."""
    df = bench.sort_values("IRR atteso (coda)").reset_index(drop=True)
    is_ga = df["Chiave"] == "ga"
    feasible = df["Soglia rispettata"].to_numpy()
    colors = [ACCENT if ga else ("#64748B" if ok else "#334155") for ga, ok in zip(is_ga, feasible)]
    labels = [strategy_label(k) for k in df["Chiave"]]
    fig = go.Figure(go.Bar(
        y=labels, x=df["IRR atteso (coda)"], orientation="h", marker_color=colors,
        marker_pattern_shape=["" if ok else "/" for ok in feasible],
        text=[f"{fmt.pct(i, 2)} · Pr {fmt.pct(p, 1)}" for i, p in zip(df["IRR atteso (coda)"], df["Probabilità di successo"])],
        textposition="outside", textfont=dict(size=11), cliponaxis=False,
        hovertemplate="%{y}<br>" + t("chart.tail_irr_hover") + "<extra></extra>"))
    fig.update_xaxes(tickformat=".0%", title=t("chart.tail_irr"), range=[min(0, df["IRR atteso (coda)"].min()) * 1.1,
                                                                        df["IRR atteso (coda)"].max() * 1.45])
    fig.update_yaxes(title=None, gridcolor="rgba(0,0,0,0)")
    return style(fig, 420, legend=False, hovermode="closest")


def convergence_figure(history: dict[str, np.ndarray], best_generation: int) -> go.Figure:
    gens = np.arange(1, len(history["best_score"]) + 1)
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(go.Scatter(x=gens, y=history["best_pr"], name=t("chart.success_prob"), mode="lines",
                             line=dict(color=ACCENT, width=2.4, shape="hv"),
                             hovertemplate="%{y:.1%}<extra>" + t("chart.success_prob") + "</extra>"), secondary_y=False)
    fig.add_trace(go.Scatter(x=gens, y=history["best_irr_es"], name=t("chart.tail_irr_short"), mode="lines",
                             line=dict(color="#2563EB", width=2, dash="dot", shape="hv"),
                             hovertemplate="%{y:.2%}<extra>" + t("chart.tail_irr_short") + "</extra>"), secondary_y=True)
    fig.add_vline(x=best_generation + 1, line=dict(color=MUTED, width=1, dash="dot"))
    fig.update_yaxes(tickformat=".1%", title=t("chart.probability"), secondary_y=False)
    fig.update_yaxes(tickformat=".2%", title=t("chart.irr_tail_axis"), secondary_y=True, showgrid=False)
    fig.update_xaxes(title=t("chart.generation_log"), type="log")
    return style(fig, 280)


def frontier_figure(market: Market) -> go.Figure:
    ret, vol = market.stats
    fig = go.Figure()
    asset_vol = np.sqrt(np.diag(market.cov))
    hover = t("chart.frontier_hover")
    fig.add_trace(go.Scatter(
        x=asset_vol, y=market.mu, mode="markers", name=t("chart.single_assets"), text=market.names,
        marker=dict(size=8, color="#94A3B8", line=dict(color="white", width=1)),
        hovertemplate="%{text}<br>" + hover + "<extra></extra>"))
    fig.add_trace(go.Scatter(x=vol, y=ret, mode="lines", line=dict(color=_hex_rgba(ACCENT, 0.5), width=2),
                             showlegend=False, hoverinfo="skip"))
    n = market.n_portfolios
    fig.add_trace(go.Scatter(
        x=vol, y=ret, mode="markers+text", name=t("chart.portfolios_range", n=n), text=[f"P{i}" for i in range(1, n + 1)],
        textposition="top left", textfont=dict(size=11),
        marker=dict(size=13, color=[risk_color(i, n) for i in range(1, n + 1)], line=dict(color="white", width=1.5)),
        hovertemplate="%{text}<br>" + hover + "<extra></extra>"))
    fig.update_xaxes(title=t("chart.annual_vol"), tickformat=".0%", showgrid=True, gridcolor=GRID)
    fig.update_yaxes(title=t("chart.annual_ret"), tickformat=".0%")
    # i titoli singoli, molto più volatili, non devono schiacciare i 9 portafogli: l'asse segue questi ultimi
    x_max = float(vol.max()) * 2.2
    inside = market.mu[asset_vol <= x_max]
    lo = min(float(ret.min()), float(inside.min()) if inside.size else float(ret.min()))
    hi = max(float(ret.max()), float(inside.max()) if inside.size else float(ret.max()))
    pad = max(0.005, (hi - lo) * 0.08)
    fig.update_xaxes(range=[0, x_max])
    fig.update_yaxes(range=[lo - pad, hi + pad])
    return style(fig, 340, hovermode="closest")


def weights_figure(market: Market, min_weight: float = 0.01) -> go.Figure:
    w = market.weights_frame()
    order = w.mean(axis=1).sort_values(ascending=False).index
    fig = go.Figure()
    for i, name in enumerate(order):
        row = w.loc[name]
        if row.max() < min_weight:
            continue
        fig.add_trace(go.Bar(x=list(w.columns), y=row.values, name=str(name), marker_color=asset_color(i),
                             hovertemplate="%{y:.1%}<extra>%{fullData.name}</extra>"))
    fig.update_layout(barmode="stack", bargap=0.25)
    fig.update_yaxes(tickformat=".0%", range=[0, 1], title=t("chart.composition"))
    return style(fig, 340)


CATEGORY_COLORS = {
    "cash": "#94A3B8", "govt_bond": "#7DD3FC", "corp_bond": "#38BDF8", "hy_bond": "#6366F1", "em_bond": "#2DD4BF",
    "dev_equity": "#A78BFA", "em_equity": "#F472B6", "commodities": "#FBBF24", "real_estate_fund": "#FB7185",
    "stocks": "#34D399", "other": "#64748B",
}


def categories_figure(market: Market) -> go.Figure:
    """Composizione dei 9 portafogli per categoria: classi di fondi e, insieme, le azioni singole."""
    from goalga.universe import FUND_CATEGORIES

    w = market.weights_frame()
    groups: dict[str, np.ndarray] = {}
    for name in w.index:
        key = classes.category_key(str(name))
        groups[key] = groups.get(key, 0.0) + w.loc[name].to_numpy()
    fig = go.Figure()
    for key in (*FUND_CATEGORIES, "stocks", "other"):
        if key in groups and groups[key].max() >= 0.002:
            fig.add_trace(go.Bar(x=list(w.columns), y=groups[key], name=t(f"cat.{key}"),
                                 marker_color=CATEGORY_COLORS.get(key, MUTED),
                                 hovertemplate="%{y:.1%}<extra>%{fullData.name}</extra>"))
    fig.update_layout(barmode="stack", bargap=0.25)
    fig.update_yaxes(tickformat=".0%", range=[0, 1], title=t("chart.composition"))
    style(fig, 400)
    fig.update_layout(legend=dict(orientation="h", yanchor="top", y=-0.1, x=0, font=dict(size=11, color=MUTED)),
                      margin=dict(b=110))
    return fig


def robustness_figure(rob, ga_path: np.ndarray, goal_marks: Sequence[tuple[int, float]] = (),
                      n_portfolios: int = 9) -> go.Figure:
    fig = glide_path_figure(ga_path, goal_marks, band=(rob.lower, rob.upper), n_portfolios=n_portfolios)
    years = np.arange(1, len(rob.median) + 1)
    fig.add_trace(go.Scatter(x=years, y=rob.median, mode="lines", name=t("chart.rob_median"),
                             line=dict(color=MUTED, width=1.6, dash="dash", shape="hv"),
                             hovertemplate="P%{y}<extra>" + t("chart.rob_median") + "</extra>"))
    return fig


# ------------------------------------------------------------------ grafici della pagina del piano
def _goal_flag(fig: go.Figure, x: float, amount: float, recurring: bool, x_max: float) -> None:
    """Cartellino dell'obiettivo sul bordo superiore (allineato a destra se vicino al margine)."""
    fig.add_annotation(x=x, y=1.0, yref="paper", yanchor="bottom", xanchor="right" if x > 0.9 * x_max else "center",
                       showarrow=False, text=fmt.eur_compact(amount) + (t("unit.per_year") if recurring else ""),
                       font=dict(size=11, color=MUTED))


def allocation_figure(macro: pd.DataFrame, colors: dict[str, str], goal_marks: Sequence[tuple[int, float]] = ()) -> go.Figure:
    """Composizione per asset class nel tempo (area impilata a gradini)."""
    years = [0.5, *macro.index.to_numpy(dtype=float), macro.index.max() + 0.5]
    fig = go.Figure()
    for col in macro.columns:
        values = macro[col].to_numpy()
        y = [values[0], *values, values[-1]]
        name = classes.label(col)
        fig.add_trace(go.Scatter(
            x=years, y=y, mode="lines", name=name, stackgroup="w", line=dict(width=0, color=colors[col], shape="hv"),
            fillcolor=_hex_rgba(colors[col], 0.9), hovertemplate="%{y:.0%}<extra>" + name + "</extra>"))
    for start, end, amount in group_goals(goal_marks):
        fig.add_vline(x=start, line=dict(color="rgba(255,255,255,0.45)", width=1, dash="dot"))
        _goal_flag(fig, start, amount, end > start, float(macro.index.max()))
    fig.update_yaxes(range=[0, 1], tickformat=".0%", dtick=0.25)
    fig.update_xaxes(range=[0.5, float(macro.index.max()) + 0.5], title=t("chart.years_from_now"),
                     dtick=max(1, len(macro) // 8))
    return style(fig, 340, legend=False, hovermode="x unified")


def fan_minimal_figure(fan: pd.DataFrame, goal_marks: Sequence[tuple[int, float]] = ()) -> go.Figure:
    """Ventaglio dei possibili patrimoni: mediana, fascia centrale (25–75) e fascia ampia (5–95)."""
    x = fan.index
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=x, y=fan["P95"], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=fan["P5"], mode="lines", line=dict(width=0), fill="tonexty",
                             fillcolor=_hex_rgba(ACCENT, 0.13), name=t("chart.band_5_95"), hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=fan["P75"], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=fan["P25"], mode="lines", line=dict(width=0), fill="tonexty",
                             fillcolor=_hex_rgba(ACCENT, 0.28), name=t("chart.band_25_75"), hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=x, y=fan["P50"], mode="lines", name=t("chart.median_case"),
                             line=dict(color="#F4F6FB", width=2.6),
                             hovertemplate="€ %{y:,.0f}<extra>" + t("chart.median_case") + "</extra>"))
    fig.add_trace(go.Scatter(x=x, y=fan["P5"], mode="lines", name=t("chart.bad_case"),
                             line=dict(color=hex_rgba(BAD, 0.9), width=1.4, dash="dot"),
                             hovertemplate="€ %{y:,.0f}<extra>" + t("chart.bad_case_hover") + "</extra>"))
    fig.add_hline(y=0, line=dict(color=hex_rgba(BAD, 0.7), width=1, dash="dot"))
    for start, end, amount in group_goals(goal_marks):
        fig.add_vline(x=start, line=dict(color="rgba(255,255,255,0.35)", width=1, dash="dot"))
        _goal_flag(fig, start, amount, end > start, float(x.max()))
    fig.update_yaxes(tickprefix="€ ", tickformat="~s")
    fig.update_xaxes(title=t("chart.years_from_now"), dtick=max(1, (len(x) - 1) // 8))
    return style(fig, 360, legend_y=1.08 if goal_marks else 1.02)


def compare_rows(bench: pd.DataFrame, is_full_range: bool = True) -> list[dict]:
    """Righe del confronto tra la strategia evoluta e alternative semplici (Exhibit 11 del paper).

    Ogni riga: ``label``, ``irr`` (rendimento nei casi peggiori), ``pr``, ``ok`` (soglia rispettata), ``you``.
    ``is_full_range`` indica se il portafoglio più aggressivo disponibile è il P9 («tutto aggressivo»).
    """
    df = bench.set_index("Chiave")
    const = df[df.index.str.startswith("const")]
    best_const = const.sort_values("Score", ascending=False).iloc[0]
    picks = [("chart.cmp.you", df.loc["ga"], True), ("chart.cmp.best_const", best_const, False),
             ("chart.cmp.linear", df.loc["linear"], False),
             ("chart.cmp.all_aggressive" if is_full_range else "chart.cmp.all_max", const.iloc[-1], False),
             ("chart.cmp.all_cautious", const.iloc[0], False)]
    return [{"label": t(key), "irr": float(row["IRR atteso (coda)"]), "pr": float(row["Probabilità di successo"]),
             "ok": bool(row["Soglia rispettata"]), "you": you} for key, row, you in picks]


def cashflow_figure(flows: Flows) -> go.Figure:
    years = np.arange(1, flows.horizon + 1)
    fig = go.Figure()
    fig.add_trace(go.Bar(x=years, y=flows.contributions, name=t("chart.contributions"), marker_color=_hex_rgba(ACCENT, 0.85),
                         hovertemplate="€ %{y:,.0f}<extra>" + t("chart.contribution_hover") + "</extra>"))
    fig.add_trace(go.Bar(x=years, y=-flows.goals, name=t("chart.goals"), marker_color=_hex_rgba(BAD, 0.85),
                         hovertemplate="€ %{y:,.0f}<extra>" + t("chart.goal_one") + "</extra>"))
    fig.update_layout(barmode="relative", bargap=0.2)
    fig.update_yaxes(tickprefix="€ ", tickformat="~s")
    fig.update_xaxes(title=t("chart.year"), dtick=max(1, flows.horizon // 10))
    return style(fig, 220)
