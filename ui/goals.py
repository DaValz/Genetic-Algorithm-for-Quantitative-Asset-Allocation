"""Obiettivi del piano: linea del tempo visiva ed elenco modificabile."""
from __future__ import annotations

import html
import json
from datetime import date

import streamlit as st

from goalga.i18n import t, tn
from goalga.plan import MAX_HORIZON

from . import format as fmt
from .inputs import format_amount, parse_amount
from .state import GOAL_KINDS, new_goal
from .theme import RISK_SCALE

MAX_GOALS = 8
REPEAT_YEARS = 5          # durata iniziale (anni) quando un obiettivo diventa «ogni anno»


def goal_name(kind: str) -> str:
    return t(f"goal.kind.{kind}")


# ------------------------------------------------------------------ linea del tempo
def _tick_step(horizon: int) -> int:
    return 1 if horizon <= 6 else 2 if horizon <= 12 else 5 if horizon <= 40 else 10


def _label(goal: dict) -> str:
    text = fmt.eur_compact(goal["amount"])
    return text + (t("unit.per_year") if goal["end"] > goal["start"] else "")


def timeline_html(goals: list[dict]) -> str:
    """Linea del tempo da oggi all'ultimo obiettivo, con un indicatore per ogni obiettivo."""
    if not goals:
        return (f'<div class="gx-card" style="text-align:center;color:var(--mute)">{html.escape(t("goals.empty"))}</div>')
    horizon = max(5, max(int(g["end"]) for g in goals))

    def pct(year: float) -> float:
        return 100.0 * year / horizon

    ticks = list(range(_tick_step(horizon), horizon + 1, _tick_step(horizon)))
    if horizon not in ticks and horizon - ticks[-1] >= _tick_step(horizon) // 2 + 1:
        ticks.append(horizon)
    tick_html = f'<span class="gx-tl-tick" style="left:0%">{html.escape(t("goals.today"))}</span>' + "".join(
        f'<span class="gx-tl-tick" style="left:{pct(k):.2f}%">{html.escape(tn("unit.years", k) if k == ticks[-1] else str(k))}</span>'
        for k in ticks)

    # le etichette vicine vengono disposte su "corsie" a diversa altezza
    order = sorted(goals, key=lambda g: (g["start"] + g["end"]) / 2)
    last_end = [-1e9, -1e9, -1e9]
    parts, max_lane = [], 0
    for g in order:
        center = pct((g["start"] + g["end"]) / 2)
        width = 13.0
        lane = next((i for i, e in enumerate(last_end) if center - width / 2 >= e), int(min(range(3), key=last_end.__getitem__)))
        last_end[lane] = center + width / 2
        max_lane = max(max_lane, lane)
        color = RISK_SCALE[min(len(RISK_SCALE) - 1, int(pct(g["start"]) / 100 * (len(RISK_SCALE) - 1) + .5))]
        stem = 16 + 34 * lane
        if g["end"] > g["start"]:
            parts.append(f'<span class="gx-tl-span" style="left:{pct(g["start"]):.2f}%;width:{pct(g["end"]) - pct(g["start"]):.2f}%;--c:{color}"></span>')
        parts.append(
            f'<div class="gx-tl-pin" style="left:{center:.2f}%;--c:{color}"><span class="gx-tl-amt">{html.escape(_label(g))}</span>'
            f'<span class="gx-tl-stem" style="height:{stem}px"></span></div>')
        ends = [g["start"]] if g["start"] == g["end"] else [g["start"], g["end"]]
        parts.extend(f'<span class="gx-tl-dot" style="left:{pct(y):.2f}%;--c:{color}"></span>' for y in ends)
    height = 150 + 34 * max_lane
    summary = "; ".join(f"{goal_name(g['kind'])} {_label(g)} {_span_text(g['start'], g['end']).split(' · ')[0].lower()}"
                        for g in order)
    return (f'<div class="gx-tl" style="height:{height}px" role="img" aria-label="{html.escape(t("goals.aria", summary=summary))}">'
            f'<div class="gx-tl-track"></div><span class="gx-tl-now"></span>{"".join(parts)}{tick_html}</div>')


# ------------------------------------------------------------------ elenco modificabile
def _commit_amount(gid: int) -> None:
    ss = st.session_state
    value = parse_amount(ss.get(f"ga_{gid}"))
    goal = next((g for g in ss["goals"] if g["id"] == gid), None)
    ss[f"bad_ga_{gid}"] = value is None or value <= 0
    if goal is not None and not ss[f"bad_ga_{gid}"]:
        goal["amount"] = value
    if goal is not None:
        ss[f"ga_{gid}"] = format_amount(goal["amount"])


def _remove(gid: int) -> None:
    ss = st.session_state
    ss["goals"] = [g for g in ss["goals"] if g["id"] != gid]
    for key in (f"gm_{gid}", f"gw_{gid}", f"gy_{gid}", f"ga_{gid}", f"bad_ga_{gid}"):
        ss.pop(key, None)


def _add() -> None:
    ss = st.session_state
    kind = ss.get("add_goal")
    if kind and len(ss["goals"]) < MAX_GOALS:
        ss["goals"].append(new_goal(kind))
    ss["add_goal"] = None


def _span_text(start: int, end: int) -> str:
    now = date.today().year
    if end == start:
        return tn("goals.in_years", start, year=now + start)
    return t("goals.span", start=start, end=end, count=tn("unit.years", end - start + 1), y0=now + start, y1=now + end)


def _bounds() -> tuple[int, int]:
    """Primo e ultimo anno di calendario che i cursori possono scegliere (da 1 a ``MAX_HORIZON`` anni da oggi)."""
    now = date.today().year
    return now + 1, now + MAX_HORIZON


def live_texts() -> dict:
    """Frasi che il browser usa per aggiornare fumetto e intestazione mentre si trascina un cursore.

    Sono le stesse che scrive il server dopo il rilascio (stesse chiavi del catalogo, plurali compresi), calcolate per ogni
    durata possibile: lo script non deve conoscere né le lingue né le regole dei plurali. L'indice ``n - 1`` vale ``n`` anni.
    """
    now = date.today().year
    years = range(1, MAX_HORIZON + 1)
    return {
        "base": now,
        "cap": [tn("goals.bubble_in", n) for n in years],
        "one": [tn("goals.in_years", n, year=now + n) for n in years],
        "count": [tn("unit.years", n) for n in years],
        "span": t("goals.span", start="{start}", end="{end}", count="{count}", y0="{y0}", y1="{y1}"),
        "every": t("goals.every_year"),
    }


def _live_marker() -> str:
    """Segnaposto nascosto con i testi di ``live_texts`` in un attributo (virgolette singole: il JSON ha solo le doppie)."""
    raw = json.dumps(live_texts(), ensure_ascii=False, separators=(",", ":"))
    return f"<span data-gx-live='{raw.replace('&', '&amp;').replace(chr(39), '&#39;').replace('<', '&lt;')}' data-gx-hide></span>"


def _keep_range(gid: int) -> None:
    """Nell'intervallo «ogni anno» i due cursori non si sovrappongono mai: sovrapposti, quello in cima non si può spostare
    indietro e l'altro non si raggiunge più. Un obiettivo di un solo anno si ottiene spegnendo «Si ripete ogni anno»."""
    ss = st.session_state
    low, high = ss[f"gy_{gid}"]
    if low >= high:
        high = min(_bounds()[1], low + 1)
        ss[f"gy_{gid}"] = (high - 1, high)


def _year_widgets(goal: dict) -> bool:
    """Prepara i widget degli anni e dice se l'obiettivo si ripete ogni anno (slider con due estremità) o è una volta sola.

    I cursori scelgono **anni di calendario** (2034), non anni da oggi (8): il numero che segue il dito mentre si trascina è
    già l'anno. Il piano continua a contare gli anni da oggi (``goal["start"]``, ``goal["end"]``).

    Un obiettivo «una volta» ha un solo cursore: con un intervallo i due cursori coincidono e quello in cima, trascinato
    verso sinistra, non si muove (non può superare l'altro). Con «ogni anno» compare l'intervallo, già con le due
    estremità separate.
    """
    ss = st.session_state
    gid = goal["id"]
    now = date.today().year
    lo, hi = _bounds()
    mkey, wkey, ykey = f"gm_{gid}", f"gw_{gid}", f"gy_{gid}"
    start, end = int(goal["start"]), int(goal["end"])
    if mkey not in ss:
        ss[mkey] = end > start
    yearly = bool(ss[mkey])
    if yearly:
        ss.pop(wkey, None)
        if ykey not in ss:
            last = end if end > start else min(MAX_HORIZON, start + REPEAT_YEARS - 1)
            ss[ykey] = (now + min(start, last - 1), now + last)
        else:                                    # a cavallo d'anno gli estremi possono uscire dall'intervallo
            first, last = ss[ykey]
            ss[ykey] = (min(max(int(first), lo), hi - 1), min(max(int(last), lo + 1), hi))
    else:
        ss.pop(ykey, None)
        ss[wkey] = min(max(int(ss.get(wkey, now + start)), lo), hi)
    return yearly


def _goal_card(goal: dict) -> None:
    ss = st.session_state
    gid = goal["id"]
    icon, name = GOAL_KINDS[goal["kind"]][0], goal_name(goal["kind"])
    akey = f"ga_{gid}"
    yearly = _year_widgets(goal)
    lo, hi = _bounds()
    now = lo - 1
    if akey not in ss:
        ss[akey] = format_amount(goal["amount"])
    with st.container(key=f"goal-{gid}"):
        with st.container(key=f"ghead-{gid}"):
            head, remove = st.columns([1, .1], vertical_alignment="center")
            title = head.empty()
            remove.button(t("goals.remove"), key=f"rm-{gid}", type="tertiary", icon=":material/close:",
                          on_click=_remove, args=(gid,), help=t("goals.remove_help"))
        years_col, amount_col = st.columns([1.5, 1], vertical_alignment="bottom")
        with years_col:
            label = t("goals.years_label", name=name)
            if yearly:
                first, last = st.slider(label, lo, hi, key=f"gy_{gid}", label_visibility="collapsed", format="%d",
                                        on_change=_keep_range, args=(gid,))
                start, end = first - now, last - now
            else:
                start = end = st.slider(label, lo, hi, key=f"gw_{gid}", label_visibility="collapsed", format="%d") - now
        with amount_col:
            with st.container(key=f"gamt-{gid}"):
                st.text_input(t("goals.amount_label", name=name), key=akey, label_visibility="collapsed",
                              on_change=_commit_amount, args=(gid,), placeholder=fmt.eur(0))
        if ss.get(f"bad_ga_{gid}"):
            st.html(f'<div class="gx-note" style="color:var(--warn)">{html.escape(t("input.bad_amount"))}</div>')
        st.toggle(t("goals.repeat"), key=f"gm_{gid}")
    goal["start"], goal["end"] = int(start), int(end)
    every = f" · {html.escape(t('goals.every_year'))}" if goal["end"] > goal["start"] else ""
    title.html(f'<div class="gx-goal-title"><span class="gx-goal-ico"><span class="gx-ico">{icon}</span></span>'
               f'<div>{html.escape(name)}<div class="gx-goal-sub">{html.escape(_span_text(goal["start"], goal["end"]))}'
               f'{every}</div></div></div>')


def goals_editor() -> None:
    ss = st.session_state
    goals = ss["goals"]
    st.html(_live_marker())
    for goal in goals:
        _goal_card(goal)
    if len(goals) < MAX_GOALS:
        st.pills(t("goals.add"), list(GOAL_KINDS), key="add_goal", on_change=_add,
                 format_func=lambda k: f":material/{GOAL_KINDS[k][0]}: {goal_name(k)}", label_visibility="collapsed")
    st.html(f'<div class="gx-note">{html.escape(t("goals.hint"))}</div>')
