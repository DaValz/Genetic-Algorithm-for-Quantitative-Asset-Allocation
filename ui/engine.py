"""Schermata «Evoluzione»: prepara i dati, esegue l'algoritmo genetico e ne mostra la ricerca (una sola volta)."""
from __future__ import annotations

import html

import numpy as np
import streamlit as st

from goalga.data import DataError
from goalga.genetic import GAConfig
from goalga.i18n import render as render_msg
from goalga.i18n import t
from goalga.market import Market
from goalga.pipeline import RunSettings, optimize, preview_profiles
from goalga.plan import Plan
from goalga.risk import profile_caps

from . import format as fmt
from . import market_tab, stage
from .components import back, chrome, forward_button, head, skeleton
from .state import (DEFAULT_RISK, DataBundle, ResultBundle, build_plan, go, launch_seed, market_options, pending_seed,
                    setting, signature, spec_from_run, universe_choice)


def run_settings(seed: int | None = None) -> RunSettings:
    """Parametri della ricerca dallo stato: predefiniti, salvo modifiche nell'area avanzata (se attiva).

    Senza ``seed`` si usa quello che avrà il prossimo avvio (le anteprime del rischio), altrimenti quello indicato.
    """
    cfg = GAConfig(
        pop_size=int(setting("pop_size")), p_c=float(setting("p_c")), p_m=float(setting("p_m")),
        mut_v=int(setting("mut_v")), patience=int(setting("patience")), max_generations=int(setting("max_gens")),
        elitism=int(setting("elitism")), seed=pending_seed() if seed is None else int(seed))
    return RunSettings(cfg, int(setting("n_scenarios")), int(setting("oos_n")))


def market_signature(market: Market) -> str:
    return signature(market.names, np.round(market.mu, 8), np.round(market.weights, 6), market.method,
                     market.custom_weights, market.n_months)


def run_signature(plan: Plan, market: Market, settings: RunSettings, risk: str) -> str:
    return signature(plan, market_signature(market), settings.ga, settings.n_scenarios, settings.oos_n, risk)


def preview_signature(plan: Plan, market: Market, settings: RunSettings) -> str:
    """Firma delle anteprime per profilo (indipendente dal profilo scelto)."""
    return signature("preview", plan, market_signature(market), settings.ga, settings.n_scenarios)


def optimize_run(plan: Plan, market: Market, data: DataBundle, settings: RunSettings, risk: str, sig: str,
                 previews: list | None) -> ResultBundle:
    """Scenari, algoritmo genetico (con registrazione dell'evoluzione) e post-elaborazione."""
    ss = st.session_state
    cap = profile_caps(market.n_portfolios)[risk]
    out = optimize(plan, market, settings, max_level=cap)
    cfg = settings.ga
    info = {
        "scenarios": settings.n_scenarios, "validation_scenarios": settings.oos_n, "population": cfg.pop_size,
        "p_crossover": cfg.p_c, "p_mutation": cfg.p_m, "mutation_step": cfg.mut_v, "patience": cfg.patience,
        "max_generations": cfg.max_generations, "elitism": cfg.elitism, "seed": cfg.seed,
        "assets_evaluated": data.evaluated, "assets_selected": len(data.requested), "risk_profile": risk,
        "max_level": cap}
    spec = spec_from_run(
        plan, market, data, cfg, settings.n_scenarios, settings.oos_n, risk=risk, advanced=bool(ss.get("use_advanced")),
        goals=list(ss["goals"]), choice=universe_choice(), options=market_options(data.requested),
        custom_weights=market.custom_weights)
    return ResultBundle(sig, out.report, plan, info, out.market, cfg, settings.n_scenarios, data, out.trace, risk,
                        cap, spec, previews)


def prepare_run(plan: Plan, slot) -> ResultBundle:
    """Restituisce il risultato valido per il piano corrente, calcolandolo solo se serve."""
    ss = st.session_state
    seed = launch_seed()
    slot.html(skeleton(t("engine.prep_data"), t("engine.prep_data_sub")))
    bundle = market_tab.market_for(seed)
    market, data = bundle.market, bundle.data
    settings = run_settings(seed)
    risk = ss.get("risk", DEFAULT_RISK)
    sig = run_signature(plan, market, settings, risk)
    current: ResultBundle | None = ss.get("result")
    if current is not None and current.sig == sig and current.trace is not None:
        return current
    cached = ss.get("risk_previews")
    psig = preview_signature(plan, market, settings)
    previews = cached["items"] if cached and cached.get("sig") == psig else None
    if previews is None:                         # piano o impostazioni cambiati dopo la scelta del rischio (es. area avanzata)
        slot.html(skeleton(t("risk.loading"), t("risk.loading_sub")))
        previews = preview_profiles(plan, market, settings)
        ss["risk_previews"] = {"sig": psig, "items": previews}
    slot.html(skeleton(t("engine.evolving"), t("engine.evolving_sub", pop=settings.ga.pop_size,
                                               n=fmt.number(settings.n_scenarios))))
    ss["result"] = run = optimize_run(plan, market, data, settings, risk, sig, previews)
    return run


def _open_plan(sig: str) -> None:
    st.session_state["seen_run"] = sig          # una volta vista l'evoluzione non si ripete
    go("plan")


def render() -> None:
    ss = st.session_state
    chrome("evolve")
    head(t("evolve.eyebrow"), t("evolve.title"), compact=True)
    plan, errors = build_plan()
    if errors:
        for message in errors:
            st.warning(message, icon=":material/error_outline:")
        back("review")
        return
    slot = st.empty()
    try:
        run = prepare_run(plan, slot)
    except (ValueError, DataError) as exc:
        slot.empty()
        st.error(t("evolve.error", detail=render_error(exc)), icon=":material/error_outline:")
        st.button(t("evolve.back_to_review"), on_click=go, args=("review",), key="err-back")
        return
    slot.empty()
    if ss.get("seen_run") == run.sig:           # già mostrata: si va dritti al piano
        ss["step"] = "plan"
        st.rerun()

    trace = run.trace
    millis = stage.replay_duration_ms(trace)
    st.html(f"<style>:root{{--late:{millis / 1000 + 1.6:.1f}s}}</style>")
    with st.container(key="stage"):
        stage.embed(stage.stage_html(trace, run.plan, millis, run.data.evaluated if run.data else None), height=620)
    universe = (t("evolve.universe", evaluated=fmt.number(run.data.evaluated), picked=fmt.number(len(run.data.requested)))
                if run.data is not None else "")
    st.html('<div class="gx-note gx-late">'
            + html.escape(t("evolve.done_note", secs=fmt.number(trace["elapsed"], 1), gens=fmt.number(trace["generations"])))
            + (f' · {html.escape(universe)}' if universe else "") + '</div>')
    with st.container(key="cta-late"):
        forward_button(t("evolve.cta"), key="cta-late-btn", on_click=_open_plan, args=(run.sig,))


def render_error(exc: object) -> str:
    """Testo di un errore o di un messaggio traducibile nella lingua attiva."""
    return render_msg(exc)
