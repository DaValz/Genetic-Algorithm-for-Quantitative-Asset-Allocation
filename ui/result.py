"""Pagina «Il tuo piano»: esito, strategia nel tempo, scenari possibili e confronto, in forma essenziale."""
from __future__ import annotations

import html
from datetime import datetime

import numpy as np
import streamlit as st

from goalga.i18n import render as render_msg
from goalga.i18n import t

from . import charts, classes
from . import format as fmt
from .components import chrome, spacer
from .export import build_excel, build_json
from .risk import success_count
from .state import ResultBundle, go

PLOT_CONFIG = {"displayModeBar": False}


# ------------------------------------------------------------------ testi
def outcome(run: ResultBundle) -> dict:
    """Esito sintetico: percentuale mostrata, se la soglia è rispettata, titolo e frase di contesto."""
    report, plan, oos = run.report, run.plan, run.report.oos
    pr = oos.pr if oos is not None else report.pr
    n = success_count(pr)                                       # «100 su 100» solo se non ci sono scenari falliti
    target = int(round(plan.pr_target * 100))
    validated = oos.feasible if oos is not None else report.ga.feasible       # vale il numero che si mostra
    if validated:
        lead = (t("plan.out.ok.lead", scen=fmt.number(oos.n_scenarios), low=fmt.pct(oos.pr_low, 1),
                  high=fmt.pct(oos.pr_high, 1)) if oos is not None else "")
        return {"ok": True, "n": n, "title": t("plan.out.ok.title", n=n), "lead": lead}
    if report.ga.feasible:  # soglia raggiunta in ricerca ma non confermata su scenari nuovi
        return {"ok": False, "n": n, "title": t("plan.out.near.title", n=n),
                "lead": t("plan.out.near.lead", pr=fmt.pct(oos.pr, 2), target=target)}
    ret, _ = run.market.stats
    required = report.required_return
    best_growth = float(run.market.compound_returns.max())
    reason = (t("plan.out.low.reason", req=fmt.pct(required, 1), max=fmt.pct(best_growth, 1))
              if required is not None and required > best_growth else "")
    more = ""
    higher = [p for p in (run.previews or []) if p.max_level > run.max_level]
    best = max(higher, key=lambda p: p.pr, default=None)
    if best is not None and success_count(best.pr) > n:
        more = t("plan.out.low.more", name=t(f"risk.{best.key}.name"), n=success_count(best.pr))
    return {"ok": False, "n": n, "title": t("plan.out.low.title", n=n),
            "lead": t("plan.out.low.lead", target=target, reason=reason, more=more)}


def _stat(label: str, value: str, sub: str) -> str:
    return (f'<div class="gx-stat"><div class="k">{html.escape(label)}</div><div class="v">{html.escape(value)}</div>'
            f'<div class="s">{html.escape(sub)}</div></div>')


def hero_html(run: ResultBundle) -> str:
    report, plan, oos = run.report, run.plan, run.report.oos
    o = outcome(run)
    badges = []
    if run.data is not None:
        start, end = run.data.prepared.window
        badges.append(f'<span class="gx-badge"><i></i>'
                      f'{html.escape(t("plan.badge.universe", evaluated=fmt.number(run.data.evaluated), picked=fmt.number(len(run.data.requested)), start=f"{start:%m/%Y}", end=f"{end:%m/%Y}"))}</span>')
    badges.append(f'<span class="gx-badge"><i></i>{html.escape(t("plan.badge.profile", name=t(f"risk.{run.risk}.name")))}</span>')
    target = int(round(plan.pr_target * 100))
    badges.append(f'<span class="gx-badge {"ok" if o["ok"] else "warn"}"><i></i>'
                  f'{html.escape(t("plan.badge.ok" if o["ok"] else "plan.badge.warn", target=target))}</span>')
    irr = report.irr_es
    per_year = t("plan.stat.per_year", value=f"{'+' if irr >= 0 else '−'}{fmt.pct(abs(irr), 1)}")
    stats = [
        _stat(t("plan.stat.tail_title", alpha=fmt.pct_short(plan.alpha)), per_year, t("plan.stat.tail_sub"))
        if np.isfinite(irr) and report.irr_reliable else
        _stat(t("plan.stat.worst"), "—", t("plan.stat.not_computable")),
        _stat(t("plan.stat.required"),
              t("plan.stat.per_year", value=fmt.pct(report.required_return, 1)) if report.required_return is not None else "—",
              t("plan.stat.required_sub", pct=fmt.pct(report.expected_path_growth, 1))),
        _stat(t("plan.stat.oos"), fmt.pct(oos.pr, 1) if oos is not None else "—",
              t("plan.stat.oos_sub", n=fmt.number(oos.n_scenarios)) if oos is not None else t("plan.stat.oos_off")),
    ]
    ring = (f'<div class="gx-ring {"" if o["ok"] else "warn"}" style="--pct:{o["n"]}" role="img" '
            f'aria-label="{o["n"]} {html.escape(t("risk.of_100"))}"><span>{o["n"]}<small>/100</small></span></div>')
    return (f'<div class="gx-card"><div class="gx-hero">{ring}<div>'
            f'<div style="display:flex;flex-wrap:wrap;gap:.5rem;margin-bottom:.9rem">{"".join(badges)}</div>'
            f'<h2>{html.escape(o["title"])}</h2><p>{html.escape(o["lead"])}</p></div></div>'
            f'<div class="gx-stats" style="margin-top:1.4rem">{"".join(stats)}</div></div>')


def _section(title: str, text: str = "") -> None:
    st.html(f'<div class="gx-sec"><h3>{html.escape(title)}</h3>{f"<p>{html.escape(text)}</p>" if text else ""}</div>')


def _mix_bar(label: str, weights: dict[str, float], colors: dict[str, str]) -> str:
    segments = "".join(
        f'<i style="width:{w * 100:.2f}%;background:{colors[c]}" title="{html.escape(classes.label(c))} {w:.0%}"></i>'
        for c, w in weights.items() if w > 0.004)
    legend = " · ".join(f"{classes.label(c)} {fmt.pct(w, 0)}" for c, w in weights.items() if w >= 0.005)
    return (f'<div class="gx-mix"><div class="k">{html.escape(label)}</div><div class="bar">{segments}</div>'
            f'<div class="s">{html.escape(legend)}</div></div>')


# ------------------------------------------------------------------ sezioni
def _open_holdings() -> None:
    st.session_state.pop("holdings_pf", None)
    go("holdings")


def _allocation(run: ResultBundle) -> None:
    report, plan = run.report, run.plan
    mapping = classes.asset_class_map(list(run.market.names))
    macro = classes.macro_composition(report.composition, mapping)
    macro = macro.loc[:, macro.max() >= 0.005]          # solo le classi effettivamente usate
    colors = classes.MACRO_COLORS
    first, last = macro.iloc[0].to_dict(), macro.iloc[-1].to_dict()
    _section(t("plan.alloc.title"), t("plan.alloc.text"))
    legend = "".join(f'<span><i style="--c:{colors[c]}"></i>{html.escape(classes.label(c))}</span>' for c in macro.columns)
    st.html(f'<div class="gx-legend">{legend}</div>')
    flows = plan.flows()
    marks = [(int(y), float(flows.goals[y - 1])) for y in flows.goal_years]
    st.plotly_chart(charts.allocation_figure(macro, colors, marks), width="stretch", config=PLOT_CONFIG)
    st.html('<div class="gx-mixes">' + _mix_bar(t("plan.mix.today"), first, colors)
            + _mix_bar(t("plan.mix.year", n=plan.horizon), last, colors) + '</div>')
    with st.container(key="card-holdings"):
        st.html(f'<div class="gx-link-card"><div class="ico"><span class="gx-ico">pie_chart</span></div><div>'
                f'<b>{html.escape(t("plan.holdings.title"))}</b><span>{html.escape(t("plan.holdings.sub"))}</span></div></div>')
        st.button(t("plan.holdings.btn"), key="to-holdings", type="primary", icon=":material/arrow_forward:",
                  on_click=_open_holdings)


def _scenarios(run: ResultBundle) -> None:
    report, plan = run.report, run.plan
    flows = plan.flows()
    marks = [(int(y), float(flows.goals[y - 1])) for y in flows.goal_years]
    end = report.fan.iloc[-1]
    _section(t("plan.scen.title"), t("plan.scen.text", median=fmt.eur_compact(end["P50"]), worst=fmt.eur_compact(end["P5"])))
    st.plotly_chart(charts.fan_minimal_figure(report.fan, marks), width="stretch", config=PLOT_CONFIG)


def compare_html(rows: list[dict]) -> str:
    """Barre del confronto: l'etichetta è a sinistra, il valore a destra, sempre in colonne separate (nessuna sovrapposizione)."""
    values = [r["irr"] for r in rows]
    lo, hi = min(0.0, min(values)), max(0.0, max(values))
    span = max(hi - lo, 1e-6)
    zero = -lo / span * 100
    out = []
    for r in rows:
        v = r["irr"]
        left = zero + min(0.0, v) / span * 100
        width = max(abs(v) / span * 100, 0.8)
        cls = " ".join(c for c in ("you" if r["you"] else "", "" if r["ok"] else "dim") if c)
        sign = "+" if v >= 0 else "−"
        below = f' · {html.escape(t("plan.cmp.below"))}' if not r["ok"] else ""
        out.append(
            f'<div class="row {cls}"><div class="lbl">{html.escape(r["label"])}</div>'
            f'<div class="bar"><span class="axis" style="left:{zero:.2f}%"></span><i style="left:{left:.2f}%;width:{width:.2f}%"></i></div>'
            f'<div class="val"><b>{sign}{fmt.pct(abs(v), 1)}</b>'
            f'<span>{html.escape(t("plan.cmp.prob", pr=fmt.pct(r["pr"], 0)))}{below}</span></div></div>')
    return f'<div class="gx-cmp">{"".join(out)}</div>'


COMPARISON_NOISE = 0.001       # 0,1 punti percentuali: sotto questa soglia la differenza tra due strategie è rumore statistico


def comparison_verdict(bench, target: int) -> tuple[str, dict]:
    """Chiave del testo e parametri del giudizio sul confronto con le strategie semplici (tutte valutate sugli stessi scenari)."""
    table = bench.set_index("Chiave")
    ga, others = table.loc["ga"], table.drop(index="ga")
    valid = others[others["Soglia rispettata"]]
    if not bool(ga["Soglia rispettata"]):
        if valid.empty:
            return "plan.cmp.none", {"target": target}
        best = valid["IRR atteso (coda)"].astype(float).idxmax()
        return "plan.cmp.other", {"target": target, "name": charts.strategy_label(best).lower()}
    if valid.empty:
        return "plan.cmp.only", {"target": target}
    best_key = valid["IRR atteso (coda)"].astype(float).idxmax()
    gap = float(ga["IRR atteso (coda)"]) - float(valid.loc[best_key, "IRR atteso (coda)"])
    name = charts.strategy_label(best_key).lower()
    if gap > COMPARISON_NOISE:
        return "plan.cmp.better", {"target": target, "gap": fmt.number(gap * 100, 2), "name": name}
    if gap < -COMPARISON_NOISE:
        return "plan.cmp.worse", {"target": target, "gap": fmt.number(-gap * 100, 2), "name": name}
    return "plan.cmp.equal", {"target": target, "name": name}


def _comparison(run: ResultBundle) -> None:
    report, plan = run.report, run.plan
    table = report.benchmarks_validated
    target = int(round(plan.pr_target * 100))
    key, args = comparison_verdict(table, target)
    _section(t("plan.cmp.title"), t(key, **args))
    rows = charts.compare_rows(table, is_full_range=run.risk == "dynamic")
    st.html(compare_html(rows))
    note = "plan.cmp.note_oos" if table is not report.benchmarks else "plan.cmp.note"
    st.html(f'<div class="gx-note">{html.escape(t(note, alpha=fmt.pct_short(plan.alpha), target=target))}</div>')


def _try_profile(key: str) -> None:
    ss = st.session_state
    ss["risk"] = key
    ss.pop("seen_run", None)
    go("evolve", keep_seed=True)               # stesso pool e stessi scenari: cambia solo il profilo di rischio


def _whatif(run: ResultBundle) -> None:
    """Cosa cambierebbe con più o meno rischio (stime calcolate alla scelta del profilo)."""
    if not run.previews:
        return
    _section(t("plan.whatif.title"), t("plan.whatif.text"))
    o = outcome(run)
    cols = st.columns(len(run.previews))
    for col, p in zip(cols, run.previews):
        current = p.key == run.risk
        n = o["n"] if current else success_count(p.pr)
        with col, st.container(key=f"wi-{p.key}"):
            st.html(f'<div class="gx-wi{" cur" if current else ""}"><span class="k">{html.escape(t(f"risk.{p.key}.name"))}</span>'
                    f'<b>{"" if current else "≈ "}{n}<small>/100</small></b></div>')
            st.button(t("plan.whatif.current") if current else t("plan.whatif.try"), key=f"wi-btn-{p.key}",
                      disabled=current, on_click=_try_profile, args=(p.key,), width="stretch")


def _notes(run: ResultBundle) -> None:
    report, plan = run.report, run.plan
    key, args = ("plan.note.infl", {"pct": fmt.pct(plan.inflation, 1)}) if plan.inflation > 0 else ("plan.note.nominal", {})
    st.html(f'<div class="gx-note" style="margin-top:.7rem">{html.escape(t(key, **args))}</div>')
    if run.data is not None:
        for text in run.data.prepared.warnings:
            st.warning(render_msg(text))
    if report.ga.stopped_by == "max_generations":
        st.info(t("plan.note.max_gens"), icon=":material/info:")
    for message in report.warnings:
        st.info(render_msg(message), icon=":material/info:")


def _exports(run: ResultBundle) -> None:
    ss = st.session_state
    robust = ss.get("robust")
    rob = robust["report"] if robust and robust["sig"] == run.sig else None
    key = (run.sig, rob is not None, st.session_state.get("lang"))
    cache = ss.get("_export_cache")
    if not cache or cache["key"] != key:
        ss["_export_cache"] = cache = {
            "key": key,
            "xlsx": build_excel(run.report, run.plan, run.market, run.settings, rob),
            "json": build_json(run.report, run.plan, run.market, run.settings),
        }
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    c1, c2, _ = st.columns([1, 1, 1.4])
    c1.download_button(t("plan.export.excel"), cache["xlsx"], f"goalga_plan_{stamp}.xlsx", icon=":material/download:",
                       width="stretch", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    c2.download_button(t("plan.export.json"), cache["json"], f"goalga_plan_{stamp}.json", icon=":material/data_object:",
                       width="stretch", mime="application/json", help=t("plan.export.json_help"))


def _open_lab() -> None:
    st.session_state["lab_section"] = "checks"
    go("lab")


# ------------------------------------------------------------------ ingresso
def render() -> None:
    from . import account

    chrome("plan")
    run: ResultBundle | None = st.session_state.get("result")
    if run is None:
        st.html(f'<div class="gx-card" style="text-align:center">{html.escape(t("plan.empty"))}</div>')
        st.button(t("plan.restart"), on_click=go, args=("start",), key="plan-empty")
        return
    st.html(f'<div class="gx-head gx-compact"><div class="gx-eyebrow">{html.escape(t("plan.eyebrow"))}</div></div>')
    st.html(hero_html(run))
    _notes(run)
    _allocation(run)
    _scenarios(run)
    _comparison(run)
    _whatif(run)
    account.save_card(run)
    spacer()
    _exports(run)
    c1, c2 = st.columns(2)
    c1.button(t("plan.edit"), icon=":material/edit:", on_click=go, args=("start",), key="plan-edit", width="stretch")
    c2.button(t("plan.analysis"), icon=":material/tune:", on_click=_open_lab, key="plan-lab", width="stretch")
    st.html(f'<div class="gx-note" style="margin-top:1.2rem">{html.escape(t("plan.disclaimer"))}</div>')
