"""Tema grafico: palette, CSS dell'interfaccia e stile comune dei grafici Plotly."""
from __future__ import annotations

import hashlib
import html
import json
import os
from datetime import date
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from . import format as fmt

ASSETS = Path(__file__).resolve().parent / "assets"
BRAND = os.environ.get("GOALGA_BRAND", "GoalGA")

INK = "#F4F6FB"
MUTED = "#A4ACBD"
FAINT = "#6C7589"
ACCENT = "#818CF8"
ACCENT_SOFT = "rgba(129,140,248,0.20)"
GRID = "rgba(255,255,255,0.07)"
GOOD = "#34D399"
WARN = "#FBBF24"
BAD = "#FB7185"
FONT = ('Inter, system-ui, -apple-system, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", "Noto Sans CJK SC", '
        '"Hiragino Sans GB", sans-serif')

# scala neutra dal difensivo (verde acqua) all'aggressivo (arancio)
RISK_SCALE = ["#2DD4BF", "#38BDF8", "#60A5FA", "#818CF8", "#A78BFA", "#C084FC", "#E879F9", "#F472B6", "#FB923C"]
ASSET_COLORS = [
    "#818CF8", "#2DD4BF", "#F472B6", "#FBBF24", "#38BDF8", "#A78BFA", "#34D399", "#FB923C", "#E879F9", "#60A5FA",
    "#FB7185", "#A3E635", "#22D3EE", "#C084FC", "#F59E0B", "#4ADE80", "#F87171", "#67E8F9", "#D946EF", "#94A3B8",
]
# luce ambientale (sfumature di sfondo) e larghezza massima per schermata
_SCREEN = {
    "welcome": ("760px", "rgba(99,102,241,.28)", "rgba(34,211,238,.14)"),
    "start": ("720px", "rgba(99,102,241,.22)", "rgba(34,211,238,.10)"),
    "goals": ("760px", "rgba(168,85,247,.20)", "rgba(244,114,182,.11)"),
    "risk": ("900px", "rgba(34,211,238,.17)", "rgba(99,102,241,.14)"),
    "review": ("720px", "rgba(45,212,191,.15)", "rgba(99,102,241,.16)"),
    "evolve": ("1120px", "rgba(79,70,229,.28)", "rgba(168,85,247,.13)"),
    "plan": ("1060px", "rgba(99,102,241,.22)", "rgba(45,212,191,.12)"),
    "holdings": ("1060px", "rgba(99,102,241,.2)", "rgba(244,114,182,.1)"),
    "account": ("920px", "rgba(45,212,191,.14)", "rgba(99,102,241,.16)"),
    "lab": ("1180px", "rgba(99,102,241,.16)", "rgba(34,211,238,.08)"),
}


def hex_rgba(color: str, alpha: float) -> str:
    c = color.lstrip("#")
    return f"rgba({int(c[0:2], 16)},{int(c[2:4], 16)},{int(c[4:6], 16)},{alpha})"


def risk_color(level: int, n: int = 9) -> str:
    idx = round((level - 1) / max(n - 1, 1) * (len(RISK_SCALE) - 1))
    return RISK_SCALE[idx]


def asset_color(i: int) -> str:
    return ASSET_COLORS[i % len(ASSET_COLORS)]


def css() -> str:
    return (ASSETS / "theme.css").read_text(encoding="utf-8")


# prefissi dei pulsanti che cambiano schermata: al clic la pagina sfuma subito (vedi assets/behaviors.js)
NAV_KEYS = ("cta", "back-", "to-lab", "lab-reset", "to-holdings", "plan-edit", "plan-lab", "plan-empty", "wi-btn-", "err-back",
            "acct-btn", "save-guest", "save-open", "pf-comp-", "pf-edit-", "pf-new", "signout")


def behaviors() -> str:
    """Comportamenti dell'interfaccia lato browser (transizioni, selezione degli importi, fumetto degli anni).

    ``__VERSION__`` è l'impronta del testo: se la scheda del browser ha già una versione diversa dello script (app aggiornata
    mentre era aperta) quella vecchia si disattiva e la nuova prende il suo posto.
    """
    source = (ASSETS / "behaviors.js").read_text(encoding="utf-8").replace("__NAV__", json.dumps(list(NAV_KEYS)))
    return source.replace("__VERSION__", hashlib.sha1(source.encode("utf-8")).hexdigest()[:10])


def inject(screen: str, lang: str = "en") -> None:
    """Applica il tema; ``screen`` regola larghezza e sfumature di sfondo, ``lang`` la lingua del documento."""
    maxw, glow1, glow2 = _SCREEN.get(screen, _SCREEN["start"])
    st.html(f"<style>{css()}:root{{--maxw:{maxw};--glow1:{glow1};--glow2:{glow2};}}</style>")
    code = (f'var d=document.documentElement;d.lang="{html.escape(lang)}";d.setAttribute("data-gx-year","{date.today().year}");'
            f"{behaviors()}")
    script = f'<span data-lang="{html.escape(lang)}" data-gx-hide></span><script>{code}</script>'
    try:
        st.html(script, unsafe_allow_javascript=True)
    except TypeError:  # versioni di Streamlit che non eseguono JavaScript in st.html
        pass


def chrome(index: int, total: int) -> None:
    """Barra superiore fissa: marchio e avanzamento (index = passo corrente da 1, 0 = nessuno)."""
    bars = "".join(f'<i class="{"on" if k < index - 1 else ("cur on" if k == index - 1 else "")}"></i>'
                   for k in range(total))
    progress = (f'<div class="gx-progress" role="img" aria-label="{index} / {total}">{bars}</div>'
                if index else "<span></span>")
    st.html(f'<div class="gx-top"><div class="gx-brand"><span class="gx-logo"></span>'
            f'<span class="gx-brand-name">{html.escape(BRAND)}</span></div>{progress}<span class="gx-top-fill"></span></div>')


def scroll_top(key: str) -> None:
    """Riporta la pagina in cima a ogni cambio di schermata (Streamlit conserva lo scorrimento precedente)."""
    script = ('<span data-scroll="%s"></span><script>(function(){var m=document.querySelector(\'[data-testid="stMain"]\');'
              'if(m){m.scrollTo(0,0);}else{window.scrollTo(0,0);}})();</script>') % html.escape(key)
    try:
        st.html(script, unsafe_allow_javascript=True)
    except TypeError:  # versioni di Streamlit che non eseguono JavaScript in st.html
        pass


def style(fig: go.Figure, height: int = 360, legend: bool = True, legend_y: float = 1.02, **layout) -> go.Figure:
    """Applica lo stile minimale comune a tutti i grafici (sfondo trasparente, griglia appena visibile)."""
    layout.setdefault("hovermode", "x unified")
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=36, b=14),
        font=dict(family=FONT, size=13, color=MUTED),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        separators=fmt.plotly_separators(),
        hoverlabel=dict(font=dict(family=FONT, size=12, color=INK), bgcolor="#141826", bordercolor="rgba(255,255,255,.14)"),
        showlegend=legend,
        legend=dict(orientation="h", yanchor="bottom", y=legend_y, xanchor="left", x=0, font=dict(size=12, color=MUTED)),
        **layout,
    )
    fig.update_xaxes(showgrid=False, zeroline=False, linecolor=GRID, ticks="outside", tickcolor=GRID, automargin=True,
                     tickfont=dict(color=FAINT), title_font=dict(color=FAINT, size=12))
    fig.update_yaxes(gridcolor=GRID, zeroline=False, ticks="", automargin=True, tickfont=dict(color=FAINT),
                     title_font=dict(color=FAINT, size=12))
    return fig
