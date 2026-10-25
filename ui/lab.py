"""Configurazione avanzata guidata: cinque passi per intervenire su ciò che l'app sceglie da sola."""
from __future__ import annotations

import html

import numpy as np
import streamlit as st

from goalga.data import DataError
from goalga.i18n import render as render_msg
from goalga.i18n import t

from . import analysis, lab_markets, market_tab, method_tab
from .components import chrome, cta, guide, head, spacer
from .state import CLASS_KEYS, EFFORTS, GA_DEFAULTS, LAB_DEFAULTS, build_plan

SECTIONS = ["universe", "returns", "portfolios", "search", "checks", "method"]
NUMBERED = SECTIONS[:5]
# impostazioni di ciascun passo (servono a riconoscere le modifiche rispetto alle scelte automatiche e a ripristinarle)
GROUPS: dict[str, tuple[str, ...]] = {
    "universe": ("pool_mode", "cats_funds", "cats_sectors", "manual_sel", "excluded_sel", "pool_stocks",
                 "stock_share_pct", "min_years"),
    "returns": ("assump_source", "outlook_pt", *[f"cls_{k}" for k in (*CLASS_KEYS, "stocks")]),
    "portfolios": ("max_weight_pct", "use_shrinkage", "boot_method", "use_custom_weights"),
    "search": (*GA_DEFAULTS, "seed_fixed", "seed"),
    "plan": ("tail_free", "growth_pct", "infl_pct", "pr_pct", "alpha_pct"),
}
# i gruppi mostrati nel riepilogo delle modifiche (il piano compare con la ricerca: stesso passo)
GROUP_LABELS = {"universe": "universe", "returns": "returns", "portfolios": "portfolios", "search": "search", "plan": "search"}
_CUSTOM_STATE = ("custom_w", "w_base", "w_base_for", "w_editor", "w_used", "robust", "pool_pin")


def _same(a, b) -> bool:
    if isinstance(b, list):
        return sorted(map(str, a or [])) == sorted(map(str, b))
    return a == b


def changed_groups(ss) -> list[str]:
    """Gruppi di impostazioni che differiscono dalle scelte automatiche, nell'ordine dei passi."""
    out = []
    for group, keys in GROUPS.items():
        relevant = [k for k in keys if not (k == "seed" and not ss.get("seed_fixed"))]
        if any(k in ss and not _same(ss[k], LAB_DEFAULTS[k]) for k in relevant):
            out.append(group)
    return out


def is_customized_from(ss) -> bool:
    """True se lo stato ``ss`` contiene modifiche rispetto alle scelte automatiche."""
    return bool(changed_groups(ss))


def is_customized() -> bool:
    """True se l'utente ha cambiato qualcosa rispetto alle scelte automatiche."""
    return is_customized_from(st.session_state)


def changed_steps(ss) -> list[str]:
    """Passi dell'area avanzata con scelte diverse da quelle automatiche (senza ripetizioni, nell'ordine dei passi)."""
    out: list[str] = []
    for group in changed_groups(ss):
        if GROUP_LABELS[group] not in out:
            out.append(GROUP_LABELS[group])
    return out


def changes_html(ss) -> str:
    """Pillole dei passi modificati («Hai modificato: Dove investire · Rendimenti»), vuoto se è tutto in automatico."""
    steps = changed_steps(ss)
    if not steps:
        return ""
    chips = "".join(f'<span class="gx-badge warn"><i></i>{html.escape(t(f"lab.section.{s}"))}</span>' for s in steps)
    return f'<div class="gx-changes"><span>{html.escape(t("lab.changed"))}</span>{chips}</div>'


def reset_group(group: str) -> None:
    """Riporta un gruppo di impostazioni ai valori automatici."""
    ss = st.session_state
    for key in GROUPS[group]:
        value = LAB_DEFAULTS[key]
        ss[key] = list(value) if isinstance(value, list) else value
    if group == "portfolios":
        for key in ("custom_w", "w_base", "w_base_for", "w_editor", "w_used"):
            ss.pop(key, None)
    if group == "universe":
        ss.pop("pool_pin", None)


def reset_lab() -> None:
    """Torna alle scelte automatiche (tutte le categorie, ipotesi di lungo periodo, parametri predefiniti)."""
    ss = st.session_state
    for group in GROUPS:
        reset_group(group)
    ss["use_advanced"] = False
    for key in _CUSTOM_STATE:
        ss.pop(key, None)


def _back() -> None:
    """Esce dall'area avanzata tenendo le modifiche fatte (se non ce ne sono, si lavora in automatico)."""
    ss = st.session_state
    if not is_customized():
        ss["use_advanced"] = False
    ss["step"] = ss.get("lab_from", "review")


def leave_to_automatic() -> None:
    """«Torna alle scelte automatiche»: azzera ogni modifica ed esce, alla schermata da cui si era arrivati."""
    reset_lab()
    st.session_state["lab_section"] = SECTIONS[0]
    _back()


def _goto(section: str) -> None:
    st.session_state["lab_section"] = section


def _reseed() -> None:
    st.session_state["seed"] = int(np.random.default_rng().integers(1, 2**31 - 1))


def effort_of(ss) -> str | None:
    """Livello di impegno che corrisponde ai parametri correnti (None se sono stati personalizzati)."""
    current = {k: ss.get(k) for k in ("pop_size", "n_scenarios", "patience", "oos_n")}
    for name, preset in EFFORTS.items():
        if all(current[k] == v for k, v in preset.items()):
            return name
    return None


def _apply_effort() -> None:
    ss = st.session_state
    choice = ss.get("effort")
    if choice in EFFORTS:
        ss.update(EFFORTS[choice])


def _section_label(section: str) -> str:
    if section in NUMBERED:
        return f"{NUMBERED.index(section) + 1} · {t(f'lab.section.{section}')}"
    return t(f"lab.section.{section}")


def _changes_strip() -> None:
    strip = changes_html(st.session_state)
    st.html(strip or f'<div class="gx-changes"><span>{html.escape(t("lab.all_auto"))}</span></div>')


# ------------------------------------------------------------------ 4. ricerca e piano
def _search_step() -> None:
    ss = st.session_state
    plan, _ = build_plan()
    guide(4, t("lab.s.title"), t("lab.s.text"))
    ss["effort"] = effort_of(ss)
    effort = st.segmented_control(t("lab.s.effort"), list(EFFORTS), key="effort", on_change=_apply_effort,
                                  label_visibility="collapsed", format_func=lambda e: t(f"lab.s.effort.{e}"))
    st.html(f'<div class="gx-note">{html.escape(t(f"lab.s.effort_text.{effort}") if effort else t("lab.s.effort_custom"))}</div>')

    st.markdown(f"#### {t('lab.plan_options')}")
    ss["tail_free"] = min(int(ss["tail_free"]), plan.horizon)
    c1, c2, c3 = st.columns(3)
    c1.number_input(t("lab.tail_free"), min_value=0, max_value=plan.horizon, step=1, key="tail_free",
                    help=t("lab.tail_free_help"))
    c2.number_input(t("lab.growth"), min_value=-20.0, max_value=30.0, step=0.5, key="growth_pct", format="%.1f",
                    help=t("lab.growth_help"))
    c3.number_input(t("lab.inflation"), min_value=0.0, max_value=30.0, step=0.5, key="infl_pct", format="%.1f",
                    help=t("lab.inflation_help"))
    s1, s2 = st.columns(2)
    s1.slider(t("lab.pr"), 50, 99, step=1, key="pr_pct", format="%d%%", help=t("lab.pr_help"))
    s2.slider(t("lab.alpha"), 1.0, 20.0, step=0.5, key="alpha_pct", format="%.1f%%", help=t("lab.alpha_help"))

    st.markdown(f"#### {t('lab.s.repro')}")
    st.toggle(t("lab.s.seed_fixed"), key="seed_fixed", help=t("lab.s.seed_help"))
    if ss["seed_fixed"]:
        s1, s2 = st.columns([2, 1], vertical_alignment="bottom")
        s1.number_input(t("lab.ga.seed"), min_value=0, max_value=2**31 - 1, step=1, key="seed",
                        help=t("lab.ga.seed_help"))
        s2.button(t("lab.ga.reseed"), on_click=_reseed, icon=":material/casino:", width="stretch",
                  help=t("lab.ga.reseed_help"))
    else:
        st.html(f'<div class="gx-note">{html.escape(t("lab.s.seed_random"))}</div>')
    last = ss.get("result")
    if last is not None:
        st.html(f'<div class="gx-note">{html.escape(t("lab.s.last_seed", seed=last.ga_config.seed))}</div>')

    with st.expander(t("lab.s.expert"), icon=":material/tune:"):
        st.caption(t("lab.ga.caption"))
        c1, c2 = st.columns(2)
        with c1:
            st.slider(t("lab.ga.pop"), 40, 300, step=10, key="pop_size", help=t("lab.ga.pop_help"))
            st.slider(t("lab.ga.pc"), 0.0, 1.0, step=0.05, key="p_c", help=t("lab.ga.pc_help"))
            st.slider(t("lab.ga.mut_v"), 1, 6, key="mut_v", help=t("lab.ga.mut_v_help"))
            st.slider(t("lab.ga.patience"), 20, 400, step=10, key="patience", help=t("lab.ga.patience_help"))
            st.select_slider(t("lab.ga.oos"), [0, 5_000, 10_000, 20_000], key="oos_n",
                             format_func=lambda n: t("lab.ga.oos_off") if n == 0 else f"{n:,}".replace(",", " "),
                             help=t("lab.ga.oos_help"))
        with c2:
            st.slider(t("lab.ga.scen"), 500, 5000, step=500, key="n_scenarios", help=t("lab.ga.scen_help"))
            st.slider(t("lab.ga.pm"), 0.0, 1.0, step=0.05, key="p_m", help=t("lab.ga.pm_help"))
            st.slider(t("lab.ga.elitism"), 0, 5, key="elitism", help=t("lab.ga.elitism_help"))
            st.slider(t("lab.ga.max_gens"), 100, 3000, step=100, key="max_gens")
        st.button(t("lab.ga.reset"), on_click=reset_group, args=("search",), icon=":material/restart_alt:",
                  key="ga-reset")


def _checks_step() -> None:
    guide(5, t("lab.c.title"), t("lab.c.text"))
    run = st.session_state.get("result")
    if run is None:
        st.info(t("lab.no_result"), icon=":material/insights:")
    else:
        analysis.render(run)


def _step_nav(section: str) -> None:
    if section not in NUMBERED:
        return
    index = NUMBERED.index(section)
    cols = st.columns([1, 1, 3])
    slot = 0
    if index > 0:
        cols[slot].button(t("lab.prev"), key="lab-prev", type="tertiary", icon=":material/arrow_back:",
                          on_click=_goto, args=(NUMBERED[index - 1],))
        slot += 1
    if index < len(NUMBERED) - 1:
        cols[slot].button(t("lab.next"), key="lab-next", type="tertiary", icon=":material/arrow_forward:",
                          on_click=_goto, args=(NUMBERED[index + 1],))


def render() -> None:
    ss = st.session_state
    chrome("lab")
    st.button(t("common.back"), key="back-lab", type="tertiary", icon=":material/arrow_back:", on_click=_back)
    head(t("lab.eyebrow"), t("lab.title"), t("lab.sub"))
    if ss.get("lab_section") not in SECTIONS:
        ss["lab_section"] = SECTIONS[0]
    section = st.segmented_control(t("lab.section_label"), SECTIONS, key="lab_section", label_visibility="collapsed",
                                   format_func=_section_label) or SECTIONS[0]
    _changes_strip()
    spacer()

    with st.container(key="lab-body"):
        if section == "universe":
            lab_markets.universe_step()
        elif section in ("returns", "portfolios"):
            try:
                bundle = market_tab.market_for()
            except (ValueError, DataError) as exc:
                st.error(render_msg(exc), icon=":material/error_outline:")
            else:
                if section == "returns":
                    lab_markets.returns_step(bundle.market)
                else:
                    lab_markets.portfolios_step(bundle)
        elif section == "search":
            _search_step()
        elif section == "checks":
            _checks_step()
        else:
            method_tab.render()

    spacer()
    _step_nav(section)
    cta(t("lab.apply"), "evolve", key="cta-lab")
    st.button(t("lab.reset"), key="lab-reset", type="tertiary", icon=":material/restart_alt:", on_click=leave_to_automatic)
