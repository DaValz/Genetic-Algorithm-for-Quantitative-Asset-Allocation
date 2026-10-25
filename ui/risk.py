"""Schermata «Rischio»: quanto rischio sei disposto ad assumere, con la probabilità di riuscita di ciascun profilo."""
from __future__ import annotations

import html

import streamlit as st

from goalga.data import DataError
from goalga.i18n import render as render_msg
from goalga.i18n import t
from goalga.market import Market
from goalga.pipeline import ProfilePreview, preview_profiles
from goalga.plan import Plan
from goalga.risk import PROFILE_KEYS

from . import classes, engine, market_tab
from . import format as fmt
from .components import back, chrome, cta, head, skeleton
from .inputs import confidence_dots
from .state import DEFAULT_RISK, DataBundle, build_plan


def _choose(key: str) -> None:
    st.session_state["risk"] = key


def success_count(pr: float) -> int:
    """Futuri «su 100» da mostrare: mai 100 se anche un solo scenario fallisce."""
    return 100 if pr >= 1.0 else min(99, int(round(pr * 100)))


def ensure_previews(plan: Plan, slot) -> tuple[list[ProfilePreview], Market, DataBundle]:
    """Anteprime dei tre profili per il piano corrente (calcolate una volta sola per piano, impostazioni e seed)."""
    ss = st.session_state
    slot.html(skeleton(t("engine.prep_data"), t("engine.prep_data_sub")))
    bundle = market_tab.market_for()
    market, data = bundle.market, bundle.data
    settings = engine.run_settings()
    sig = engine.preview_signature(plan, market, settings)
    cached = ss.get("risk_previews")
    if cached and cached.get("sig") == sig:
        return cached["items"], market, data
    slot.html(skeleton(t("risk.loading"), t("risk.loading_sub")))
    items = preview_profiles(plan, market, settings)
    ss["risk_previews"] = {"sig": sig, "items": items}
    return items, market, data


def _equity_share(market: Market, level: int, mapping: dict[str, str]) -> float:
    weights = market.weights[:, level - 1]
    return float(sum(w for name, w in zip(market.names, weights) if mapping.get(name) == "equity"))


def _card_html(preview: ProfilePreview, market: Market, mapping: dict[str, str], selected: bool, target: float) -> str:
    n = success_count(preview.pr)
    equity = _equity_share(market, preview.max_level, mapping)
    ok = preview.feasible
    badge = (f'<span class="gx-badge ok"><i></i>{html.escape(t("risk.threshold_ok", target=round(target * 100)))}</span>'
             if ok else "")
    return (
        f'<div class="gx-risk{" sel" if selected else ""}" data-profile="{preview.key}">'
        f'<div class="gx-risk-head"><b>{html.escape(t(f"risk.{preview.key}.name"))}</b>'
        f'<span>{html.escape(t(f"risk.{preview.key}.tag"))}</span></div>'
        f'<div class="gx-risk-prob"><span class="n">{n}</span><small>{html.escape(t("risk.of_100"))}</small></div>'
        f'<div class="gx-risk-lbl">{html.escape(t("risk.prob_label"))}</div>'
        f'{confidence_dots(n, 100, cols=10)}'
        f'<div class="gx-risk-facts">'
        f'<div><span class="k">{html.escape(t("risk.max_equity"))}</span><b>{fmt.pct(equity, 0)}</b></div>'
        f'<div><span class="k">{html.escape(t("risk.bad_year"))}</span><b>{fmt.pct(preview.bad_year, 0)}</b></div></div>'
        f'<div class="gx-risk-badge">{badge}</div></div>')


def _insight(previews: list[ProfilePreview], chosen: str, target: float) -> str:
    """Una frase che legge i numeri: cosa significa il profilo scelto e cosa cambierebbe con più (o meno) rischio."""
    order = list(PROFILE_KEYS)
    by_key = {p.key: p for p in previews}
    cur = by_key[chosen]
    pct_target = round(target * 100)
    if cur.feasible:
        lower = next((by_key[k] for k in order[:order.index(chosen)] if by_key[k].feasible), None)
        if lower is not None:
            return t("risk.insight.lower_enough", name=t(f"risk.{lower.key}.name"), target=pct_target)
        return t("risk.insight.ok", target=pct_target)
    higher = [by_key[k] for k in order[order.index(chosen) + 1:]]
    best = max(higher, key=lambda p: p.pr, default=None)
    if best is not None and success_count(best.pr) > success_count(cur.pr):
        return t("risk.insight.more_risk", name=t(f"risk.{best.key}.name"), n=success_count(best.pr), target=pct_target)
    return t("risk.insight.not_reachable", target=pct_target)


def render() -> None:
    ss = st.session_state
    chrome("risk")
    back("goals")
    head(t("risk.eyebrow"), t("risk.title"), t("risk.sub"))
    plan, errors = build_plan()
    if errors:
        for message in errors:
            st.warning(message, icon=":material/error_outline:")
        return
    slot = st.empty()
    try:
        previews, market, data = ensure_previews(plan, slot)
    except (ValueError, DataError) as exc:
        slot.empty()
        st.error(t("evolve.error", detail=render_msg(exc)), icon=":material/error_outline:")
        return
    slot.empty()
    chosen = ss.get("risk") if ss.get("risk") in PROFILE_KEYS else DEFAULT_RISK
    ss["risk"] = chosen
    mapping = classes.asset_class_map(list(market.names))
    cols = st.columns(3)
    for col, preview in zip(cols, previews):
        with col, st.container(key=f"rk-{preview.key}"):
            st.html(_card_html(preview, market, mapping, preview.key == chosen, plan.pr_target))
            selected = preview.key == chosen
            st.button(t("risk.selected") if selected else t("risk.choose"), key=f"rk-btn-{preview.key}",
                      type="primary" if selected else "secondary", icon=":material/check:" if selected else None,
                      on_click=_choose, args=(preview.key,), width="stretch")
    st.html(f'<div class="gx-insight">{html.escape(_insight(previews, chosen, plan.pr_target))}</div>')
    st.html(f'<div class="gx-note">{html.escape(t("risk.note"))}</div>')
    cta(t("common.continue"), "review")
