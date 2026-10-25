"""Lingua dell'interfaccia: scelta iniziale (URL, browser), cambio a runtime e persistenza nella sessione."""
from __future__ import annotations

import streamlit as st

from goalga import i18n


def _session_language() -> str | None:
    """Lingua della sessione corrente, usata dai callback dei widget (eseguiti prima dello script)."""
    try:
        return st.session_state.get("lang")
    except Exception:
        return None


i18n.set_resolver(_session_language)


def _from_browser() -> str | None:
    """Lingua preferita dal browser (``st.context``), se supportata."""
    try:
        context = st.context
        header = None
        try:
            header = context.headers.get("Accept-Language")
        except Exception:
            header = None
        return i18n.detect(getattr(context, "locale", None), header)
    except Exception:
        return None


def activate() -> str:
    """Determina la lingua della sessione (URL > browser > predefinita) e la rende attiva per questa esecuzione."""
    ss = st.session_state
    lang = i18n.normalize(ss.get("lang"))
    if lang is None:
        try:
            requested = st.query_params.get("lang")
        except Exception:
            requested = None
        lang = i18n.normalize(requested) or _from_browser() or i18n.default_language()
        ss["lang"] = lang
    i18n.activate(lang)
    return lang


def set_language(code: str) -> None:
    """Callback del selettore: cambia lingua e la riporta nell'URL (così sopravvive a un aggiornamento della pagina)."""
    lang = i18n.normalize(code)
    if lang is None:
        return
    st.session_state["lang"] = lang
    try:
        st.query_params["lang"] = lang
    except Exception:
        pass
