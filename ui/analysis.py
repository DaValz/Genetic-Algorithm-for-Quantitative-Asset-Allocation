"""Analisi dettagliata (area avanzata): KPI, glide path, proiezioni, rischio, confronto e robustezza."""
from __future__ import annotations

import html
from typing import Callable

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from goalga.analytics import OptimizationReport, run_robustness
from goalga.genetic import GAConfig
from goalga.i18n import render as render_msg
from goalga.i18n import t, tn
from goalga.market import Market
from goalga.plan import Plan

from . import charts
from . import format as fmt
from .state import ResultBundle

PLOT_CONFIG = {"displayModeBar": False}


# ------------------------------------------------------------------ utilità
def delta_text(x: float, unit: str | None = None, decimals: int = 1) -> str:
    """Differenza con segno ASCII, es. '+3,3 pp'."""
    return f"{'+' if x >= 0 else '-'}{fmt.number(abs(x) * 100, decimals)} {unit or t('unit.pp')}"


def phases(path: np.ndarray, ret: np.ndarray, vol: np.ndarray) -> pd.DataFrame:
    """Raggruppa gli anni consecutivi con lo stesso portafoglio in fasi operative (intestazioni nella lingua attiva)."""
    rows, start = [], 0
    for i in range(1, len(path) + 1):
        if i == len(path) or path[i] != path[start]:
            level = int(path[start])
            rows.append({t("an.col_years"): f"{start + 1}" if i - start == 1 else f"{start + 1}–{i}",
                         t("an.col_portfolio"): f"P{level}", t("an.col_exp_ret"): ret[level - 1] * 100,
                         t("an.col_vol"): vol[level - 1] * 100})
            start = i
    return pd.DataFrame(rows)


def cached_figure(name: str, sig: str, builder: Callable[[], go.Figure]) -> go.Figure:
    """Memorizza le figure del risultato corrente: i rerun che non cambiano nulla restano istantanei."""
    lang = st.session_state.get("lang")
    cache = st.session_state.setdefault("_fig_cache", {})
    if cache.get("__sig__") != (sig, lang):
        cache.clear()
        cache["__sig__"] = (sig, lang)
    if name not in cache:
        cache[name] = builder()
    return cache[name]


def show(fig: go.Figure) -> None:
    st.plotly_chart(fig, width="stretch", config=PLOT_CONFIG)


# ------------------------------------------------------------------ KPI e diagnostica
def kpi_card(label: str, value: str, sub: str = "", tone: str = "", help: str = "") -> str:
    tip = f' title="{html.escape(help, quote=True)}"' if help else ""
    sub_html = f'<div class="s {tone}">{html.escape(sub)}</div>' if sub else ""
    return (f'<div class="gx-stat"{tip}><div class="k">{html.escape(label)}</div>'
            f'<div class="v">{html.escape(value)}</div>{sub_html}</div>')


def _kpis(report: OptimizationReport, plan: Plan) -> None:
    cols = st.columns(5)
    gap = report.pr - plan.pr_target
    cols[0].markdown(kpi_card(
        t("an.kpi.pr"), fmt.pct(report.pr, 1),
        t("an.kpi.vs_threshold", delta=delta_text(gap), target=fmt.pct(plan.pr_target, 0)),
        "good" if gap >= -1e-9 else "bad", t("an.kpi.pr_help")), unsafe_allow_html=True)
    required = report.required_return
    spread = None if required is None else report.irr_es - required
    cols[1].markdown(kpi_card(
        t("an.kpi.irr", alpha=fmt.pct_short(plan.alpha)), fmt.pct(report.irr_es, 2),
        "" if spread is None else t("an.kpi.vs_required", delta=delta_text(spread, decimals=2)),
        "" if spread is None else ("good" if spread >= 0 else "warn"), t("an.kpi.irr_help")), unsafe_allow_html=True)
    cols[2].markdown(kpi_card(
        t("an.kpi.tail"), fmt.eur_compact(report.tail_wealth),
        t("an.kpi.deficit") if report.tail_wealth < 0 else t("an.kpi.no_deficit"),
        "bad" if report.tail_wealth < 0 else "good", t("an.kpi.tail_help")), unsafe_allow_html=True)
    cols[3].markdown(kpi_card(
        t("an.kpi.required"), fmt.pct(required, 2) if required is not None else t("an.na"),
        t("an.kpi.expected_path", pct=fmt.pct(report.expected_path_growth, 2)), "", t("an.kpi.required_help")),
        unsafe_allow_html=True)
    if report.oos is not None:
        oos = report.oos
        cols[4].markdown(kpi_card(
            t("an.kpi.oos"), fmt.pct(oos.pr, 1),
            t("an.kpi.ci", low=fmt.pct(oos.pr_low, 1), high=fmt.pct(oos.pr_high, 1)),
            "good" if oos.feasible else "warn", t("an.kpi.oos_help", n=fmt.number(oos.n_scenarios))),
            unsafe_allow_html=True)
    else:
        cols[4].markdown(kpi_card(t("an.kpi.oos"), t("an.off")), unsafe_allow_html=True)


def _diagnostics(report: OptimizationReport, plan: Plan, market: Market) -> None:
    best_growth = float(market.compound_returns.max())
    target = fmt.pct(plan.pr_target, 0)
    if not report.ga.feasible:
        required = report.required_return
        hint = ""
        if required is not None and required > best_growth:
            hint = t("an.diag.hint", required=fmt.pct(required, 2), max=fmt.pct(best_growth, 2))
        st.warning(t("an.diag.infeasible", target=target, pr=fmt.pct(report.pr, 1), hint=hint), icon=":material/warning:")
    elif report.oos is not None and not report.oos.feasible:
        st.warning(t("an.diag.oos", pr=fmt.pct(report.oos.pr, 1), target=target), icon=":material/rule:")
    if report.ga.stopped_by == "max_generations":
        st.info(t("an.diag.max_gens"), icon=":material/info:")
    for message in report.warnings:
        st.info(render_msg(message), icon=":material/info:")


# ------------------------------------------------------------------ sotto-schede
def _summary_tab(report: OptimizationReport, plan: Plan, market: Market, sig: str) -> None:
    flows = plan.flows()
    ret, vol = market.stats
    marks = [(int(y), float(flows.goals[y - 1])) for y in flows.goal_years]
    rob = st.session_state.get("robust")
    rob_report = rob["report"] if rob and rob["sig"] == sig else None
    left, right = st.columns([1.55, 1])
    with left:
        st.markdown(f"##### {t('an.glide.title')}")
        st.caption(t("an.glide.caption"))
        band = (rob_report.lower, rob_report.upper) if rob_report is not None else None
        show(cached_figure("glide-rob" if band else "glide", sig,
                           lambda: charts.glide_path_figure(report.path, marks, band, market.n_portfolios)))
    with right:
        st.markdown(f"##### {t('an.phases.title')}")
        frame = phases(report.path, ret, vol)
        st.dataframe(frame, hide_index=True, width="stretch", column_config={
            t("an.col_exp_ret"): st.column_config.NumberColumn(format="%.2f"),
            t("an.col_vol"): st.column_config.NumberColumn(format="%.2f")})
        first, last = int(report.path[0]), int(report.path[-1])
        avg = fmt.pct(report.expected_path_return, 2)
        if report.switches == 0:
            st.caption(t("an.phases.constant", first=first, avg=avg))
        else:
            st.caption(t("an.phases.moves", first=first, last=last, n=tn("an.switches", report.switches), avg=avg))

    st.markdown(f"##### {t('an.comp.title')}")
    allocation_explorer(report, market, sig)


@st.fragment
def allocation_explorer(report: OptimizationReport, market: Market, sig: str) -> None:
    horizon = len(report.path)
    left, right = st.columns([1.55, 1])
    with left:
        show(cached_figure("composition", sig, lambda: charts.composition_figure(report.composition)))
    with right:
        year = st.slider(t("an.comp.year"), 1, horizon, key=f"alloc_year_{horizon}")
        level = int(report.path[year - 1])
        weights = report.composition.loc[year].sort_values(ascending=False)
        weights = weights[weights > 0.0005]
        st.caption(t("an.comp.caption", year=year, level=level))
        frame = pd.DataFrame({t("an.col_asset"): weights.index, t("an.col_weight"): weights.values * 100})
        st.dataframe(frame, hide_index=True, width="stretch", height=min(320, 36 + 35 * len(frame)),
                     column_config={t("an.col_weight"): st.column_config.ProgressColumn(
                         format="%.1f%%", min_value=0, max_value=100)})


def _projection_tab(report: OptimizationReport, plan: Plan, sig: str) -> None:
    flows = plan.flows()
    marks = [(int(y), float(flows.goals[y - 1])) for y in flows.goal_years]
    st.markdown(f"##### {t('an.proj.title')}")
    st.caption(t("an.proj.caption"))
    show(cached_figure("fan", sig, lambda: charts.fan_figure(report.fan, marks)))
    left, right = st.columns([1, 1.2])
    with left:
        st.markdown(f"##### {t('an.goalprob.title')}")
        show(cached_figure("goals", sig, lambda: charts.goals_figure(report.goals, plan.pr_target)))
    with right:
        st.markdown(f"##### {t('an.goaldetail.title')}")
        st.caption(t("an.goaldetail.caption"))
        goals = report.goals.copy()
        goals["Probabilità cumulata di successo"] *= 100
        st.dataframe(goals, hide_index=True, width="stretch", column_config={
            "Anno": st.column_config.NumberColumn(t("an.col_year")),
            "Obiettivo": st.column_config.NumberColumn(t("an.col_amount"), format="localized"),
            "Probabilità cumulata di successo": st.column_config.NumberColumn(t("an.col_cum_prob"), format="%.1f"),
            "Copertura mediana": st.column_config.NumberColumn(t("an.col_cov_median"), format="%.1f"),
            "Copertura nel 5° percentile": st.column_config.NumberColumn(t("an.col_cov_p5"), format="%.1f")})
    st.markdown(f"##### {t('an.cashflow.title')}")
    show(cached_figure("cashflow", sig, lambda: charts.cashflow_figure(flows)))


def _risk_tab(report: OptimizationReport, plan: Plan, sig: str) -> None:
    left, right = st.columns([1.4, 1])
    with left:
        st.markdown(f"##### {t('an.terminal.title')}")
        st.caption(t("an.terminal.caption", alpha=fmt.pct_short(plan.alpha)))
        show(cached_figure("terminal", sig, lambda: charts.terminal_figure(report.terminal, plan.alpha)))
    with right:
        st.markdown(f"##### {t('an.percentiles.title')}")
        q = report.terminal_quantiles.round(0)
        st.dataframe(pd.DataFrame({t("an.col_percentile"): q.index, t("an.col_final_wealth"): q.values}),
                     hide_index=True, width="stretch", column_config={
                         t("an.col_final_wealth"): st.column_config.NumberColumn(format="localized")})
    st.markdown(f"##### {t('an.bench.title')}")
    st.caption(t("an.bench.caption"))
    left, right = st.columns([1.3, 1])
    with left:
        show(cached_figure("bench", sig, lambda: charts.benchmark_figure(report.benchmarks_validated, plan.pr_target)))
    with right:
        bench = report.benchmarks_validated.copy()
        labels = [charts.strategy_label(k) for k in bench["Chiave"]]
        bench = bench.drop(columns=["Chiave", "Strategia", "Score", "Soglia rispettata"])
        bench[t("an.col_strategy")] = labels
        bench["Probabilità di successo"] *= 100
        bench["IRR atteso (coda)"] *= 100
        bench["Patrimonio finale medio (coda)"] = bench["Patrimonio finale medio (coda)"].round(0)
        bench = bench[[t("an.col_strategy"), "Probabilità di successo", "IRR atteso (coda)",
                       "Patrimonio finale medio (coda)"]]
        st.dataframe(bench, hide_index=True, width="stretch", height=420, column_config={
            t("an.col_strategy"): st.column_config.TextColumn(width="medium"),
            "Probabilità di successo": st.column_config.NumberColumn(t("an.col_prob_short"), format="%.1f", width="small"),
            "IRR atteso (coda)": st.column_config.NumberColumn(t("an.col_irr_short"), format="%.2f", width="small"),
            "Patrimonio finale medio (coda)": st.column_config.NumberColumn(
                t("an.col_tail_wealth_short"), format="localized", width="small")})


def _algorithm_tab(report: OptimizationReport, plan: Plan, market: Market, ga_config: GAConfig,
                   n_scenarios: int, sig: str) -> None:
    ga = report.ga
    reasons = {"patience": t("an.stop.converged"), "max_generations": t("an.stop.limit"), "user": t("an.stop.user")}
    c = st.columns(4)
    c[0].metric(t("an.alg.generations"), f"{ga.generations}", border=True)
    c[1].metric(t("an.alg.best_at"), t("an.alg.gen_n", n=ga.best_generation + 1), border=True)
    c[2].metric(t("an.alg.time"), f"{fmt.number(ga.elapsed, 1)} s", border=True)
    c[3].metric(t("an.alg.stop"), reasons.get(ga.stopped_by, ga.stopped_by), border=True, help=t("an.alg.stop_help"))
    st.markdown(f"##### {t('an.conv.title')}")
    st.caption(t("an.conv.caption"))
    show(cached_figure("convergence", sig, lambda: charts.convergence_figure(ga.history, ga.best_generation)))

    st.markdown(f"##### {t('an.rob.title')}")
    st.caption(t("an.rob.caption"))
    c1, c2, _ = st.columns([1, 1, 2], vertical_alignment="bottom")
    n_runs = c1.slider(t("an.rob.runs"), 5, 50, key="rob_runs")
    run = c2.button(t("an.rob.run"), icon=":material/repeat:", key="rob_btn", width="stretch")
    if run:
        progress = st.progress(0.0, text=t("an.rob.progress", k=0, n=n_runs))
        rob = run_robustness(
            market, plan.flows(), pr_target=plan.pr_target, alpha=plan.alpha, ga_config=ga_config,
            n_runs=n_runs, n_scenarios=n_scenarios, seed=(ga_config.seed or 0) + 5,
            progress=lambda k, n: progress.progress(k / n, text=t("an.rob.progress", k=k, n=n)))
        progress.empty()
        st.session_state["robust"] = {"sig": sig, "report": rob, "runs": n_runs}
        st.toast(t("an.rob.done"), icon=":material/check_circle:")
    rob_state = st.session_state.get("robust")
    if rob_state and rob_state["sig"] == sig:
        rob = rob_state["report"]
        c = st.columns(4)
        c[0].metric(t("an.rob.runs_m"), f"{len(rob.pr)}", border=True)
        c[1].metric(t("an.rob.reach"), f"{int(rob.feasible.sum())}/{len(rob.pr)}", border=True)
        c[2].metric(t("an.rob.within"), fmt.pct(rob.modal_share, 0), border=True)
        c[3].metric(t("an.rob.maxdev"), t("an.rob.levels", n=rob.max_deviation), border=True)
        flows = plan.flows()
        marks = [(int(y), float(flows.goals[y - 1])) for y in flows.goal_years]
        show(charts.robustness_figure(rob, report.path, marks, market.n_portfolios))
        st.caption(t("an.rob.summary", irr_lo=fmt.pct(rob.irr_es.min(), 2), irr_hi=fmt.pct(rob.irr_es.max(), 2),
                     pr_lo=fmt.pct(rob.pr.min(), 1), pr_hi=fmt.pct(rob.pr.max(), 1)))


# ------------------------------------------------------------------ ingresso
def render(run: ResultBundle) -> None:
    """Analisi dettagliata del risultato corrente (stessi dati e ipotesi che lo hanno generato)."""
    st.session_state.setdefault("rob_runs", 10)
    report, plan, market = run.report, run.plan, run.market
    _kpis(report, plan)
    _diagnostics(report, plan, market)
    tabs = st.tabs([t("an.tab.summary"), t("an.tab.wealth"), t("an.tab.risk"), t("an.tab.algorithm")])
    with tabs[0]:
        _summary_tab(report, plan, market, run.sig)
    with tabs[1]:
        _projection_tab(report, plan, run.sig)
    with tabs[2]:
        _risk_tab(report, plan, run.sig)
    with tabs[3]:
        _algorithm_tab(report, plan, market, run.ga_config, run.n_scenarios, run.sig)
