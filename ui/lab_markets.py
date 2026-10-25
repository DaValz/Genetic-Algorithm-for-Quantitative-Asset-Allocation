"""Area avanzata, passi 1-3: dove investire, quali rendimenti attendersi e come costruire i 9 portafogli."""
from __future__ import annotations

import html

import numpy as np
import pandas as pd
import streamlit as st

from goalga.data import DataError
from goalga.i18n import render as render_msg
from goalga.i18n import t
from goalga.market import METHODS, Market
from goalga.selection import MAX_WINDOW_YEARS, REASONS, Screen
from goalga.universe import CATEGORIES, FUND_CATEGORIES, SECTOR_CATEGORIES, catalog

from . import charts, market_tab
from . import format as fmt
from .components import guide
from .state import CLASS_KEYS, LAB_DEFAULTS, MarketBundle, pending_seed, signature

MIN_PICKS = market_tab.MIN_ASSETS
DIVERSIFICATION = [20, 25, 30, 40, 50, 60, 80, 100]
OUTLOOKS = [-2.0, -1.0, 0.0, 1.0, 2.0]


def cat_name(key: str) -> str:
    return t(f"cat.{key}")


def _funnel(found: Screen, pool: list[str]) -> str:
    funds = sum(1 for x in pool if catalog().at[x, "Tipo"] == "fund")
    items = [(fmt.number(found.n_evaluated), t("lab.funnel.evaluated")),
             (fmt.number(found.n_eligible), t("lab.funnel.eligible", years=fmt.number(found.min_years))),
             (fmt.number(len(pool)), t("lab.funnel.used", funds=funds, stocks=len(pool) - funds))]
    cells = '<i>→</i>'.join(f'<div><b>{html.escape(n)}</b><span>{html.escape(label)}</span></div>' for n, label in items)
    return f'<div class="gx-funnel">{cells}</div>'


# ------------------------------------------------------------------ 1. universo
def _set(key: str, value) -> None:
    st.session_state[key] = value


def _label(ticker: str, names: pd.Series) -> str:
    return f"{ticker} · {names.get(ticker, ticker)}"


def _auto_universe(found: Screen) -> None:
    ss = st.session_state
    counts = found.category_counts()
    st.html(f'<div class="gx-note">{html.escape(t("lab.u.auto_text"))}</div>')
    for group, key, options in (("lab.u.funds", "cats_funds", FUND_CATEGORIES), ("lab.u.sectors", "cats_sectors", SECTOR_CATEGORIES)):
        head, a, b = st.columns([10, 1.1, 1.1], vertical_alignment="center")
        head.markdown(f"**{t(group)}**")
        a.button(t("lab.u.all"), key=f"{key}-all", type="tertiary", on_click=_set, args=(key, list(options)))
        b.button(t("lab.u.none"), key=f"{key}-none", type="tertiary", on_click=_set, args=(key, []))
        st.pills(t(group), list(options), selection_mode="multi", key=key, label_visibility="collapsed",
                 format_func=lambda c: f"{cat_name(c)} · {fmt.number(counts[c])}")
    chosen = list(ss["cats_funds"]) + list(ss["cats_sectors"])
    funds = [c for c in chosen if c in FUND_CATEGORIES]
    if not funds:
        st.warning(t("lab.u.no_funds"), icon=":material/warning:")
    elif sum(counts[c] for c in chosen) < MIN_PICKS:
        st.warning(t("lab.u.too_few"), icon=":material/warning:")
    with st.expander(t("lab.u.more"), icon=":material/tune:"):
        c1, c2 = st.columns(2)
        c1.slider(t("lab.u.min_years"), 3, MAX_WINDOW_YEARS, key="min_years", help=t("lab.u.min_years_help"))
        c2.slider(t("lab.u.stocks"), 0, 80, key="pool_stocks", help=t("lab.u.stocks_help"))
        c1.slider(t("lab.u.share"), 0, 60, step=5, key="stock_share_pct", format="%d%%", help=t("lab.u.share_help"))
        names = found.eligible()["Nome"]
        options = [_label(x, names) for x in found.eligible().index]
        ss["excluded_sel"] = [x for x in ss["excluded_sel"] if x in set(options)]
        st.multiselect(t("lab.u.exclude"), options, key="excluded_sel", placeholder=t("lab.u.exclude_ph"),
                       help=t("lab.u.exclude_help"))


def _manual_universe(found: Screen) -> None:
    ss = st.session_state
    eligible = found.eligible()
    names = eligible["Nome"]
    st.html(f'<div class="gx-note">{html.escape(t("lab.u.manual_text", min=MIN_PICKS))}</div>')
    options = [_label(x, names) for x in eligible.index]
    ss["manual_sel"] = [x for x in ss["manual_sel"] if x in set(options)]
    st.multiselect(t("lab.u.pick"), options, key="manual_sel", placeholder=t("lab.u.pick_ph"),
                   format_func=lambda s: f"{s} — {cat_name(eligible.at[s.split(' · ')[0], 'Categoria'])}")
    c1, c2, _ = st.columns([1.2, 1, 3])
    funds = [_label(x, names) for x in eligible.index[eligible["Tipo"] == "fund"]]
    c1.button(t("lab.u.pick_funds"), key="pick-funds", on_click=_set, args=("manual_sel", funds), width="stretch")
    c2.button(t("lab.u.none"), key="pick-none", on_click=_set, args=("manual_sel", []), width="stretch")
    n = len(ss["manual_sel"])
    if n < MIN_PICKS:
        st.info(t("lab.u.pick_more", n=n, min=MIN_PICKS), icon=":material/info:")


def _reasons(found: Screen) -> None:
    counts = found.reason_counts()
    with st.expander(t("lab.u.why"), icon=":material/help:"):
        st.html(f'<div class="gx-note">{html.escape(t("lab.u.why_text"))}</div>')
        rows = "".join(
            f'<div class="r"><span class="k">{html.escape(t(f"lab.reason.{r}", years=fmt.number(found.min_years)))}</span>'
            f'<span class="v">{fmt.number(counts[r])}</span></div>' for r in REASONS if r in counts)
        st.html(f'<div class="gx-card gx-rcpt">{rows}</div>')


def _browse(found: Screen) -> None:
    counts = found.category_counts()
    with st.expander(t("lab.u.browse"), icon=":material/travel_explore:"):
        key = st.selectbox(t("lab.u.browse_pick"), list(CATEGORIES), key="browse_cat",
                           format_func=lambda c: f"{cat_name(c)} · {fmt.number(counts[c])}")
        sub = found.eligible()
        sub = sub[sub["Categoria"] == key].copy()
        table = catalog().loc[sub.index]
        frame = pd.DataFrame({
            t("lab.u.col_ticker"): sub.index, t("lab.u.col_name"): sub["Nome"].to_numpy(),
            t("lab.u.col_detail"): (table["Industria"].where(table["Industria"] != "", table["Gruppo"])).to_numpy(),
            t("lab.u.col_years"): (sub["Months"] / 12).round(1).to_numpy(),
            t("lab.u.col_vol"): (sub["Vol"] * 100).round(1).to_numpy()})
        st.dataframe(frame.sort_values(t("lab.u.col_name")), hide_index=True, width="stretch", height=300)


def universe_step() -> None:
    ss = st.session_state
    try:
        found = market_tab.screen()
    except DataError as exc:
        st.error(render_msg(exc))
        return
    guide(1, t("lab.u.title"), t("lab.u.text", evaluated=fmt.number(found.n_evaluated)))
    mode = st.segmented_control(t("lab.u.mode"), ["auto", "manual"], key="pool_mode", label_visibility="collapsed",
                                format_func=lambda m: t(f"lab.u.mode.{m}"))
    if mode is None:
        ss["pool_mode"] = mode = "auto"
    (_auto_universe if mode == "auto" else _manual_universe)(found)
    try:
        pool = market_tab.pool_for(pending_seed())
        st.html(_funnel(found, pool))
    except DataError as exc:
        st.error(render_msg(exc))
    _reasons(found)
    _browse(found)


# ------------------------------------------------------------------ 2. rendimenti
def _outlook_label(value: float) -> str:
    return t("lab.r.outlook_zero") if abs(value) < 1e-9 else t("lab.r.outlook_pts", value=f"{value:+g}".replace("-", "−"))


def _class_inputs() -> None:
    st.html(f'<div class="gx-note">{html.escape(t("lab.r.classes_text"))}</div>')
    keys = [*CLASS_KEYS, "stocks"]
    cols = st.columns(2)
    for i, key in enumerate(keys):
        label = t("lab.r.stocks_premium") if key == "stocks" else cat_name(key)
        cols[i % 2].number_input(label, min_value=-5.0, max_value=25.0, step=0.1, format="%.2f", key=f"cls_{key}",
                                 help=t("lab.r.stocks_premium_help") if key == "stocks" else t("lab.r.class_help"))
    st.button(t("lab.r.restore"), key="cls-restore", type="tertiary", icon=":material/restart_alt:",
              on_click=_restore_classes)


def _restore_classes() -> None:
    for key in (*CLASS_KEYS, "stocks"):
        st.session_state[f"cls_{key}"] = LAB_DEFAULTS[f"cls_{key}"]


def returns_step(market: Market) -> None:
    ss = st.session_state
    guide(2, t("lab.r.title"), t("lab.r.text"))
    source = st.segmented_control(t("lab.r.source"), ["long_term", "historical"], key="assump_source",
                                  label_visibility="collapsed", format_func=lambda s: t(f"lab.r.source.{s}"))
    if source is None:
        ss["assump_source"] = source = "long_term"
    st.html(f'<div class="gx-note">{html.escape(t(f"lab.r.source_text.{source}"))}</div>')
    if source == "historical":
        st.warning(t("lab.r.hist_warning"), icon=":material/warning:")
    st.select_slider(t("lab.r.outlook"), OUTLOOKS, key="outlook_pt", format_func=_outlook_label, help=t("lab.r.outlook_help"))
    if source == "long_term":
        with st.expander(t("lab.r.classes"), icon=":material/tune:"):
            _class_inputs()
    ret, _ = market.stats
    st.html(f'<div class="gx-card gx-rcpt"><div class="r"><span class="k">{html.escape(t("lab.r.result_low"))}</span>'
            f'<span class="v">{html.escape(fmt.pct(float(ret[0]), 1))}</span></div>'
            f'<div class="r"><span class="k">{html.escape(t("lab.r.result_high"))}</span>'
            f'<span class="v">{html.escape(fmt.pct(float(ret[-1]), 1))}</span></div></div>')
    extreme = [f"{x} ({fmt.pct(v, 0)})" for x, v in zip(market.names, market.mu) if v > 0.20]
    if extreme:
        st.warning(t("lab.r.extreme", assets=", ".join(extreme[:6])), icon=":material/warning:")


# ------------------------------------------------------------------ 3. portafogli
def _custom_weights(market: Market) -> None:
    """Approccio plug-and-play (solo con asset scelti a mano): sostituisce i 9 portafogli con pesi propri.

    ``market`` è il mercato con i portafogli efficienti (prima dei pesi personalizzati).
    """
    ss = st.session_state
    ss["custom_w"] = None
    base_sig = signature(market.names, np.round(market.mu, 6), market.method, market.n_months)
    with st.expander(t("mkt.w.title"), icon=":material/edit:"):
        st.caption(t("mkt.w.caption"))
        if ss.get("w_base_for") != base_sig:
            frame = (market.weights_frame() * 100).round(2)
            frame.insert(0, "Asset", frame.index)
            ss["w_base"] = frame.reset_index(drop=True)
            ss["w_base_for"] = base_sig
            ss.pop("w_editor", None)
            ss.pop("w_used", None)
        elif "w_editor" not in ss and ss.get("w_used") is not None:
            ss["w_base"] = ss["w_used"]        # stato dell'editor scartato cambiando sezione: si tengono le modifiche
        c1, c2 = st.columns([1, 1])
        c1.toggle(t("mkt.w.use"), key="use_custom_weights")
        c2.button(t("mkt.w.reset"), on_click=_reset_weights)
        edited = st.data_editor(ss["w_base"], hide_index=True, key="w_editor", width="stretch", disabled=["Asset"],
                                column_config={c: st.column_config.NumberColumn(c, min_value=0.0, max_value=100.0,
                                                                                step=1.0, format="%.1f")
                                               for c in ss["w_base"].columns if c != "Asset"})
        ss["w_used"] = edited
        weights = edited.drop(columns="Asset").to_numpy(dtype=float) / 100.0
        sums = weights.sum(axis=0)
        st.caption(t("mkt.w.sums", sums=" · ".join(f"P{i + 1} {fmt.pct(s, 1)}" for i, s in enumerate(sums))))
        if not ss["use_custom_weights"]:
            return
        if np.isnan(weights).any() or (weights < 0).any():
            st.error(t("mkt.w.err_neg"))
            return
        if not np.allclose(sums, 1.0, atol=0.005):
            st.error(t("mkt.w.err_sum"))
            return
        ss["custom_w"] = weights / sums


def _reset_weights() -> None:
    for key in ("w_editor", "w_used"):
        st.session_state.pop(key, None)
    st.session_state["w_base_for"] = None


def portfolios_step(bundle: MarketBundle) -> None:
    ss = st.session_state
    market = bundle.market
    manual = ss.get("pool_mode") == "manual"
    guide(3, t("lab.p.title"), t("lab.p.text"))
    caps = sorted({*DIVERSIFICATION, int(ss["max_weight_pct"])})
    st.select_slider(t("lab.p.cap_manual" if manual else "lab.p.cap"), caps, key="max_weight_pct",
                     format_func=lambda v: f"{v}%", help=t("lab.p.cap_help_manual" if manual else "lab.p.cap_help"))
    if market.frontier.degenerate:
        st.warning(t("mkt.pf.degenerate"), icon=":material/warning:")
    left, right = st.columns(2)
    with left:
        st.markdown(f"**{t('mkt.pf.frontier')}**")
        st.plotly_chart(charts.frontier_figure(market), width="stretch", config={"displayModeBar": False})
    with right:
        st.markdown(f"**{t('lab.p.by_class')}**")
        st.plotly_chart(charts.categories_figure(market), width="stretch", config={"displayModeBar": False})
    with st.expander(t("lab.p.expert"), icon=":material/tune:"):
        c1, c2 = st.columns(2)
        c1.toggle(t("mkt.pf.shrinkage"), key="use_shrinkage", help=t("mkt.pf.shrinkage_help"))
        c2.selectbox(t("mkt.pf.bootstrap"), list(METHODS), key="boot_method", format_func=lambda m: t(f"mkt.method.{m}"),
                     help=t("mkt.pf.bootstrap_help"))
        summary = market.summary()
        table = pd.DataFrame({
            t("mkt.pf.col_pf"): summary["Portafoglio"], t("mkt.pf.col_ret"): summary["Rendimento atteso"] * 100,
            t("mkt.pf.col_vol"): summary["Volatilità"] * 100, t("mkt.pf.col_ratio"): summary["Rapporto R/V"]})
        st.dataframe(table, hide_index=True, width="stretch", column_config={
            t("mkt.pf.col_ret"): st.column_config.NumberColumn(format="%.2f"),
            t("mkt.pf.col_vol"): st.column_config.NumberColumn(format="%.2f"),
            t("mkt.pf.col_ratio"): st.column_config.NumberColumn(format="%.2f")})
    if manual and bundle.base is not None:
        _custom_weights(bundle.base)
