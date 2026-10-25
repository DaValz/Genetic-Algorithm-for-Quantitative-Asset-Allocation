"""Test dei componenti dell'interfaccia che non richiedono Streamlit in esecuzione."""
import json
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from goalga import GAConfig, GoalProblem, i18n, run_ga
from goalga.plan import PAPER_GOALS_CASE_1, Plan, group_goals
from goalga.trace import EvolutionTrace
from ui import classes, stage
from ui import format as fmt
from ui.flow import _COUNT_UP, _feats_html, approx_floor
from ui.goals import timeline_html
from ui.inputs import confidence_dots, format_amount, parse_amount
from ui.theme import ASSETS, NAV_KEYS, behaviors, css

ROOT = Path(__file__).resolve().parent.parent


def plain(text: str) -> str:
    """Testo senza spazi speciali (non separabili / sottili) per confronti indipendenti dalla lingua."""
    return text.replace("\u00a0", " ").replace("\u202f", " ")


# ------------------------------------------------------------------ importi scritti a mano
@pytest.mark.parametrize("text, expected", [
    ("20000", 20_000), ("20.000", 20_000), ("€ 20.000", 20_000), ("20 000", 20_000), ("1.250.000", 1_250_000),
    ("20k", 20_000), ("20 K", 20_000), ("2,5k", 2_500), ("2.5k", 2_500), ("1,5M", 1_500_000), ("1,5 mln", 1_500_000),
    ("12,50", 12.5), ("1.234,56", 1_234.56), ("50,000", 50_000), ("0", 0), (" 350.000 € ", 350_000),
    ("1,250,000", 1_250_000), ("€1,250,000.50", 1_250_000.5), ("12,345.67", 12_345.67), ("1\u202f250\u202f000\u00a0€", 1_250_000),
])
def test_parse_amount_accepts_the_ways_people_write_money(text, expected):
    assert parse_amount(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", ["", "tanto", "20..000", "1,2,3", "-5", "k", "12,5.5", "1.2.3k", ".", ",", None])
def test_parse_amount_rejects_garbage(text):
    assert parse_amount(text) is None


@pytest.mark.parametrize("text, lang, expected", [
    ("2 milioni", "it", 2e6), ("1 milione", "it", 1e6), ("1,5 milioni", "it", 1.5e6), ("un milione", "it", 1e6),
    ("3 mln di euro", "it", 3e6), ("2 milioni di euro", "it", 2e6), ("500 mila", "it", 5e5), ("500 mila euro", "it", 5e5),
    ("1 miliardo", "it", 1e9), ("2,5 mld", "it", 2.5e9), ("2 Mio", "it", 2e6), ("1,5M€", "it", 1.5e6), ("€ 2,5 M", "it", 2.5e6),
    ("2 million", "en", 2e6), ("1.5 million euros", "en", 1.5e6), ("a million", "en", 1e6), ("1.2bn", "en", 1.2e9),
    ("250 thousand", "en", 2.5e5), ("2M€", "en", 2e6), ("€2.5M", "en", 2.5e6), ("one million", "en", 1e6),
    ("2 millones", "es", 2e6), ("1,5 millones de euros", "es", 1.5e6), ("500 mil", "es", 5e5), ("2 mil millones", "es", 2e9),
    ("un millón", "es", 1e6), ("2 millions d'euros", "fr", 2e6), ("1,5 million", "fr", 1.5e6), ("500 mille", "fr", 5e5),
    ("3 Md€", "fr", 3e9), ("2 млн", "ru", 2e6), ("1,5 млн.", "ru", 1.5e6), ("2 миллиона", "ru", 2e6), ("500 тыс.", "ru", 5e5),
    ("3 млрд", "ru", 3e9), ("один миллион", "ru", 1e6), ("2 млн евро", "ru", 2e6), ("100万", "zh", 1e6), ("1.5亿", "zh", 1.5e8),
    ("100万欧元", "zh", 1e6), ("２５００万", "zh", 2.5e7), ("1,000,000", "zh", 1e6), ("5万", "zh", 5e4), ("1千万", "zh", 1e7),
])
def test_parse_amount_understands_millions_in_words_in_every_language(text, lang, expected):
    with i18n.use(lang):
        assert parse_amount(text) == pytest.approx(expected)


@pytest.mark.parametrize("text, expected", [
    ("250.0000", 2_500_000), ("€ 250.0000", 2_500_000), ("1.000.0000", 10_000_000), ("€ 1.000.00", 100_000),
    ("50.0000", 500_000), ("1000000", 1_000_000), ("1.000.000", 1_000_000), ("1'000'000", 1_000_000), ("1000 euro", 1_000),
    ("50.", 50), ("0,5", 0.5), ("1.5", 1.5),
])
def test_appending_a_digit_to_a_formatted_amount_keeps_the_grouping(text, expected):
    """Bug: scrivere uno zero dopo «€ 250.000» dava «250.0000», letto come 250 euro invece di 2,5 milioni."""
    assert parse_amount(text) == pytest.approx(expected)


def test_mil_means_thousand_only_in_spanish():
    with i18n.use("es"):
        assert parse_amount("500 mil") == 500_000
    assert parse_amount("500 mil") is None


@pytest.mark.parametrize("text", ["2 gatti", "5 xyz", "1e6", "50%", "$5", "1.2.3", "1,,5", "999999999999999999", "10000000000000",
                                  "mil", "abc123", "1 2 mil", "milioni", "2 milioni 3"])
def test_parse_amount_rejects_more_garbage_and_absurd_sizes(text):
    assert parse_amount(text) is None


@pytest.mark.parametrize("lang", list(i18n.LANGS))
def test_format_amount_round_trips_in_every_language(lang):
    """Il campo riscrive l'importo nella lingua attiva: deve poterlo rileggere anche dopo un cambio di formato."""
    with i18n.use(lang):
        for value in (0, 999, 1_000, 50_000, 1_250_000, 12_000_000):
            assert parse_amount(format_amount(value)) == value


def test_amounts_follow_the_language_of_the_session():
    assert format_amount(1_250_000) == "€ 1.250.000"
    with i18n.use("en"):
        assert format_amount(50_000) == "€50,000"


def test_widget_callbacks_see_the_session_language():
    """Streamlit esegue i callback prima dello script: la lingua deve arrivare dalla sessione (resolver)."""
    import ui.lang as ui_lang
    assert i18n._resolver is ui_lang._session_language
    assert ui_lang._session_language() is None      # fuori da una sessione non solleva errori


def test_confidence_dots_light_the_requested_share():
    html = confidence_dots(95)
    assert html.count('<i class="on"') == 95 and html.count("<i ") == 100
    assert confidence_dots(500).count('class="on"') == 100 and confidence_dots(-3).count('class="on"') == 0
    assert "--cols:10" in confidence_dots(50, 100, 10)


# ------------------------------------------------------------------ home
def test_welcome_counters_round_down_so_the_plus_sign_stays_true():
    assert [approx_floor(n) for n in (3478, 3438, 99, 7, 120, 1000, 12_345)] == [3400, 3400, 99, 7, 120, 1000, 12_000]


def test_welcome_cards_are_three_counters_with_a_plus_sign():
    from goalga.universe import universe_size
    cards, script = _feats_html()
    assert cards.count('class="gx-feat"') == 3 and cards.count("</span>+</b>") == 3
    assert re.findall(r'data-to="(\d+)"', cards) == ["1000", "100", str(approx_floor(universe_size()))]
    assert universe_size() >= 3000, "il numero di asset mostrato viene dal database reale"
    assert 'LOC="it-IT"' in script and "%s" not in script
    assert "oppure" not in cards.lower() and "esempio" not in cards.lower()


def test_count_up_script_has_no_less_than_sign():
    assert not re.search(r"<[/!\w]", _COUNT_UP.replace("<script>", "").replace("</script>", ""))


# ------------------------------------------------------------------ tema
def test_theme_css_survives_the_html_sanitizer():
    """st.html passa il contenuto a DOMPurify: un '<' nel foglio di stile lo fa scartare per intero."""
    text = css()
    assert "<" not in text and "</style" not in text
    assert text.count("{") == text.count("}")
    assert "--maxw" in text and "@property" in text


def test_every_custom_class_used_by_the_python_ui_is_styled():
    used = set()
    for path in (ROOT / "ui").glob("*.py"):
        used |= set(re.findall(r'class="(gx-[a-z0-9-]+)', path.read_text(encoding="utf-8")))
    styled = css()
    missing = sorted(c for c in used if f".{c}" not in styled)
    assert not missing, f"classi senza stile: {missing}"


# ------------------------------------------------------------------ comportamenti lato browser (assets/behaviors.js)
def test_behaviors_script_survives_the_html_sanitizer_and_is_well_formed():
    code = behaviors()
    assert "__NAV__" not in code and "__VERSION__" not in code, "elenco dei pulsanti e versione vengono inseriti da Python"
    assert not re.search(r"<[/!\w]", code), "DOMPurify scarta gli script che contengono «<»"
    for open_, close in ("()", "{}", "[]"):
        assert code.count(open_) == code.count(close), f"{open_}{close} non bilanciate"
    assert "window.__gx" in code, "idempotente: viene rieseguito a ogni cambio di lingua"
    raw = (ASSETS / "behaviors.js").read_text(encoding="utf-8").replace("__NAV__", "[]").replace("__VERSION__", "x")
    assert "<" not in raw


def test_behaviors_script_is_versioned_so_an_update_replaces_the_old_one_in_an_open_tab():
    """Un'app aggiornata mentre la scheda è aperta riesegue lo script: se la versione è diversa, quello vecchio si smonta."""
    code = behaviors()
    version = re.search(r'var VERSION = "([0-9a-f]{10})"', code).group(1)
    assert behaviors() == code and version, "stessa impronta finché il testo non cambia"
    assert "previous.v === VERSION" in code and "previous.off()" in code and "offs.push" in code
    assert "doc.addEventListener" not in code and "new MutationObserver(queue)" not in code, \
        "ogni listener passa da on()/watch(), altrimenti non si potrebbe smontare"


def test_navigation_prefixes_belong_to_real_buttons_and_reach_the_script():
    sources = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "ui").glob("*.py"))
    for prefix in NAV_KEYS:
        assert re.search(r'["\']' + re.escape(prefix), sources), f"nessun pulsante con chiave «{prefix}»"
    embedded = re.search(r"var NAV = (\[.*?\]);", behaviors()).group(1)
    assert json.loads(embedded) == list(NAV_KEYS)
    assert not any(p.startswith(("review-reset", "si_", "su_", "lab-next", "rk-btn")) for p in NAV_KEYS), \
        "i pulsanti che non cambiano schermata non devono far sfumare la pagina"


def test_page_transition_and_slider_bubble_are_styled():
    text = css()
    assert "html.gx-leaving" in text and "html.gx-swapped" in text and '[data-stale="true"]' in text
    assert 'data-dragging="true"' in text and "attr(data-cap)" in text and "[data-edge=" in text
    assert "var(--gx-years)" not in text and "data-year" not in text, "il numero grande è l'anno scelto: niente unità da comporre in CSS"
    assert "prefers-reduced-motion" in text, "chi riduce le animazioni non vede dissolvenze né fumetti che rimbalzano"
    assert "(max-width: 1120px)" in text and "(max-width: 860px)" in text, "la barra in alto regge il pulsante «Accedi o registrati»"


def test_font_is_bundled_with_its_license():
    fonts = ROOT / "static" / "fonts"
    assert (fonts / "Inter-latin.woff2").stat().st_size > 20_000
    assert (fonts / "Inter-cyrillic.woff2").read_bytes()[:4] == b"wOF2", "sottoinsieme cirillico per il russo"
    assert "SIL Open Font License" in (fonts / "OFL.txt").read_text(encoding="utf-8")
    config = (ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    assert "app/static/fonts/Inter-latin.woff2" in config and "app/static/fonts/Inter-cyrillic.woff2" in config
    assert config.count("unicodeRange") == 2, "ogni file copre solo la propria scrittura"


# ------------------------------------------------------------------ linea del tempo
def _goal(start, end, amount, kind="altro", gid=1):
    return {"id": gid, "kind": kind, "start": start, "end": end, "amount": amount}


def test_timeline_places_one_pin_per_goal_and_spans_recurring_ones():
    goals = [_goal(8, 8, 40_000, gid=1), _goal(20, 23, 32_000, gid=2), _goal(50, 50, 1_900_000, gid=3)]
    html = plain(timeline_html(goals))
    assert html.count("gx-tl-pin") == 3 and html.count("gx-tl-span") == 1
    assert "1,9" in html and "32" in html and "/anno" in html and "50 anni" in html
    assert 'left:16.00%' in html           # anno 8 su 50


def test_timeline_handles_empty_and_crowded_goals():
    assert "Nessun obiettivo" in timeline_html([])
    crowded = [_goal(8, 8, 10_000, gid=1), _goal(9, 9, 12_000, gid=2), _goal(10, 10, 14_000, gid=3), _goal(11, 11, 1_000, gid=4)]
    heights = set(re.findall(r'class="gx-tl-stem" style="height:(\d+)px', timeline_html(crowded)))
    assert len(heights) > 1, "le etichette vicine devono disporsi su corsie diverse"


def test_group_goals_round_trip():
    groups = group_goals(PAPER_GOALS_CASE_1)
    assert groups == [(10, 13, 32_000.0), (20, 23, 40_000.0), (50, 50, 1_900_000.0)]
    assert group_goals([(10, 5.0), (10, 7.0)]) == [(10, 10, 5.0), (10, 10, 7.0)]


# ------------------------------------------------------------------ scena dell'algoritmo
@pytest.fixture(scope="module")
def trace_payload(market):
    plan = Plan(w0=50_000, contribution=6_000, horizon=25, goals=((8, 40_000.0), (25, 350_000.0)), pr_target=0.9, alpha=0.05)
    scen = market.draw_scenarios(plan.horizon, 500, np.random.default_rng(1))
    problem = GoalProblem(plan.flows(), scen, plan.pr_target, plan.alpha)
    trace = EvolutionTrace(n_scenarios=500, n_portfolios=market.n_portfolios)
    result = run_ga(problem, GAConfig(pop_size=40, patience=30, seed=3), callback=trace)
    payload = trace.payload(elapsed=result.elapsed, stopped_by=result.stopped_by, best_generation=result.best_generation)
    payload["cap"] = 6
    return plan, payload


def _config(doc: str) -> dict:
    return json.loads(re.search(r"window\.GX=(\{.*?\});</script>", doc, re.S).group(1))


def test_stage_page_is_self_contained_and_safe(trace_payload):
    plan, payload = trace_payload
    doc = stage.stage_html(payload, plan)
    assert doc.startswith("<!doctype html>") and "window.GX=" in doc
    assert doc.count("</script>") == 2, "i dati serializzati non devono poter chiudere lo script"
    assert "http://" not in doc and "https://" not in doc, "nessuna risorsa esterna"
    cfg = _config(doc)
    assert cfg["mode"] == "replay" and cfg["target"] == plan.pr_target and cfg["nScenarios"] == 500
    assert [g["y"] for g in cfg["goals"]] == [8, 25] and plain(cfg["goals"][0]["label"]) == "40 k€"
    assert 8_500 <= cfg["duration"] <= 11_500 and len(doc) < 900_000


def test_stage_is_localized_and_shows_the_risk_limit(trace_payload):
    plan, payload = trace_payload
    cfg = _config(stage.stage_html(payload, plan))
    assert cfg["locale"] == "it-IT" and cfg["pctSuffix"] == "%" and cfg["cap"] == 6
    with i18n.use("en"):
        en = _config(stage.stage_html(payload, plan))
    assert en["locale"] == "en-GB" and en["text"] != cfg["text"]
    phases = cfg["text"]["phases"]
    assert len(phases) >= 4 and len(set(phases)) == len(phases), "le didascalie cambiano durante l'animazione"
    assert phases[0] == "Simulazioni lanciate" and "percorso ottimale" in phases[-1]


def test_stage_has_no_skip_or_replay_controls(trace_payload):
    """Una volta finita l'animazione è finita: niente «salta» né «rivedi»."""
    plan, payload = trace_payload
    doc = stage.stage_html(payload, plan)
    assert "<button" not in doc.lower() and "rivedi" not in doc.lower() and "salta" not in doc.lower()


def test_replay_duration_and_markers():
    assert stage.replay_duration_ms({"F": 5}) == 8_500 and stage.replay_duration_ms({"F": 500}) == 11_500
    plan = Plan(goals=PAPER_GOALS_CASE_1, horizon=50)
    marks = stage.goal_markers(plan)
    assert [m["y"] for m in marks] == [10, 13, 20, 23, 50]
    assert [plain(m["label"]) for m in marks] == ["32 k€/anno", "", "40 k€/anno", "", "1,9 M€"]


def test_ambient_page_has_no_data_and_no_external_resources():
    doc = stage.ambient_html()
    assert '"mode":"ambient"' in doc and "http" not in doc


def test_embed_falls_back_to_components_when_st_iframe_is_missing(monkeypatch):
    import streamlit as st
    calls = []
    monkeypatch.delattr(st, "iframe", raising=False)
    import streamlit.components.v1 as components
    monkeypatch.setattr(components, "html", lambda doc, height=None, **k: calls.append((len(doc), height)))
    stage.embed("<html></html>", 321)
    assert calls == [(13, 321)]


def test_stage_runs_in_a_real_browser(trace_payload):
    """La pagina del replay deve eseguirsi senza errori JavaScript e disegnare sul canvas (opzionale: serve Chromium)."""
    sync_api = pytest.importorskip("playwright.sync_api")
    plan, payload = trace_payload
    doc = stage.stage_html(payload, plan, replay_ms=700)
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:  # browser non installato
            pytest.skip(f"Chromium non disponibile: {exc}")
        page = browser.new_page(viewport={"width": 1000, "height": 560})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.set_content(doc)
        page.wait_for_function("window.__gx && window.__gx.done === true", timeout=20_000)
        time.sleep(0.5)
        painted = page.evaluate("""() => { const c = document.getElementById('cv'); const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
            let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i] > 0) n++; return n; }""")
        gen = page.inner_text("#v-gen")
        pr = page.inner_text("#v-pr")
        browser.close()
    assert not errors, errors
    assert painted > 2_000
    assert re.sub(r"\D", "", gen) == str(payload["generations"]) and pr.endswith("%")


# ------------------------------------------------------------------ asset class
def test_macro_classes_cover_the_catalog():
    mapping = classes.asset_class_map(["SWDA.MI", "XEON.MI", "IEAC.MI", "AAPL", "VNQ", "SGLD.MI", "IHYG.MI", "ZZZZ"])
    assert mapping == {"SWDA.MI": "equity", "XEON.MI": "cash", "IEAC.MI": "bonds", "AAPL": "equity",
                       "VNQ": "realestate", "SGLD.MI": "commodities", "IHYG.MI": "bonds", "ZZZZ": "other"}


def test_category_keys_and_labels_follow_the_catalog():
    assert classes.category_key("AAPL") == "stocks" and classes.category_key("XEON.MI") == "cash"
    assert classes.category_key("SPY") == "dev_equity" and classes.category_key("NOPE") == "other"
    assert classes.category_label("XEON.MI") == "Liquidità" and classes.category_label("AAPL") == "Tecnologia e software"
    with i18n.use("en"):
        assert classes.category_label("IHYG.MI") == "High-yield bonds"


def test_class_labels_exist_in_every_language():
    assert classes.label("bonds") == "Obbligazioni" and classes.label("equity") == "Azioni"
    for lang in i18n.LANGS:
        with i18n.use(lang):
            names = [classes.label(key) for key in classes.MACRO_ORDER]
        assert all(n and not n.startswith("class.") for n in names) and len(set(names)) == len(names), lang


def test_macro_composition_preserves_total_weight():
    comp = pd.DataFrame([[0.5, 0.3, 0.2], [0.1, 0.1, 0.8]], columns=["XEON.MI", "IEAC.MI", "SWDA.MI"], index=[1, 2])
    macro = classes.macro_composition(comp, classes.asset_class_map(list(comp.columns)))
    assert list(macro.columns) == ["cash", "bonds", "equity"]
    assert np.allclose(macro.sum(axis=1), 1.0) and macro.loc[2, "equity"] == pytest.approx(0.8)


# ------------------------------------------------------------------ composizione con molte azioni
def _stock_heavy_composition():
    cols = ["XEON.MI", "IHYG.MI", "VWO", "AAPL", "MSFT", "JNJ"]
    comp = pd.DataFrame([[0.20, 0.30, 0.20, 0.10, 0.10, 0.10], [0.50, 0.20, 0.10, 0.10, 0.05, 0.05]], columns=cols,
                        index=[1, 2])
    return comp, {c: c for c in cols}


def test_holdings_are_grouped_by_category_and_keep_every_asset():
    from ui import holdings
    comp, names = _stock_heavy_composition()
    colors = holdings._palette(comp)
    page = holdings.holdings_html(holdings._ordered(comp.loc[1]), names, classes.asset_class_map(list(comp.columns)), colors)
    assert page.count("gx-hgroup") == 4, "liquidità, high yield, azionario emergente e azioni singole"
    assert page.index("Liquidità") < page.index("Obbligazioni high yield") < page.index("Azioni singole")
    assert "Azioni singole · 3" in page and all(t in page for t in comp.columns)
    assert colors["AAPL"] == colors["MSFT"] != colors["XEON.MI"], "un solo colore per categoria"


def test_holdings_heatmap_collapses_the_stock_basket_into_one_column():
    from ui import holdings
    comp, names = _stock_heavy_composition()
    table = holdings.heatmap_html(comp, names, 2026)
    assert "Azioni singole" in table and "AAPL" not in table and "MSFT" not in table
    assert ">30<" in table.replace(" ", ""), "10% + 10% + 10% in azioni nel primo anno"


def test_holdings_donut_is_ordered_by_category():
    from ui import holdings
    comp, _ = _stock_heavy_composition()
    ordered = holdings._ordered(comp.loc[1])
    assert list(ordered.index[:3]) == ["XEON.MI", "IHYG.MI", "VWO"] and set(ordered.index[3:]) == {"AAPL", "MSFT", "JNJ"}


def test_formatting_helpers_used_by_the_ui():
    assert plain(fmt.eur_compact(40_000)) == "40 k€" and plain(fmt.eur_compact(1_900_000)) == "1,9 M€"
    assert fmt.pct(0.9583, 1) == "95,8%"
    js = (ASSETS / "evolve.js").read_text(encoding="utf-8")
    assert js.count("(") == js.count(")") and js.count("{") == js.count("}")


def test_a_percentage_below_one_hundred_is_never_shown_as_one_hundred():
    """Una probabilità del 99,996% vuol dire che in qualche scenario è andata male: non si scrive «100%»."""
    assert fmt.pct(0.99996, 1) == "99,9%" and fmt.pct(0.9951, 0) == "99%" and fmt.pct(0.99999, 2) == "99,99%"
    assert fmt.pct(1.0, 1) == "100,0%" and fmt.pct(1.0, 0) == "100%", "il 100% vero resta tale"
    assert fmt.pct(0.9994, 1) == "99,9%" and fmt.pct(0.0, 1) == "0,0%" and fmt.pct(-0.0123, 1) == "-1,2%"
    assert fmt.pct(1.2, 0) == "120%", "e i valori oltre il 100% (non probabilità) non vengono toccati"


def test_a_tail_that_is_not_a_whole_percentage_keeps_its_decimal():
    assert fmt.pct_short(0.05) == "5%" and fmt.pct_short(0.025) == "2,5%" and fmt.pct_short(0.02) == "2%"


def _run_with(ga_feasible, oos_pr, oos_feasible, pr=0.88):
    from types import SimpleNamespace

    from goalga.analytics import OutOfSample
    oos = None if oos_pr is None else OutOfSample(10_000, oos_pr, oos_pr - 0.006, oos_pr + 0.006, 0.03, 1e4, oos_feasible)
    report = SimpleNamespace(ga=SimpleNamespace(feasible=ga_feasible), oos=oos, pr=pr, required_return=0.04)
    return SimpleNamespace(report=report, plan=Plan(w0=1_000, contribution=100, horizon=5, goals=((5, 1_000.0),),
                                                    pr_target=0.9, alpha=0.05),
                           market=None, previews=[], max_level=6)


def test_the_headline_follows_the_validated_probability_and_never_contradicts_itself():
    from ui.result import outcome
    both = outcome(_run_with(True, 0.93, True))
    assert both["ok"] and both["n"] == 93
    lucky = outcome(_run_with(False, 0.905, True))
    assert lucky["ok"] and lucky["n"] == 90, "la ricerca non ha trovato la soglia ma la verifica su scenari nuovi sì: vale questa"
    near = outcome(_run_with(True, 0.8996, False))
    assert not near["ok"] and "89,96%" in near["lead"], "un quasi-successo mostra due decimali: non «95,0% sotto 95»"
    no_validation = outcome(_run_with(True, None, False, pr=0.92))
    assert no_validation["ok"] and no_validation["n"] == 92


def _bench(ga, **others):
    """Tabella di confronto minima: ``(probabilità, IRR di coda, soglia rispettata)`` per ogni strategia."""
    rows = {"ga": ga, **others}
    return pd.DataFrame({"Chiave": list(rows), "Strategia": list(rows),
                         "Probabilità di successo": [v[0] for v in rows.values()],
                         "IRR atteso (coda)": [v[1] for v in rows.values()],
                         "Patrimonio finale medio (coda)": 0.0, "Soglia rispettata": [v[2] for v in rows.values()],
                         "Score": 0.0})


@pytest.mark.parametrize("ga, others, key", [
    ((0.95, 0.040, True), {"const5": (0.93, 0.030, True), "const3": (0.80, 0.045, False)}, "plan.cmp.better"),
    ((0.95, 0.0300, True), {"const5": (0.93, 0.0305, True)}, "plan.cmp.equal"),
    ((0.95, 0.0300, True), {"const5": (0.93, 0.0390, True)}, "plan.cmp.worse"),
    ((0.95, 0.040, True), {"const5": (0.80, 0.050, False)}, "plan.cmp.only"),
    ((0.88, 0.020, False), {"const5": (0.80, 0.030, False)}, "plan.cmp.none"),
    ((0.89, 0.020, False), {"const5": (0.91, 0.030, True)}, "plan.cmp.other"),
])
def test_the_comparison_verdict_follows_the_numbers_and_ignores_differences_that_are_noise(ga, others, key):
    from ui.result import comparison_verdict
    assert comparison_verdict(_bench(ga, **others), 90)[0] == key


def test_the_verdict_names_the_best_alternative_and_the_size_of_the_gap():
    from ui.result import comparison_verdict
    key, args = comparison_verdict(_bench((0.95, 0.0300, True), const5=(0.93, 0.0390, True), const4=(0.91, 0.0350, True)), 90)
    assert key == "plan.cmp.worse" and args["gap"] == "0,90" and "5" in args["name"]
    key, args = comparison_verdict(_bench((0.95, 0.0450, True), const5=(0.93, 0.0300, True)), 90)
    assert key == "plan.cmp.better" and args["gap"] == "1,50" and args["target"] == 90
