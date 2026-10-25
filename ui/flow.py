"""Percorso guidato: home, punto di partenza, obiettivi, riepilogo e router delle schermate."""
from __future__ import annotations

import html
from datetime import date

import streamlit as st

from goalga.data import DataError
from goalga.i18n import LOCALE_TAGS, current, t, tn
from goalga.universe import universe_size

from . import format as fmt
from . import theme
from .components import back, chrome, cta, head, spacer
from .goals import goal_name, goals_editor, timeline_html
from .inputs import amount_field
from .state import begin, build_plan, go

_COUNT_UP = """<script>(function(){
  /* nel codice non si usa il simbolo di minore: DOMPurify scarta gli script che lo contengono */
  var LOC="%s", tries=0;
  var reduce=window.matchMedia&&window.matchMedia("(prefers-reduced-motion: reduce)").matches, nf=null;
  try{nf=new Intl.NumberFormat(LOC,{useGrouping:"always"});}catch(e){}
  function f(n){return nf?nf.format(n):String(n);}
  function start(){
    var els=[].slice.call(document.querySelectorAll(".gx-count[data-to]:not([data-run])"));
    if(!els.length){if(60>tries++){window.setTimeout(start,50);}return;}
    els.forEach(function(el,i){
      el.setAttribute("data-run","1");
      if(reduce){return;}
      var to=parseInt(el.getAttribute("data-to"),10), fin=el.getAttribute("data-final");
      el.textContent=f(0);
      window.setTimeout(function(){
        var t0=null;
        function step(ts){
          if(t0===null){t0=ts;}
          var p=Math.min(1,(ts-t0)/1500), e=1-Math.pow(1-p,4);
          el.textContent=f(Math.round(to*e));
          if(1>p){window.requestAnimationFrame(step);}else{el.textContent=fin;}
        }
        window.requestAnimationFrame(step);
      },420+i*150);
    });
  }
  start();
})();</script>"""


def approx_floor(n: int) -> int:
    """Arrotonda per difetto a due cifre significative (3.478 -> 3.400): il «+» che segue resta sempre vero."""
    n = int(n)
    step = 10 ** max(0, len(str(n)) - 2)
    return n // step * step


def _feats_html() -> tuple[str, str]:
    """Tre numeri in evidenza che «salgono» all'apertura (il testo finale è già nell'HTML se manca JavaScript)."""
    items = [(1000, t("welcome.feat1")), (100, t("welcome.feat2")), (approx_floor(universe_size()), t("welcome.feat3"))]
    cards = "".join(
        f'<div class="gx-feat" style="--d:{.4 + i * .15:.2f}s"><b><span class="gx-count" data-to="{n}" '
        f'data-final="{html.escape(fmt.number(n))}">{html.escape(fmt.number(n))}</span>+</b>'
        f"<span>{html.escape(label)}</span></div>" for i, (n, label) in enumerate(items))
    return f'<div class="gx-feats">{cards}</div>', _COUNT_UP % LOCALE_TAGS[current()]


def welcome() -> None:
    chrome("welcome")
    from .stage import ambient
    ambient()
    with st.container(key="welcome"):
        head(t("welcome.eyebrow"), t("welcome.title"), t("welcome.sub"), big=True)
        spacer()
        cta(t("welcome.cta"), "start", key="cta-home", on_click=begin, args=())
        cards, script = _feats_html()
        try:
            st.html(cards + script, unsafe_allow_javascript=True)
        except TypeError:  # versioni di Streamlit che non eseguono JavaScript in st.html
            st.html(cards)


def start() -> None:
    chrome("start")
    back("welcome")
    head(t("start.eyebrow"), t("start.title"), t("start.sub"))
    ss = st.session_state
    note = ss.get("edit_note")
    if note and ss.get("editing_portfolio"):
        text = t("acct.edit.note_" + str(note["source"]), name=note["name"], value=fmt.eur(note["value"]))
        st.html(f'<div class="gx-note">{html.escape(text)}</div>')
    amount_field("w0", t("start.have"), [10_000, 25_000, 50_000, 100_000, 250_000, 500_000, 1_000_000])
    spacer()
    amount_field("contribution", t("start.add"), [0, 1_200, 3_000, 6_000, 12_000, 24_000],
                 hint=t("start.per_month", amount=fmt.eur(ss["contribution"] / 12)) if ss["contribution"] > 0 else "")
    empty = ss["w0"] <= 0 and ss["contribution"] <= 0
    if empty:
        st.html(f'<div class="gx-note" style="color:var(--warn)">{html.escape(t("core.plan.empty"))}</div>')
    spacer()
    cta(t("common.continue"), "goals", disabled=empty)


def goals() -> None:
    chrome("goals")
    back("start")
    head(t("goals.eyebrow"), t("goals.title"), t("goals.sub"))
    timeline = st.empty()
    goals_editor()
    timeline.html(timeline_html(st.session_state["goals"]))
    spacer()
    cta(t("common.continue"), "risk", disabled=not st.session_state["goals"])


def _receipt(plan) -> str:
    ss = st.session_state
    now = date.today().year
    per_year = t("unit.per_year")
    rows = [
        (t("start.have"), fmt.eur(plan.w0), ""),
        (t("start.add"), fmt.eur(plan.contribution), t("start.per_month", amount=fmt.eur(plan.contribution / 12))),
    ]
    goal_lines = []
    for g in ss["goals"]:
        name = goal_name(g["kind"])
        when = (tn("review.in_years", g["start"]) if g["end"] == g["start"]
                else t("review.span", start=g["start"], end=g["end"]))
        goal_lines.append(f"{html.escape(name)} · {fmt.eur(g['amount'])}{per_year if g['end'] > g['start'] else ''} "
                          f"<small>{html.escape(when)}</small>")
    rows.append((t("review.goals"), "".join(f"<div>{line}</div>" for line in goal_lines), ""))
    rows.append((t("review.horizon"), tn("unit.years", plan.horizon), t("review.until", year=now + plan.horizon)))
    if plan.inflation > 0:
        rows.append((t("review.inflation"), html.escape(t("review.inflation_value", pct=fmt.pct(plan.inflation, 1))),
                     t("review.inflation_sub")))
    else:
        rows.append((t("review.inflation"), html.escape(t("review.inflation_none")), t("review.inflation_none_sub")))
    previews = (ss.get("risk_previews") or {}).get("items") or []
    chosen = next((p for p in previews if p.key == ss.get("risk")), None)
    risk_sub = (t("review.risk_estimate", n=min(99, round(chosen.pr * 100))) if chosen is not None else "")
    rows.append((t("review.risk"), html.escape(t(f"risk.{ss.get('risk', 'balanced')}.name")), risk_sub))
    body = "".join(
        f'<div class="r"><span class="k">{html.escape(k)}</span><span class="v">{v}'
        f'{f"<small>{html.escape(s)}</small>" if s else ""}</span></div>' for k, v, s in rows)
    return f'<div class="gx-card gx-rcpt">{body}</div>'


def _difficulty_card(plan) -> str:
    """Quanto è ambizioso il piano rispetto ai rendimenti attesi dei portafogli."""
    from goalga.problem import required_return

    from . import market_tab

    try:
        market = market_tab.market_for().market
        required = required_return(plan.flows())
    except (ValueError, DataError):
        return ""
    if required is None:
        return ""
    lo, hi = float(market.compound_returns.min()), float(market.compound_returns.max())
    pos = 50.0 if hi <= lo else min(100.0, max(0.0, (required - lo) / (hi - lo) * 100.0))
    if required <= lo:
        tone, key = "ok", "review.gauge.easy"
    elif required <= lo + 0.45 * (hi - lo):
        tone, key = "ok", "review.gauge.balanced"
    elif required <= hi:
        tone, key = "warn", "review.gauge.ambitious"
    else:
        tone, key = "warn", "review.gauge.very_ambitious"
    return (f'<div class="gx-card gx-gauge {tone}"><div class="top"><span class="k">{html.escape(t("review.gauge.title"))}</span>'
            f'<b>{html.escape(t("review.gauge.per_year", pct=fmt.pct(required, 1)))}</b></div>'
            f'<div class="track"><i style="left:{pos:.1f}%"></i></div>'
            f'<div class="ends"><span>{html.escape(t("review.gauge.low", pct=fmt.pct(lo, 1)))}</span>'
            f'<span>{html.escape(t("review.gauge.high", pct=fmt.pct(hi, 1)))}</span></div>'
            f'<div class="msg">{html.escape(t(key))}</div></div>')


def _settings_card(chips: str) -> None:
    """Come lavora l'app: in automatico, oppure con le scelte fatte nell'area avanzata (le pillole dicono quali)."""
    if chips:
        title, desc = t("review.auto.title_adv"), t("review.auto.desc_adv")
    else:
        title, desc = t("review.auto.title_auto"), t("review.auto.desc_auto")
    with st.container(key="card-auto"):
        st.html(f'<div class="gx-auto"><div class="ico">✦</div><div><b>{html.escape(title)}</b>'
                f'<span>{html.escape(desc)}</span></div></div>{chips}')


def _actions(errors: list[str], customized: bool) -> None:
    """Sotto il riepilogo, a tutta larghezza: trovare la strategia e, con lo stesso peso, personalizzare le impostazioni."""
    from .lab import reset_lab

    with st.container(key="review-actions"):
        cta(t("review.cta"), "evolve", disabled=bool(errors), width="stretch")
        st.button(t("review.adv.edit" if customized else "review.adv.use"), key="to-lab", icon=":material/tune:",
                  on_click=go, args=("lab",), width="stretch")
    if customized:
        st.button(t("lab.reset"), key="review-reset", type="tertiary", icon=":material/restart_alt:", on_click=reset_lab)


def review() -> None:
    from .lab import changes_html

    chrome("review")
    back("risk")
    head(t("review.eyebrow"), t("review.title"), t("review.sub"))
    plan, errors = build_plan()
    st.html(_receipt(plan))
    if not errors and (card := _difficulty_card(plan)):
        st.html(card)
    chips = changes_html(st.session_state) if st.session_state.get("use_advanced") else ""
    _settings_card(chips)
    for message in errors:
        st.warning(message, icon=":material/error_outline:")
    spacer()
    _actions(errors, customized=bool(chips))


# ------------------------------------------------------------------ router
def render() -> None:
    ss = st.session_state
    step = ss["step"]
    theme.inject(step, ss.get("lang", "en"))
    theme.scroll_top(step)
    if step == "welcome":
        welcome()
    elif step == "start":
        start()
    elif step == "goals":
        goals()
    elif step == "risk":
        from . import risk
        risk.render()
    elif step == "review":
        review()
    elif step == "evolve":
        from . import engine
        engine.render()
    elif step == "plan":
        from . import result
        result.render()
    elif step == "holdings":
        from . import holdings
        holdings.render()
    elif step == "lab":
        from . import lab
        lab.render()
    elif step == "account":
        from . import account
        account.render()
    else:  # stato non riconosciuto: riparte dall'inizio
        ss["step"] = "welcome"
        st.rerun()
