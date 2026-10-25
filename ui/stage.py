"""Scena dell'algoritmo: animazioni in canvas (sfondo della home e replay dell'evoluzione reale)."""
from __future__ import annotations

import html
import json

import streamlit as st

from goalga.i18n import LOCALE_TAGS, current, t, tn
from goalga.plan import Plan, group_goals

from . import format as fmt
from .theme import ASSETS

AMBIENT_SEED = 7


def _read(name: str) -> str:
    return (ASSETS / name).read_text(encoding="utf-8")


def _page(cfg: dict, body: str) -> str:
    """Pagina HTML autonoma (iframe): stile, configurazione serializzata e script di animazione."""
    cfg = {**cfg, "locale": LOCALE_TAGS[current()], "pctSuffix": fmt.spec().pct}
    data = json.dumps(cfg, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    return (f'<!doctype html><html lang="{html.escape(current())}"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<style>{_read("stage.css")}</style></head><body class="{cfg["mode"]}">{body}'
            f'<script>window.GX={data};</script><script>{_read("evolve.js")}</script></body></html>')


def embed(doc: str, height: int) -> None:
    """Incorpora una pagina HTML autonoma (``st.iframe`` se disponibile, altrimenti ``components.html``)."""
    if hasattr(st, "iframe"):
        st.iframe(doc, height=height)
    else:  # versioni di Streamlit precedenti a st.iframe
        import streamlit.components.v1 as components
        components.html(doc, height=height)


# ------------------------------------------------------------------ sfondo della home
def ambient_html() -> str:
    body = '<div id="root"><div class="cv-wrap"><canvas id="cv" aria-hidden="true"></canvas></div></div>'
    return _page({"mode": "ambient", "seed": AMBIENT_SEED, "duration": 15000}, body)


def ambient() -> None:
    """Evoluzione decorativa a tutto schermo dietro la home."""
    with st.container(key="bg"):
        embed(ambient_html(), 600)


# ------------------------------------------------------------------ replay dell'evoluzione
def replay_duration_ms(trace: dict) -> int:
    """Durata della riproduzione: abbastanza lunga da seguire l'evoluzione, mai noiosa."""
    return int(min(11_500, max(8_500, 6_500 + 40 * trace["F"])))


def goal_markers(plan: Plan) -> list[dict]:
    """Cartellini degli obiettivi sull'asse degli anni (anni consecutivi uguali sono raggruppati)."""
    out = []
    for start, end, amount in group_goals(plan.goals):
        out.append({"y": start, "label": fmt.eur_compact(amount) + (t("unit.per_year") if end > start else "")})
        if end > start:
            out.append({"y": end, "label": ""})
    return out


def stage_html(trace: dict, plan: Plan, replay_ms: int | None = None, evaluated: int | None = None) -> str:
    """Pagina del replay: statistiche in alto, filamenti delle strategie, DNA del campione e narrazione.

    Con ``evaluated`` (asset valutati dall'algoritmo) la prima frase della narrazione lo dice.
    """
    sims = fmt.number(trace["n_scenarios"], 0)
    phases = [t(f"stage.phase{i}") for i in range(5)]
    if evaluated:
        phases[0] = t("stage.phase0_universe", n=fmt.number(evaluated))
    text = {
        "riskHigh": t("stage.risk_high"), "riskLow": t("stage.risk_low"), "risk": t("stage.risk"),
        "today": t("stage.today"), "years": t("stage.years"), "of": t("stage.of"), "dna": t("stage.dna"),
        "aria": t("stage.aria"), "cap": t("stage.cap"), "done": t("stage.done"),
        "phases": phases,
        # «25 anni», «22 года»…: la forma plurale giusta per ogni possibile etichetta dell'asse
        "yearLabels": {str(n): tn("unit.years", n) for n in range(1, int(trace["T"]) + 1)},
    }
    cfg = {"mode": "replay", "data": trace, "goals": goal_markers(plan), "target": plan.pr_target,
           "cap": trace.get("cap"), "nScenarios": trace["n_scenarios"],
           "duration": replay_ms or replay_duration_ms(trace), "text": text}
    threshold = html.escape(t("stage.threshold", pct=fmt.pct(plan.pr_target, 0)), quote=True)
    body = (
        '<div id="root"><div class="stats">'
        f'<div class="stat"><div class="k">{html.escape(t("stage.gen"))}</div><div class="v" id="v-gen">1</div>'
        '<div class="s" id="s-gen"></div></div>'
        f'<div class="stat"><div class="k">{html.escape(t("stage.sims"))}</div><div class="v" id="v-sims">0</div>'
        f'<div class="s">{html.escape(t("stage.sims_per", n=sims))}</div></div>'
        f'<div class="stat hl" id="stat-pr"><div class="k">{html.escape(t("stage.prob"))}</div>'
        f'<div class="v" id="v-pr">0%</div><div class="bar"><i id="bar-pr"></i><b id="bar-target" title="{threshold}"></b></div></div>'
        f'<div class="stat"><div class="k">{html.escape(t("stage.worst"))}</div><div class="v" id="v-irr">—</div>'
        f'<div class="s">{html.escape(t("stage.worst_sub"))}</div></div></div>'
        '<div class="cv-wrap">'
        f'<canvas id="cv" role="img" aria-label="{html.escape(t("stage.aria"), quote=True)}"></canvas></div>'
        '<div class="foot"><div class="narr" id="narr" aria-live="polite"></div></div></div>')
    return _page(cfg, body)
