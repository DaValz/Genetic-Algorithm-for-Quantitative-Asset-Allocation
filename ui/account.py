"""Account: accesso, salvataggio dei portafogli, avvisi sui pesi e gestione nel tempo."""
from __future__ import annotations

import html
from datetime import date

import streamlit as st

from goalga import i18n
from goalga.accounts import AccountError, Accounts, Database, Portfolio, User
from goalga.accounts.messages import describe
from goalga.accounts.monitor import check_portfolio, estimate_wealth, version_origin
from goalga.accounts.payload import (
    SOURCE_LABEL,
    elapsed_years,
    fan_value,
    year_fraction,
    years_elapsed,
)
from goalga.i18n import render as render_msg
from goalga.i18n import t, tn
from goalga.pipeline import goal_kinds, is_monitorable, plan_to_spec, spec_plan
from goalga.risk import PROFILE_KEYS

from . import format as fmt
from . import lang as ui_lang
from .components import chrome, head, spacer
from .state import ResultBundle, apply_spec, begin, go

_NAME_KEYS = ("si_email", "si_password", "su_name", "su_email", "su_password", "su_password2")


# ------------------------------------------------------------------ servizio e sessione
@st.cache_resource(show_spinner=False)
def _service() -> Accounts:
    return Accounts(Database())


def svc() -> Accounts | None:
    """Servizio degli account; ``None`` (e un messaggio) se l'archivio non è raggiungibile."""
    try:
        return _service()
    except Exception:
        return None


def reset_service() -> None:
    """Dimentica il servizio in cache (test e cambi di configurazione)."""
    _service.clear()


def user() -> dict | None:
    return st.session_state.get("user")


def refresh_badge() -> None:
    """Aggiorna il numero di avvisi non letti mostrato in alto a destra (una query leggera per esecuzione)."""
    ss = st.session_state
    me = ss.get("user")
    if not me:
        ss["alerts_unread"] = 0
        return
    service = svc()
    try:
        ss["alerts_unread"] = service.unread_count(me["id"]) if service else 0
    except Exception:
        ss["alerts_unread"] = 0


def _login(account: User) -> None:
    ss = st.session_state
    ss["user"] = {"id": account.id, "email": account.email, "name": account.name, "locale": account.locale}
    for key in _NAME_KEYS:
        ss.pop(key, None)
    if i18n.normalize(account.locale):
        ui_lang.set_language(account.locale)
    refresh_badge()
    back = ss.pop("account_from", None)
    if back in ("plan", "holdings", "review", "risk"):
        ss["step"] = back


def sign_out() -> None:
    ss = st.session_state
    for key in ("user", "alerts_unread", "editing_portfolio", "saved_portfolio", "holdings_pf", *_NAME_KEYS):
        ss.pop(key, None)
    ss["step"] = "welcome"


# ------------------------------------------------------------------ accesso e registrazione
def _auth_error(exc: Exception) -> None:
    st.session_state["auth_error"] = render_msg(exc)


def _do_signin() -> None:
    ss = st.session_state
    service = svc()
    if service is None:
        ss["auth_error"] = t("acct.err.unavailable")
        return
    try:
        _login(service.authenticate(ss.get("si_email", ""), ss.get("si_password", "")))
    except AccountError as exc:
        _auth_error(exc)
        ss["si_password"] = ""


def _do_signup() -> None:
    ss = st.session_state
    service = svc()
    if service is None:
        ss["auth_error"] = t("acct.err.unavailable")
        return
    if ss.get("su_password") != ss.get("su_password2"):
        ss["auth_error"] = t("acct.err.password_mismatch")
        return
    try:
        account = service.register(ss.get("su_email", ""), ss.get("su_password", ""), ss.get("su_name", ""),
                                   locale=ss.get("lang") or "en")
        _login(account)
    except AccountError as exc:
        _auth_error(exc)
        ss["su_password"] = ss["su_password2"] = ""


def _auth_page() -> None:
    head(t("acct.eyebrow"), t("acct.title.guest"), t("acct.sub.guest"))
    if svc() is None:
        st.error(t("acct.err.unavailable"), icon=":material/cloud_off:")
        return
    message = st.session_state.pop("auth_error", None)
    tab_in, tab_up = st.tabs([t("acct.tab.signin"), t("acct.tab.signup")])
    with tab_in:
        with st.container(key="card-signin"):
            st.text_input(t("acct.email"), key="si_email", autocomplete="email")
            st.text_input(t("acct.password"), key="si_password", type="password", autocomplete="current-password")
            st.button(t("acct.signin"), key="si_submit", type="primary", on_click=_do_signin)
    with tab_up:
        with st.container(key="card-signup"):
            st.text_input(t("acct.name"), key="su_name", autocomplete="name")
            st.text_input(t("acct.email"), key="su_email", autocomplete="email")
            st.text_input(t("acct.password"), key="su_password", type="password", autocomplete="new-password",
                          help=t("acct.pw_hint", min=8))
            st.text_input(t("acct.password2"), key="su_password2", type="password", autocomplete="new-password")
            st.button(t("acct.signup"), key="su_submit", type="primary", on_click=_do_signup)
    if message:
        st.error(message, icon=":material/error_outline:")
    st.html(f'<div class="gx-note">{html.escape(t("acct.privacy"))}</div>')


# ------------------------------------------------------------------ avvisi
def _alert_card(alert, names: dict[int, str]) -> str:
    text = describe(alert, names.get(alert.portfolio_id, "—"))
    rows = "".join(
        f'<tr><td>{html.escape(r["asset"])}<small>{html.escape(r["ticker"])}</small></td><td>{html.escape(r["old"])}</td>'
        f'<td><b>{html.escape(r["new"])}</b></td><td class="{"up" if r["up"] else "down"}">{html.escape(r["delta"])}</td></tr>'
        for r in text.rows)
    table = f'<table class="gx-alert-table"><tbody>{rows}</tbody></table>' if rows else ""
    new = "" if alert.read_at else f'<span class="gx-badge ok"><i></i>{html.escape(t("acct.alerts.new"))}</span>'
    return (f'<div class="gx-alert{"" if alert.read_at else " unread"}"><div class="top"><b>{html.escape(text.title)}</b>{new}'
            f'<span class="when">{alert.created_at:%d/%m/%Y}</span></div><p>{html.escape(text.summary)}</p>{table}</div>')


def _mark_all_read() -> None:
    me, service = user(), svc()
    if me and service:
        service.mark_read(me["id"])
        refresh_badge()


def _alerts_section(service: Accounts, me: dict, names: dict[int, str]) -> None:
    items = service.list_alerts(me["id"], limit=30)
    st.html(f'<div class="gx-sec"><h3>{html.escape(t("acct.alerts.title"))}</h3></div>')
    if not items:
        st.html(f'<div class="gx-note">{html.escape(t("acct.alerts.none"))}</div>')
        return
    unread = [a for a in items if a.read_at is None]
    for alert in unread:
        st.html(_alert_card(alert, names))
    if unread:
        st.button(t("acct.alerts.mark_all"), key="alerts-read", on_click=_mark_all_read, type="tertiary",
                  icon=":material/done_all:")
    older = [a for a in items if a.read_at is not None]
    if older:
        with st.expander(t("acct.alerts.older")):
            for alert in older:
                st.html(_alert_card(alert, names))


# ------------------------------------------------------------------ portafogli
def _next_change(res: dict, pf: Portfolio, today: date) -> tuple[int, int, int] | None:
    """Prossimo cambio di portafoglio previsto dal glide path: (anno solare, livello attuale, nuovo livello)."""
    if pf.start_date is None:
        return None
    k = years_elapsed(pf.start_date, today)
    anchor, path = int(res.get("anchor", 0)), res["path"]
    idx = min(max(k - anchor, 0), len(path) - 1)
    for j in range(idx + 1, len(path)):
        if path[j] != path[idx]:
            return pf.start_date.year + anchor + j, int(path[idx]), int(path[j])
    return None


def _pf_open_holdings(pid: int) -> None:
    st.session_state["holdings_pf"] = pid
    go("holdings")


def _edit_spec(service: Accounts, pf: Portfolio, version, today: date) -> tuple[dict, str] | None:
    """Specifica da cui si modifica un portafoglio: il piano rimasto da oggi, non quello iniziale.

    Il capitale è la stima del patrimonio di oggi (ultimo valore registrato o mediana prevista dal piano) e gli anni
    degli obiettivi sono contati da oggi: salvare la modifica non fa ripartire l'orologio del piano. Restituisce la
    specifica e l'origine del capitale (``checkin``, ``projection`` o ``plan`` se il portafoglio non è mai stato
    seguito), oppure ``None`` se del piano non resta nulla da modificare.
    """
    spec = version.spec
    if pf.start_date is None:                       # mai seguito: il piano è quello salvato
        return dict(spec), "plan"
    plan = spec_plan(spec)
    anchor = int(version.result.get("anchor", 0))
    floor = max(pf.start_date, version_origin(version))
    wealth, source = estimate_wealth(pf, version, plan, service.latest_checkin(pf.id, after=floor), today)
    k = years_elapsed(pf.start_date, today)
    remaining = plan.advance(k - anchor, wealth, year_fraction(pf.start_date, today))
    if remaining is None:
        return None
    kinds = goal_kinds(remaining, spec["plan"]["goals"], k - anchor)
    return {**spec, "plan": plan_to_spec(remaining, kinds)}, source


def _pf_edit(pid: int) -> None:
    ss = st.session_state
    me, service = user(), svc()
    if not me or not service:
        return
    pf = service.get_portfolio(me["id"], pid)
    version = service.current_version(pf.id)
    edit = _edit_spec(service, pf, version, service.today())
    if edit is None:
        ss["space_error"] = t("acct.edit.nothing_left")
        return
    spec, source = edit
    apply_spec(spec)
    ss["editing_portfolio"] = pid
    ss["edit_note"] = {"name": pf.name, "source": source, "value": float(spec["plan"]["w0"])}
    go("start")


def _pf_toggle_follow(pid: int) -> None:
    ss = st.session_state
    me, service = user(), svc()
    if not me or not service:
        return
    try:
        service.set_invested(me["id"], pid, bool(ss.get(f"follow_{pid}")))
    except AccountError as exc:
        ss["space_error"] = render_msg(exc)


def _pf_delete(pid: int) -> None:
    me, service = user(), svc()
    if me and service:
        service.delete_portfolio(me["id"], pid)
        st.session_state.pop("confirm_delete", None)
        if st.session_state.get("editing_portfolio") == pid:
            st.session_state.pop("editing_portfolio", None)


def _ask_delete(pid: int) -> None:
    st.session_state["confirm_delete"] = pid


def _cancel_delete() -> None:
    st.session_state.pop("confirm_delete", None)


def _reason_label(reason: str) -> str:
    return t(f"acct.reason.{reason}")


def _tracking_text(version, pf: Portfolio, checkin) -> str:
    """Dove si trova il valore reale rispetto alle attese (fasce 5°–95° e mediana) del giorno in cui è stato registrato.

    Le attese sono interpolate tra due anniversari (prima dei flussi del successivo), non quelle di inizio anno; un valore
    precedente alla versione in corso non è confrontabile con il suo piano e non genera messaggi.
    """
    res = version.result
    if not res.get("fan") or pf.start_date is None or checkin.on_date < version_origin(version):
        return ""
    try:
        net = spec_plan(version.spec).flows().net
    except (KeyError, TypeError, ValueError):
        net = None
    when = elapsed_years(pf.start_date, checkin.on_date)
    median, low = fan_value(res, "p50", when, net), fan_value(res, "p5", when, net)
    if median is None or low is None:
        return ""
    if checkin.value >= median:
        return t("acct.checkin.above", median=fmt.eur_compact(median))
    if checkin.value >= low:
        return t("acct.checkin.inside", median=fmt.eur_compact(median))
    return t("acct.checkin.below")


def _history(service: Accounts, me: dict, pf: Portfolio, version, names: dict[int, str]) -> None:
    with st.expander(t("acct.pf.history")):
        versions = service.versions(me["id"], pf.id)
        for v in versions:
            m = v.result.get("metrics", {})
            pr = m.get("oos_pr") if m.get("oos_pr") is not None else m.get("pr", 0)
            st.html(f'<div class="gx-note">{html.escape(t("acct.pf.version_row", n=v.number, date=f"{v.created_at:%d/%m/%Y}", reason=_reason_label(v.reason)))}'
                    f' · {html.escape(t("acct.pf.prob", n=min(99, round(pr * 100))))}</div>')
        related = service.list_alerts(me["id"], portfolio_id=pf.id, limit=10)
        for alert in related:
            st.html(_alert_card(alert, names))
        if pf.invested:
            st.markdown(f"**{t('acct.checkin.title')}**")
            st.caption(t("acct.checkin.help"))
            c1, c2 = st.columns([2, 1], vertical_alignment="bottom")
            value = c1.number_input(t("acct.checkin.value"), min_value=0.0, step=1000.0, key=f"ci_value_{pf.id}",
                                    format="%.0f", label_visibility="collapsed")
            if c2.button(t("acct.checkin.save"), key=f"ci_save_{pf.id}", width="stretch"):
                try:
                    service.add_checkin(me["id"], pf.id, float(value))
                    st.toast(t("acct.checkin.saved"), icon=":material/check_circle:")
                except AccountError as exc:
                    st.error(render_msg(exc))
            last = service.checkins(me["id"], pf.id)[:1]
            if last:
                st.html(f'<div class="gx-note">{html.escape(t("acct.checkin.last", value=fmt.eur(last[0].value), date=f"{last[0].on_date:%d/%m/%Y}"))}'
                        f' {html.escape(_tracking_text(version, pf, last[0]))}</div>')
            with st.popover(t("acct.pf.options"), icon=":material/tune:"):
                tol = st.slider(t("acct.pf.tolerance"), 1, 20, int(round(pf.tolerance * 100)), key=f"tol_{pf.id}",
                                format="%d%%")
                days = st.select_slider(t("acct.pf.review_days"), [30, 60, 90, 180, 365], value=min(
                    [30, 60, 90, 180, 365], key=lambda d: abs(d - pf.review_days)), key=f"days_{pf.id}")
                if st.button(t("common.save"), key=f"opt_save_{pf.id}"):
                    service.set_alert_options(me["id"], pf.id, review_days=days, tolerance=tol / 100)
                    st.toast(t("acct.settings.saved"), icon=":material/check_circle:")


def _portfolio_card(service: Accounts, me: dict, pf: Portfolio, names: dict[int, str]) -> None:
    today = service.today()
    version = service.current_version(pf.id)
    res, spec = version.result, version.spec
    metrics = res.get("metrics", {})
    pr = metrics.get("oos_pr") if metrics.get("oos_pr") is not None else metrics.get("pr", 0.0)
    status = "completed" if pf.status == "completed" else ("following" if pf.invested else "idle")
    risk_key = spec.get("risk", "balanced")
    risk_name = t(f"risk.{risk_key}.name") if risk_key in PROFILE_KEYS else "—"
    status_name = t(f"acct.pf.status.{status}")
    chips = [f'<span class="gx-badge {"ok" if status == "following" else ""}"><i></i>{html.escape(status_name)}</span>',
             f'<span class="gx-badge">{html.escape(risk_name)}</span>']
    facts = [("acct.pf.prob_label", t("acct.pf.prob", n=min(99, round(pr * 100)))),
             ("acct.pf.horizon", tn("unit.years", int(res.get("horizon", 0))))]
    if pf.invested and pf.start_date is not None:
        k = years_elapsed(pf.start_date, today)
        facts.append(("acct.pf.progress_label", t("acct.pf.progress", k=min(k + 1, int(res["anchor"]) + int(res["horizon"])),
                                                 total=int(res["anchor"]) + int(res["horizon"]))))
        nxt = _next_change(res, pf, today)
        facts.append(("acct.pf.next_label", t("acct.pf.next_change", year=nxt[0], a=nxt[1], b=nxt[2])
                      if nxt else t("acct.pf.no_next")))
    fact_html = "".join(f'<div><span class="k">{html.escape(t(k))}</span><b>{html.escape(v)}</b></div>' for k, v in facts)
    with st.container(key=f"pfcard-{pf.id}"):
        st.html(f'<div class="gx-pf"><div class="top"><b>{html.escape(pf.name)}</b>{"".join(chips)}</div>'
                f'<div class="sub">{html.escape(t("acct.pf.created", date=f"{pf.created_at:%d/%m/%Y}"))}</div>'
                f'<div class="facts">{fact_html}</div></div>')
        if pf.invested and not is_monitorable(spec):
            st.html(f'<div class="gx-note">{html.escape(t("acct.pf.not_monitorable"))}</div>')
        st.session_state.setdefault(f"follow_{pf.id}", pf.invested)
        st.session_state[f"follow_{pf.id}"] = pf.invested
        st.toggle(t("acct.pf.follow"), key=f"follow_{pf.id}", help=t("acct.pf.follow_help"),
                  on_change=_pf_toggle_follow, args=(pf.id,))
        c1, c2, c3, c4 = st.columns(4)
        c1.button(t("acct.pf.composition"), key=f"pf-comp-{pf.id}", icon=":material/pie_chart:", width="stretch",
                  on_click=_pf_open_holdings, args=(pf.id,))
        c2.button(t("acct.pf.edit"), key=f"pf-edit-{pf.id}", icon=":material/edit:", width="stretch",
                  on_click=_pf_edit, args=(pf.id,))
        check = c3.button(t("acct.pf.check"), key=f"pf-check-{pf.id}", icon=":material/refresh:", width="stretch",
                          disabled=not pf.invested, help=t("acct.pf.check_help") if pf.invested
                          else t("acct.pf.check_only_followed"))
        c4.button(t("common.delete"), key=f"pf-del-{pf.id}", icon=":material/delete:", width="stretch",
                  on_click=_ask_delete, args=(pf.id,))
        if st.session_state.get("confirm_delete") == pf.id:
            st.warning(t("acct.pf.delete_confirm", name=pf.name), icon=":material/warning:")
            d1, d2, _ = st.columns([1, 1, 2])
            d1.button(t("acct.pf.delete_yes"), key=f"pf-del-yes-{pf.id}", type="primary", on_click=_pf_delete, args=(pf.id,))
            d2.button(t("common.cancel"), key=f"pf-del-no-{pf.id}", on_click=_cancel_delete)
        if check:
            _run_check(service, me, pf)
        _history(service, me, pf, version, names)


def _loader(tickers, years):
    from .market_service import service as market_service

    return market_service().get(tuple(tickers), int(years))


def _run_check(service: Accounts, me: dict, pf: Portfolio) -> None:
    before = len(service.list_alerts(me["id"], limit=100))
    with st.spinner(t("acct.pf.checking")):
        outcome = check_portfolio(service, pf.id, force=True, loader=_loader)
    refresh_badge()
    if outcome.status == "error":
        st.error(t("acct.pf.check_error", detail=outcome.error), icon=":material/error_outline:")
    elif len(service.list_alerts(me["id"], limit=100)) > before or outcome.alert_id:
        st.success(t("acct.pf.check_done_changed"), icon=":material/notifications_active:")
    else:
        st.info(t("acct.pf.check_done_same"), icon=":material/check:")


# ------------------------------------------------------------------ impostazioni dell'account
def _settings(service: Accounts, me: dict) -> None:
    with st.expander(t("acct.settings.title"), icon=":material/settings:"):
        account = service.get_user(me["id"])
        name = st.text_input(t("acct.settings.name"), value=account.name, key="set_name")
        alerts_on = st.toggle(t("acct.settings.email_alerts"), value=account.email_alerts, key="set_email_alerts")
        if st.button(t("common.save"), key="set_save"):
            updated = service.update_profile(me["id"], name=name, email_alerts=alerts_on)
            st.session_state["user"]["name"] = updated.name
            st.toast(t("acct.settings.saved"), icon=":material/check_circle:")
        st.divider()
        st.markdown(f"**{t('acct.settings.change_pw')}**")
        old = st.text_input(t("acct.settings.old_pw"), type="password", key="set_old_pw")
        new = st.text_input(t("acct.settings.new_pw"), type="password", key="set_new_pw", help=t("acct.pw_hint", min=8))
        if st.button(t("acct.settings.change_pw"), key="set_pw_btn"):
            try:
                service.change_password(me["id"], old, new)
                st.toast(t("acct.settings.pw_changed"), icon=":material/check_circle:")
            except AccountError as exc:
                st.error(render_msg(exc))
        st.divider()
        st.markdown(f"**{t('acct.settings.delete')}**")
        st.caption(t("acct.settings.delete_help"))
        confirm = st.text_input(t("acct.settings.delete_confirm_pw"), type="password", key="set_del_pw")
        if st.button(t("acct.settings.delete"), key="set_del_btn"):
            try:
                service.delete_user(me["id"], confirm)
                sign_out()
                st.rerun()
            except AccountError as exc:
                st.error(render_msg(exc))


def _space_page() -> None:
    service, me = svc(), user()
    if service is None:
        st.error(t("acct.err.unavailable"), icon=":material/cloud_off:")
        return
    top, out = st.columns([1, .32], vertical_alignment="center")
    top.html(f'<div class="gx-head"><div class="gx-eyebrow">{html.escape(t("acct.eyebrow"))}</div>'
             f'<h1 class="gx-h2">{html.escape(t("acct.hello", name=me["name"] or me["email"].split("@")[0]))}</h1>'
             f'<p class="gx-sub">{html.escape(me["email"])}</p></div>')
    if out.button(t("acct.signout"), key="signout", icon=":material/logout:"):
        sign_out()
        st.rerun()
    if st.session_state.get("space_error"):
        st.error(st.session_state.pop("space_error"))
    portfolios = service.list_portfolios(me["id"])
    names = {p.id: p.name for p in portfolios}
    _alerts_section(service, me, names)
    st.html(f'<div class="gx-sec"><h3>{html.escape(t("acct.pf.title"))}</h3></div>')
    if not portfolios:
        st.html(f'<div class="gx-card" style="text-align:center;color:var(--mute)">{html.escape(t("acct.pf.none"))}</div>')
    for pf in portfolios:
        _portfolio_card(service, me, pf, names)
    spacer()
    st.button(t("acct.pf.new"), key="pf-new", type="primary", icon=":material/add:", on_click=begin, args=())
    _settings(service, me)


def render() -> None:
    chrome("account")
    ss = st.session_state
    from_step = ss.get("account_from") if not user() else None
    if from_step and from_step not in ("account",):
        st.button(t("common.back"), key="back-account", type="tertiary", icon=":material/arrow_back:",
                  on_click=_leave_account)
    if not user():
        _auth_page()
    else:
        _space_page()


def _leave_account() -> None:
    ss = st.session_state
    ss["step"] = ss.pop("account_from", "welcome")


# ------------------------------------------------------------------ salvataggio dal risultato
def _default_name(run: ResultBundle) -> str:
    return t("acct.save.default_name", date=f"{date.today():%d/%m/%Y}")


def _open_account_from_plan() -> None:
    st.session_state["account_from"] = "plan"
    go("account")


def _save_new() -> None:
    ss = st.session_state
    run: ResultBundle | None = ss.get("result")
    me, service = user(), svc()
    if run is None or not me or not service:
        ss["save_msg"] = ("error", t("acct.err.unavailable"))
        return
    if run.plan.first_period != 1.0:
        ss["save_msg"] = ("error", t("acct.save.partial"))
        return
    from goalga.accounts.payload import result_payload
    from goalga.universe import universe_names

    names = dict(run.data.names) if run.data is not None else universe_names(list(run.market.names))
    payload = result_payload(run.report, run.market, run.plan, names=names, source=SOURCE_LABEL, risk=run.risk,
                             max_level=run.max_level)
    try:
        pf = service.create_portfolio(me["id"], ss.get("save_name", ""), run.spec, payload,
                                      invested=bool(ss.get("save_follow", True)))
    except AccountError as exc:
        ss["save_msg"] = ("error", render_msg(exc))
        return
    ss["saved_portfolio"] = pf.id
    ss["editing_portfolio"] = pf.id
    ss["save_msg"] = ("success", t("acct.save.done", name=pf.name))
    refresh_badge()


def _save_version() -> None:
    ss = st.session_state
    run: ResultBundle | None = ss.get("result")
    me, service = user(), svc()
    pid = ss.get("editing_portfolio")
    if run is None or not me or not service or not pid:
        return
    from goalga.accounts.payload import result_payload
    from goalga.universe import universe_names

    names = dict(run.data.names) if run.data is not None else universe_names(list(run.market.names))
    payload = result_payload(run.report, run.market, run.plan, names=names, source=SOURCE_LABEL, risk=run.risk,
                             max_level=run.max_level)
    try:
        version, alert = service.save_version(me["id"], pid, run.spec, payload)
    except AccountError as exc:
        ss["save_msg"] = ("error", render_msg(exc))
        return
    msg = t("acct.save.updated", n=version.number)
    if alert is not None:
        msg += " " + t("acct.save.alert_created")
    ss["save_msg"] = ("success", msg)
    ss["saved_portfolio"] = pid
    refresh_badge()


def _drop_editing() -> None:
    st.session_state.pop("editing_portfolio", None)


def save_card(run: ResultBundle) -> None:
    """Riquadro «Salva» della pagina del piano: ospiti, nuovo portafoglio o nuova versione di uno esistente."""
    ss = st.session_state
    me = user()
    with st.container(key="card-save"):
        st.html(f'<div class="gx-link-card"><div class="ico"><span class="gx-ico">bookmark</span></div><div>'
                f'<b>{html.escape(t("acct.save.title"))}</b><span>'
                f'{html.escape(t("acct.save.logged" if me else "acct.save.guest", email=me["email"] if me else ""))}</span></div></div>')
        if not me:
            st.button(t("acct.save.guest_btn"), key="save-guest", type="primary", icon=":material/person_add:",
                      on_click=_open_account_from_plan)
            return
        message = ss.pop("save_msg", None)
        if message:
            (st.success if message[0] == "success" else st.error)(message[1])
        service = svc()
        editing = ss.get("editing_portfolio")
        existing = None
        if service and editing:
            try:
                existing = service.get_portfolio(me["id"], editing)
            except AccountError:
                ss.pop("editing_portfolio", None)
        if existing is not None:
            st.html(f'<div class="gx-note"><b>{html.escape(t("acct.save.update_title", name=existing.name))}</b></div>')
            c1, c2 = st.columns(2)
            c1.button(t("acct.save.update_btn"), key="save-version", type="primary", icon=":material/save:",
                      on_click=_save_version, width="stretch")
            if run.plan.first_period == 1.0:          # un piano che riparte a metà anno vale solo per questo portafoglio
                c2.button(t("acct.save.as_new"), key="save-as-new", icon=":material/library_add:", width="stretch",
                          on_click=_drop_editing)
            return
        st.text_input(t("acct.save.name"), value=_default_name(run), key="save_name", max_chars=80)
        st.toggle(t("acct.save.follow"), value=True, key="save_follow", help=t("acct.save.follow_help"))
        if not is_monitorable(run.spec or {}):
            st.html(f'<div class="gx-note">{html.escape(t("acct.pf.not_monitorable"))}</div>')
        st.button(t("acct.save.btn"), key="save-new", type="primary", icon=":material/save:", on_click=_save_new)
        if ss.get("saved_portfolio"):
            st.button(t("acct.save.open"), key="save-open", type="tertiary", icon=":material/arrow_forward:",
                      on_click=go, args=("account",))
