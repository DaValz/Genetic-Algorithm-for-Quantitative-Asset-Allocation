"""Componenti visivi condivisi dalle schermate: intestazioni, navigazione, scheletri di caricamento."""
from __future__ import annotations

import html
import re
from typing import Callable

import streamlit as st

from goalga.i18n import t

from . import theme, topbar
from .state import JOURNEY, go

_GRADIENT = re.compile(r"\[\[(.+?)\]\]")
_BOLD = re.compile(r"\*\*(.+?)\*\*")


def rich(text: str) -> str:
    """Testo dei cataloghi -> HTML sicuro: ``[[x]]`` colora con il gradiente, ``**x**`` è in grassetto, ``\\n`` va a capo."""
    out = html.escape(str(text), quote=False)
    out = _GRADIENT.sub(r'<span class="gx-grad">\1</span>', out)
    out = _BOLD.sub(r"<b>\1</b>", out)
    return out.replace("\n", "<br>")


def chrome(step: str) -> None:
    """Barra superiore con marchio e avanzamento del percorso, più lingua e account in alto a destra."""
    index = JOURNEY.index(step) + 1 if step in JOURNEY else 0
    theme.chrome(index, len(JOURNEY))
    topbar.render()


def head(eyebrow: str, title: str, sub: str = "", *, big: bool = False, compact: bool = False) -> None:
    """Intestazione di schermata (``title`` può contenere ``[[parole]]`` con il gradiente)."""
    tag = "gx-h1" if big else "gx-h2"
    lead = f'<p class="gx-sub">{html.escape(sub)}</p>' if sub else ""
    cls = "gx-head gx-compact" if compact else "gx-head"
    st.html(f'<div class="{cls}"><div class="gx-eyebrow">{html.escape(eyebrow)}</div>'
            f'<h1 class="{tag}">{rich(title)}</h1>{lead}</div>')


def back(step: str, label: str | None = None) -> None:
    st.button(label or t("common.back"), key=f"back-{st.session_state['step']}", type="tertiary",
              icon=":material/arrow_back:", on_click=go, args=(step,))


def forward_button(label: str, *, key: str, icon: str = ":material/arrow_forward:", **kwargs) -> None:
    """Pulsante primario con la freccia a destra (dove ``icon_position`` non esiste la freccia resta a sinistra)."""
    try:
        st.button(label, key=key, type="primary", icon=icon, icon_position="right", **kwargs)
    except TypeError:
        st.button(label, key=key, type="primary", icon=icon, **kwargs)


def cta(label: str, step: str, *, disabled: bool = False, key: str = "cta", icon: str = ":material/arrow_forward:",
        on_click: Callable | None = None, args: tuple | None = None, width: str | None = None) -> None:
    extra = {"width": width} if width else {}
    with st.container(key=key):
        forward_button(label, key=f"{key}-btn", icon=icon, on_click=on_click or go,
                       args=(step,) if args is None else args, disabled=disabled, **extra)


def spacer() -> None:
    st.html('<div class="gx-space"></div>')


def guide(number: int, title: str, text: str) -> None:
    """Riquadro che apre un passo dell'area avanzata: a cosa serve e che cosa si può cambiare."""
    st.html(f'<div class="gx-guide"><div class="no">{number}</div><div><b>{html.escape(title)}</b>'
            f'<span>{html.escape(text)}</span></div></div>')


def skeleton(title: str, sub: str = "") -> str:
    """Segnaposto luminoso mostrato mentre l'app prepara i dati o l'algoritmo lavora."""
    return ('<div class="gx-skel"><div class="gx-skel-in"><div class="gx-orb"></div>'
            f'<b>{html.escape(title)}</b><span>{html.escape(sub)}</span></div></div>')
