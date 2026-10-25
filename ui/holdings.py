"""Pagina «Composizione»: di quali asset è fatto il portafoglio, anno per anno."""
from __future__ import annotations

import html
from datetime import date

import pandas as pd
import streamlit as st

from goalga.i18n import t
from goalga.universe import FUND_CATEGORIES

from . import classes
from . import format as fmt
from .charts import CATEGORY_COLORS
from .components import chrome, head, spacer
from .state import ResultBundle
from .theme import hex_rgba, risk_color

MIN_WEIGHT = 0.0005


def _phases(path) -> list[tuple[int, int, int]]:
    """Anni consecutivi con lo stesso portafoglio: ``[(primo anno, ultimo anno, livello)]``."""
    out, start = [], 0
    for i in range(1, len(path) + 1):
        if i == len(path) or path[i] != path[start]:
            out.append((start + 1, i, int(path[start])))
            start = i
    return out


def _display_name(ticker: str, names: dict[str, str]) -> str:
    return str(names.get(ticker) or ticker)


def _palette(comp: pd.DataFrame) -> dict[str, str]:
    """Un colore per categoria (classe del fondo; verde per le azioni singole): ciambella, elenco e tabella concordano."""
    return {a: CATEGORY_COLORS.get(classes.category_key(a), CATEGORY_COLORS["other"]) for a in comp.columns}


def _phase_strip(path, comp: pd.DataFrame, mapping: dict[str, str], now: int) -> None:
    cards = []
    for first, last, level in _phases(path):
        row = comp.loc[first]
        equity = sum(w for a, w in row.items() if mapping.get(a) == "equity")
        years = f"{now + first - 1}" if first == last else f"{now + first - 1}–{now + last - 1}"
        cards.append(
            f'<div class="gx-phase" style="--c:{risk_color(level)}"><span class="y">{html.escape(years)}</span>'
            f'<b>P{level}</b><span class="s">{html.escape(t("holdings.equity_share", pct=fmt.pct(equity, 0)))}</span></div>')
    st.html(f'<div class="gx-phases">{"".join(cards)}</div>')


def donut_html(weights: pd.Series, colors: dict[str, str], level: int) -> str:
    """Ciambella in puro CSS (``conic-gradient``): leggera, nitida a ogni larghezza e senza canvas da ritagliare."""
    total = float(weights.sum()) or 1.0
    stops, start = [], 0.0
    for ticker, w in weights.items():
        end = start + float(w) / total * 100
        stops.append(f"{colors[ticker]} {start:.2f}% {max(start, end - 0.5):.2f}%, #05060b {max(start, end - 0.5):.2f}% {end:.2f}%")
        start = end
    return (f'<div class="gx-donut" aria-hidden="true" style="background:conic-gradient({", ".join(stops)})">'
            f'<div class="in"><b>P{level}</b></div></div>')


def holdings_html(weights: pd.Series, names: dict[str, str], mapping: dict[str, str], colors: dict[str, str]) -> str:
    """Elenco degli asset dell'anno, raggruppati per categoria: nome, ticker, settore o classe e peso con barra."""
    top = float(weights.max()) or 1.0
    groups: dict[str, list[tuple[str, float]]] = {}
    for ticker, w in weights.items():
        groups.setdefault(classes.category_key(str(ticker)), []).append((str(ticker), float(w)))
    order = [k for k in (*FUND_CATEGORIES, "stocks", "other") if k in groups]
    blocks = []
    for key in order:
        members = groups[key]
        rows = []
        small = " sm" if key == "stocks" else ""
        for ticker, w in members:
            label = _display_name(ticker, names)
            sub = f"{ticker} · {classes.category_label(ticker)}"
            rows.append(
                f'<div class="gx-hrow{small}" style="--c:{colors[ticker]}"><span class="dot"></span>'
                f'<div class="nm"><b title="{html.escape(label)}">{html.escape(label)}</b><span>{html.escape(sub)}</span></div>'
                f'<div class="w"><b>{fmt.pct(w, 1)}</b><i style="--w:{w / top * 100:.1f}%"></i></div></div>')
        total = sum(w for _, w in members)
        title = t(f"cat.{key}") + (f" · {len(members)}" if key == "stocks" else "")
        blocks.append(f'<div class="gx-hgroup" style="--c:{colors[members[0][0]]}"><span>{html.escape(title)}</span>'
                      f'<b>{fmt.pct(total, 0)}</b></div>{"".join(rows)}')
    return f'<div class="gx-hlist">{"".join(blocks)}</div>'


def _delta_chips(prev: pd.Series, new: pd.Series, names: dict[str, str]) -> str:
    diff = (new - prev).sort_values(key=lambda s: -s.abs())
    chips = []
    for ticker, delta in diff.items():
        if abs(delta) < 0.005:
            continue
        tone = "up" if delta > 0 else "down"
        chips.append(f'<span class="gx-chip {tone}" title="{html.escape(_display_name(ticker, names))}">'
                     f'<b>{"+" if delta > 0 else "−"}{fmt.number(abs(delta) * 100, 0)} {html.escape(t("unit.pp"))}</b> '
                     f'{html.escape(ticker)}</span>')
    return f'<div class="gx-chips">{"".join(chips[:10])}</div>' if chips else ""


def _ordered(weights: pd.Series) -> pd.Series:
    """Pesi ordinati per categoria (come nell'elenco) e, dentro la categoria, dal più pesante."""
    order = {k: i for i, k in enumerate((*FUND_CATEGORIES, "stocks", "other"))}
    frame = pd.DataFrame({"w": weights, "g": [order.get(classes.category_key(str(a)), len(order)) for a in weights.index]})
    return frame.sort_values(["g", "w"], ascending=[True, False])["w"]


@st.fragment
def _explorer(comp: pd.DataFrame, path, names: dict[str, str], mapping: dict[str, str], now: int,
              colors: dict[str, str]) -> None:
    horizon = len(path)
    year = st.select_slider(t("holdings.pick_year"), options=list(range(1, horizon + 1)), key=f"hold_year_{horizon}",
                            format_func=lambda y: str(now + y - 1), label_visibility="collapsed")
    level = int(path[year - 1])
    row = comp.loc[year]
    weights = _ordered(row[row > MIN_WEIGHT])
    equity = sum(w for a, w in row.items() if mapping.get(a) == "equity")
    st.html(f'<div class="gx-sec" style="margin-top:.6rem"><h3>{html.escape(t("holdings.in_year", cal=now + year - 1, n=year))}'
            f' · P{level}</h3><p>{html.escape(t("holdings.equity_share", pct=fmt.pct(equity, 0)))}</p></div>')
    st.html(f'<div class="gx-hold">{donut_html(weights, colors, level)}{holdings_html(weights, names, mapping, colors)}</div>')
    nxt = next((y for y in range(year + 1, horizon + 1) if path[y - 1] != path[year - 1]), None)
    if nxt is None:
        st.html(f'<div class="gx-note">{html.escape(t("holdings.no_change"))}</div>')
    else:
        st.html(f'<div class="gx-note"><b>{html.escape(t("holdings.next", year=now + nxt - 1, a=level, b=int(path[nxt - 1])))}</b></div>')
        st.html(_delta_chips(row, comp.loc[nxt], names))


def heatmap_html(comp: pd.DataFrame, names: dict[str, str], now: int, colors: dict[str, str] | None = None,
                 max_assets: int = 14) -> str:
    """Tabella anni × asset con l'intensità del colore proporzionale al peso (si scorre se è molto lunga).

    I fondi sono colonne separate (i più pesanti per primi); le azioni singole, tutte piccole, sono una sola colonna
    (il dettaglio titolo per titolo è nell'elenco dell'anno e nel CSV).
    """
    colors = colors or _palette(comp)
    stock_cols = [a for a in comp.columns if classes.category_key(str(a)) == "stocks"]
    order = comp.drop(columns=stock_cols).max().sort_values(ascending=False)
    order = order[order > MIN_WEIGHT].index.tolist()
    shown, rest = order[:max_assets], order[max_assets:]
    stocks_color = CATEGORY_COLORS["stocks"]
    show_stocks = bool(stock_cols) and float(comp[stock_cols].sum(axis=1).max()) > MIN_WEIGHT
    head_cells = "".join(
        f'<th title="{html.escape(_display_name(a, names))}"><span style="--c:{colors[a]}"></span>{html.escape(a)}</th>'
        for a in shown)
    if show_stocks:
        head_cells += f'<th><span style="--c:{stocks_color}"></span>{html.escape(t("cat.stocks"))}</th>'
    if rest:
        head_cells += f'<th>{html.escape(t("holdings.others"))}</th>'
    rows = []
    for year in comp.index:
        cells = []
        for a in shown:
            w = float(comp.loc[year, a])
            bg = f"background:{hex_rgba(colors[a], min(0.92, 0.06 + w * 1.1))}" if w > MIN_WEIGHT else ""
            cells.append(f'<td style="{bg}">{fmt.number(w * 100, 0) if w > MIN_WEIGHT else ""}</td>')
        if show_stocks:
            w = float(comp.loc[year, stock_cols].sum())
            bg = f"background:{hex_rgba(stocks_color, min(0.92, 0.06 + w * 1.1))}" if w > MIN_WEIGHT else ""
            cells.append(f'<td style="{bg}">{fmt.number(w * 100, 0) if w > MIN_WEIGHT else ""}</td>')
        if rest:
            other = float(comp.loc[year, rest].sum())
            cells.append(f"<td>{fmt.number(other * 100, 0) if other > MIN_WEIGHT else ''}</td>")
        rows.append(f'<tr><th scope="row">{now + int(year) - 1}</th>{"".join(cells)}</tr>')
    return (f'<div class="gx-heat" role="region" tabindex="0" aria-label="{html.escape(t("holdings.heat_title"))}">'
            f'<table><thead><tr><th>{html.escape(t("holdings.heat_year"))}</th>{head_cells}</tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></div>')


def _saved_source(pid: int):
    """Composizione di un portafoglio salvato (dall'archivio): ``(composizione, percorso, nomi, anno base)``."""
    from . import account

    me, service = account.user(), account.svc()
    if not me or not service:
        return None
    try:
        pf = service.get_portfolio(me["id"], pid)
    except Exception:
        return None
    res = service.current_version(pf.id).result
    path = [int(x) for x in res["path"]]
    comp = pd.DataFrame([res["levels"][p - 1] for p in path], columns=res["tickers"],
                        index=pd.RangeIndex(1, len(path) + 1, name="Anno"))
    base = (pf.start_date.year if pf.start_date else date.today().year) + int(res.get("anchor", 0))
    return comp, path, dict(res.get("names") or {}), base


def _leave(pid) -> None:
    ss = st.session_state
    ss.pop("holdings_pf", None)
    ss["step"] = "account" if pid else "plan"


def render() -> None:
    ss = st.session_state
    chrome("holdings")
    pid = ss.get("holdings_pf")
    st.button(t("holdings.back_account") if pid else t("holdings.back_plan"), key="back-holdings", type="tertiary",
              icon=":material/arrow_back:", on_click=_leave, args=(pid,))
    if pid:
        source = _saved_source(pid)
        if source is None:
            st.html(f'<div class="gx-card" style="text-align:center">{html.escape(t("acct.err.not_found"))}</div>')
            return
        comp, path, names, now = source
    else:
        run: ResultBundle | None = ss.get("result")
        if run is None:
            st.html(f'<div class="gx-card" style="text-align:center">{html.escape(t("plan.empty"))}</div>')
            return
        comp, path = run.report.composition, run.report.path
        names = dict(run.data.names) if run.data is not None else {}
        now = date.today().year
    head(t("holdings.eyebrow"), t("holdings.title"), t("holdings.sub"))
    mapping = classes.asset_class_map(list(comp.columns))
    colors = _palette(comp)
    _phase_strip(path, comp, mapping, now)
    _explorer(comp, path, names, mapping, now, colors)
    st.html(f'<div class="gx-sec"><h3>{html.escape(t("holdings.heat_title"))}</h3>'
            f'<p>{html.escape(t("holdings.heat_text"))}</p></div>')
    st.html(heatmap_html(comp, names, now, colors))
    spacer()
    export = comp.copy()
    export.index = [now + int(y) - 1 for y in export.index]
    export.index.name = t("holdings.heat_year")
    export = (export * 100).round(2)
    st.download_button(t("holdings.download"), export.to_csv().encode("utf-8-sig"), "goalga_composition.csv",
                       mime="text/csv", icon=":material/download:")
    st.html(f'<div class="gx-note">{html.escape(t("holdings.note"))}</div>')


