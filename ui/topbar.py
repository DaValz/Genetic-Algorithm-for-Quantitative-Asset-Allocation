"""Controlli in alto a destra: selettore della lingua e accesso all'account."""
from __future__ import annotations

import streamlit as st

from goalga.i18n import LANGS, t

from . import lang as ui_lang
from .state import go


def _pick_language() -> None:
    ui_lang.set_language(st.session_state.get("lang_pick"))


def _open_account() -> None:
    ss = st.session_state
    if ss.get("step") != "account":
        ss["account_from"] = ss.get("step", "welcome")
    go("account")


def account_label() -> tuple[str, str]:
    """Testo e icona del pulsante account: «Accedi» per gli ospiti, nome e notifiche per chi ha effettuato l'accesso."""
    ss = st.session_state
    user = ss.get("user")
    if not user:
        return t("top.signin"), ":material/account_circle:"
    unread = int(ss.get("alerts_unread", 0) or 0)
    name = (user.get("name") or user["email"].split("@")[0]).strip()
    short = name if len(name) <= 14 else name[:13] + "…"
    return (f"{short} · {unread}" if unread else short,
            ":material/notifications_active:" if unread else ":material/account_circle:")


def render() -> None:
    ss = st.session_state
    ss["lang_pick"] = ss.get("lang") or "en"       # il selettore riflette sempre la lingua attiva
    label, icon = account_label()
    with st.container(key="topctl"):
        st.selectbox(t("top.language"), list(LANGS), key="lang_pick", format_func=LANGS.get,
                     label_visibility="collapsed", on_change=_pick_language)
        st.button(label, key="acct-btn", icon=icon, on_click=_open_account, help=t("top.account_help"))
