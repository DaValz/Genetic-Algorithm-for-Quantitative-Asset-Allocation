"""Test del percorso guidato con AppTest (nessun accesso alla rete: i prezzi sono quelli dell'archivio sintetico)."""
import html
import json
import re
from datetime import date
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from goalga import i18n  # noqa: E402
from goalga.i18n import LANGS, t  # noqa: E402

APP = str(Path(__file__).resolve().parent.parent / "app.py")
ROOT_DIR = Path(__file__).resolve().parent.parent
GOALS = [
    {"id": 1, "kind": "casa", "start": 8, "end": 8, "amount": 40_000.0},
    {"id": 2, "kind": "pensione", "start": 25, "end": 25, "amount": 300_000.0},
]
PASSWORD = "correct horse battery"


@pytest.fixture(autouse=True)
def offline(monkeypatch, tmp_path):
    import streamlit as st

    from ui import account
    monkeypatch.setenv("GOALGA_DB_PATH", str(tmp_path / "accounts.db"))
    monkeypatch.delenv("GOALGA_DATABASE_URL", raising=False)
    st.cache_data.clear()
    account.reset_service()
    yield
    account.reset_service()
    st.cache_data.clear()


# ------------------------------------------------------------------ utilità
def run_app() -> AppTest:
    return AppTest.from_file(APP, default_timeout=180).run()


def click(at: AppTest, key: str) -> AppTest:
    return at.button(key=key).click().run()


def keys(at: AppTest) -> list[str]:
    return [b.key for b in at.button]


def plan_state(**override) -> dict:
    return {"w0": 50_000.0, "contribution": 6_000.0, "goals": [dict(g) for g in GOALS], "next_goal_id": 3, **override}


def at_step(step: str, **state) -> AppTest:
    """App già posizionata su ``step`` con un piano valido (casa e pensione) e gli eventuali valori indicati."""
    at = run_app()
    at.session_state["step"] = step
    values = {} if step in ("welcome", "start") else plan_state()
    for key, value in {**values, **state}.items():
        at.session_state[key] = value
    return at.run()


def texts(at: AppTest) -> str:
    return " ".join(e.value for e in [*at.warning, *at.error, *at.info, *at.success])


def html_of(at: AppTest) -> str:
    """Contenuto HTML di tutti gli elementi ``st.html`` della pagina."""
    return " ".join(e.proto.body for e in at.get("html"))


def run_to_plan(at: AppTest | None = None) -> AppTest:
    at = at or at_step("review")
    click(at, "cta-btn")                     # Trova la mia strategia
    assert at.session_state["step"] == "evolve" and not at.exception
    return click(at, "cta-late-btn")         # Scopri il tuo piano


def set_step(at: AppTest, step: str) -> AppTest:
    at.session_state["step"] = step
    return at.run()


def sign_up(at: AppTest, email="mario@example.com", password=PASSWORD, name="Mario", again=None) -> AppTest:
    at.text_input(key="su_name").set_value(name).run()
    at.text_input(key="su_email").set_value(email).run()
    at.text_input(key="su_password").set_value(password).run()
    at.text_input(key="su_password2").set_value(again if again is not None else password).run()
    return click(at, "su_submit")


# ------------------------------------------------------------------ home e punto di partenza
def test_home_starts_the_guided_flow_without_examples():
    at = run_app()
    assert not at.exception and at.session_state["step"] == "welcome"
    assert [b.label for b in at.button if b.key == "cta-home-btn"] == [t("welcome.cta")]
    assert not at.sidebar.children, "nessuna barra laterale: il percorso è guidato"
    assert not list(at.pills), "nessun «parti da un esempio»"
    page = html_of(at)
    assert "esempio" not in page.lower() and "data-to=\"1000\"" in page and "data-to=\"100\"" in page
    assert "Simulazione di migliaia di futuri" in page


def test_the_third_welcome_number_counts_the_assets_of_the_whole_universe():
    from goalga.universe import universe_size
    from ui.flow import approx_floor
    page = html_of(run_app())
    assert f'data-to="{approx_floor(universe_size())}"' in page and approx_floor(universe_size()) >= 3400
    assert page.count('class="gx-count"') == 3 and page.count("</span>+</b>") == 3, "tutti i numeri hanno il «+»"


def test_without_the_price_archive_the_app_explains_what_to_do(monkeypatch, tmp_path):
    monkeypatch.setenv("GOALGA_PRICES_FILE", str(tmp_path / "missing.parquet"))
    at = run_app()
    assert not at.exception and t("mkt.no_snapshot_help") in texts(at)
    assert not list(at.button), "senza dati non si propone di proseguire"


def test_language_switcher_offers_the_six_languages():
    at = run_app()
    picker = at.selectbox(key="lang_pick")
    assert set(picker.options) == set(LANGS.values()) and picker.value == "it"


def test_start_is_always_a_fresh_blank_plan():
    at = run_app()
    at.session_state["w0"], at.session_state["goals"], at.session_state["risk"] = 75_000.0, [dict(g) for g in GOALS], "dynamic"
    at.session_state["result"] = object()
    at.run()
    at = click(at, "cta-home-btn")
    assert at.session_state["step"] == "start" and not at.exception
    assert (at.session_state["w0"], at.session_state["contribution"], at.session_state["goals"]) == (0.0, 0.0, [])
    assert at.session_state["risk"] == "balanced" and "result" not in at.session_state
    assert at.button(key="cta-btn").disabled, "senza importi non si procede"


def test_each_step_renders_and_back_navigation_keeps_inputs():
    at = run_app()
    at = click(at, "cta-home-btn")
    assert at.session_state["step"] == "start"
    at.text_input(key="in_w0").set_value("75k").run()
    at = click(at, "cta-btn")
    assert at.session_state["step"] == "goals"
    at = click(at, "back-goals")
    assert at.session_state["step"] == "start"
    assert at.text_input(key="in_w0").value == "€ 75.000"
    for step in ("goals", "risk", "review"):
        at = at_step(step)
        assert not at.exception and at.session_state["step"] == step


def test_user_inputs_reach_the_model_and_survive_navigation():
    """Nel vecchio wizard i parametri inseriti sparivano: il GA riceveva sempre 160k/10k/30 anni."""
    at = at_step("start")
    at.text_input(key="in_w0").set_value("250000").run()
    at.text_input(key="in_contribution").set_value("20k").run()
    at = click(at, "cta-btn")                                  # → obiettivi (vuoti: piano nuovo)
    at.pills(key="add_goal").set_value("altro").run()
    goal = at.session_state["goals"][0]
    at.slider(key=f"gw_{goal['id']}").set_value(NOW + 20).run()
    at.text_input(key=f"ga_{goal['id']}").set_value("300.000").run()
    for _ in range(3):
        at.run()                                               # rerun ripetuti, come cambiando schermata
    at = run_to_plan(set_step(at, "review"))
    assert not at.exception
    plan = at.session_state["result"].plan
    assert (plan.w0, plan.contribution, plan.horizon) == (250_000, 20_000, 20)
    assert plan.last_contribution_year == 19 and plan.goals == ((20, 300_000.0),)


def test_invalid_amount_is_rejected_and_the_previous_value_is_kept():
    at = at_step("start", w0=50_000.0)
    at.text_input(key="in_w0").set_value("tanto").run()
    assert not at.exception
    assert at.session_state["w0"] == 50_000 and at.text_input(key="in_w0").value == "€ 50.000"
    assert at.session_state["bad_w0"] is True


def test_quick_amount_pills_update_the_field():
    at = at_step("start")
    at.pills(key="chip-w0").set_value(250_000).run()
    assert at.session_state["w0"] == 250_000 and at.text_input(key="in_w0").value == "€ 250.000"
    at.pills(key="chip-w0").set_value(1_000_000).run()                  # tra le scorciatoie c'è anche il milione
    assert at.session_state["w0"] == 1_000_000 and at.text_input(key="in_w0").value == "€ 1.000.000"


def test_millions_can_be_typed_on_the_first_two_pages():
    """Bug: scrivendo uno zero in coda a «€ 250.000» il campo leggeva 250 euro, e le parole («2 milioni») erano rifiutate."""
    at = at_step("start", w0=250_000.0)
    at.text_input(key="in_w0").set_value("€ 250.0000").run()            # lo zero aggiunto alla fine del testo formattato
    assert at.session_state["w0"] == 2_500_000 and at.text_input(key="in_w0").value == "€ 2.500.000"
    at.text_input(key="in_w0").set_value("2 milioni").run()
    assert at.session_state["w0"] == 2_000_000 and at.session_state["bad_w0"] is False
    at.text_input(key="in_contribution").set_value("1,5 mln").run()
    assert at.session_state["contribution"] == 1_500_000 and at.text_input(key="in_contribution").value == "€ 1.500.000"

    at = at_step("goals")
    gid = at.session_state["goals"][0]["id"]
    at.text_input(key=f"ga_{gid}").set_value("€ 40.0000").run()
    assert at.session_state["goals"][0]["amount"] == 400_000 and at.text_input(key=f"ga_{gid}").value == "€ 400.000"
    at.text_input(key=f"ga_{gid}").set_value("1 milione").run()
    assert at.session_state["goals"][0]["amount"] == 1_000_000
    at.text_input(key=f"ga_{gid}").set_value("mezzo milione").run()          # non è un importo: resta quello di prima
    assert at.session_state["goals"][0]["amount"] == 1_000_000 and at.text_input(key=f"ga_{gid}").value == "€ 1.000.000"
    assert html.escape(t("input.bad_amount")) in html_of(at), "anche nella seconda pagina un testo illeggibile non passa in silenzio"
    at.text_input(key=f"ga_{gid}").set_value("1,2 milioni").run()
    assert at.session_state["goals"][0]["amount"] == 1_200_000 and html.escape(t("input.bad_amount")) not in html_of(at)


def test_amounts_are_reformatted_in_the_language_of_the_session():
    """I callback dei widget girano prima dello script: il formato deve seguire la lingua scelta (era sempre inglese)."""
    at = at_step("start")
    at.text_input(key="in_w0").set_value("50k").run()
    assert at.text_input(key="in_w0").value == "€ 50.000"
    at.selectbox(key="lang_pick").set_value("en").run()
    at.text_input(key="in_w0").set_value("60k").run()
    assert at.text_input(key="in_w0").value == "€60,000"
    at.selectbox(key="lang_pick").set_value("es").run()
    at.text_input(key="in_w0").set_value("70k").run()
    assert at.text_input(key="in_w0").value.replace("\u00a0", " ") == "70.000 €"


# ------------------------------------------------------------------ obiettivi
# i cursori degli obiettivi scelgono anni di calendario (2034); il piano conta gli anni da oggi (8)
NOW = date.today().year


def test_goals_can_be_added_removed_and_summed_in_the_same_year():
    at = at_step("goals")
    n = len(at.session_state["goals"])
    at.pills(key="add_goal").set_value("studi").run()
    assert len(at.session_state["goals"]) == n + 1 and at.session_state["add_goal"] is None
    new = at.session_state["goals"][-1]
    assert (new["kind"], new["start"], new["end"]) == ("studi", 15, 15)
    assert at.slider(key=f"gw_{new['id']}").value == NOW + 15, "il cursore mostra l'anno di calendario"
    at.slider(key=f"gw_{new['id']}").set_value(NOW + 8).run()  # stesso anno della «casa»
    at.text_input(key=f"ga_{new['id']}").set_value("10000").run()
    at = run_to_plan(set_step(at, "review"))
    flows = at.session_state["result"].plan.flows()
    assert flows.goals[7] == pytest.approx((40_000 + 10_000) * 1.02**8), \
        "più obiettivi nello stesso anno vengono sommati (e rivalutati con l'inflazione del 2%)"
    at = set_step(at, "goals")
    click(at, f"rm-{new['id']}")
    assert len(at.session_state["goals"]) == n


def test_the_goal_slider_picks_calendar_years_and_the_plan_counts_years_from_today():
    at = at_step("goals")
    first = at.session_state["goals"][0]
    slider = at.slider(key=f"gw_{first['id']}")
    assert (slider.min, slider.max, slider.value) == (NOW + 1, NOW + 60, NOW + 8), "da 1 a 60 anni da oggi, in anni di calendario"
    slider.set_value(NOW + 31).run()
    assert (first["start"], first["end"]) == (31, 31) and f"{NOW + 31}" in html_of(at), "il titolo della scheda dice anche l'anno"


def test_recurring_goal_expands_to_one_flow_per_year():
    from ui.state import expand_goals
    at = at_step("goals")
    first = at.session_state["goals"][0]
    assert not at.toggle(key=f"gm_{first['id']}").value, "un obiettivo di un solo anno parte con un cursore solo"
    at.toggle(key=f"gm_{first['id']}").set_value(True).run()
    assert at.slider(key=f"gy_{first['id']}").value == (NOW + 8, NOW + 12), "«ogni anno»: 5 anni a partire dall'anno scelto"
    at.slider(key=f"gy_{first['id']}").set_range(NOW + 10, NOW + 13).run()
    years = [y for y, amount in expand_goals(at.session_state["goals"]) if amount == first["amount"]]
    assert years == [10, 11, 12, 13]
    at.toggle(key=f"gm_{first['id']}").set_value(False).run()
    assert at.slider(key=f"gw_{first['id']}").value == NOW + 10 and f"gy_{first['id']}" not in at.session_state
    assert [(g["start"], g["end"]) for g in at.session_state["goals"]][0] == (10, 10)


def test_saved_recurring_goal_opens_with_the_range_and_both_ends_stay_apart():
    at = at_step("goals", goals=[{"id": 1, "kind": "studi", "start": 15, "end": 18, "amount": 12_000.0}], next_goal_id=2)
    assert at.toggle(key="gm_1").value and at.slider(key="gy_1").value == (NOW + 15, NOW + 18)
    at.slider(key="gy_1").set_range(NOW + 22, NOW + 22).run()
    assert at.slider(key="gy_1").value == (NOW + 22, NOW + 23), \
        "i due cursori non possono sovrapporsi: l'estremità in cima non si raggiungerebbe più"
    at.slider(key="gy_1").set_range(NOW + 60, NOW + 60).run()
    assert at.slider(key="gy_1").value == (NOW + 59, NOW + 60)
    assert (at.session_state["goals"][0]["start"], at.session_state["goals"][0]["end"]) == (59, 60)


def test_repeating_a_goal_at_the_last_year_keeps_the_two_ends_apart():
    at = at_step("goals", goals=[{"id": 1, "kind": "altro", "start": 60, "end": 60, "amount": 5_000.0}], next_goal_id=2)
    at.toggle(key="gm_1").set_value(True).run()
    assert at.slider(key="gy_1").value == (NOW + 59, NOW + 60)


def test_goal_years_left_over_from_an_earlier_year_are_pulled_back_into_range():
    """A cavallo d'anno i limiti dei cursori scorrono: uno stato rimasto fuori intervallo non deve far fallire la pagina."""
    at = at_step("goals", **{"gw_1": NOW - 1})
    assert not at.exception and at.slider(key="gw_1").value == NOW + 1
    at = at_step("goals", **{"gm_1": True, "gy_1": (NOW - 3, NOW + 99)})
    assert not at.exception and at.slider(key="gy_1").value == (NOW + 1, NOW + 60)


def test_plan_without_goals_cannot_continue():
    at = at_step("goals", goals=[])
    assert at.button(key="cta-btn").disabled


def _live(at: AppTest) -> dict:
    """Testi per il browser (fumetto e intestazione mentre si trascina): JSON nell'attributo data-gx-live."""
    raw = re.search(r"data-gx-live='([^']*)'", html_of(at)).group(1)
    return json.loads(html.unescape(raw))


@pytest.mark.parametrize("lang, expected", [
    ("it", {1: "tra 1 anno", 8: "tra 8 anni"}), ("en", {1: "in 1 year", 8: "in 8 years"}),
    ("es", {1: "en 1 año", 8: "en 8 años"}), ("fr", {1: "dans 1 an", 8: "dans 8 ans"}),
    ("ru", {1: "через 1 год", 2: "через 2 года", 5: "через 5 лет", 21: "через 21 год", 60: "через 60 лет"}),
    ("zh", {1: "1 年后", 8: "8 年后"}),
])
def test_slider_bubble_caption_follows_the_language_and_its_plurals(lang, expected):
    """Il fumetto dice l'anno scelto (numero grande) e «tra 8 anni» (didascalia): le frasi, plurali compresi, le scrive il server."""
    at = at_step("goals")
    at.selectbox(key="lang_pick").set_value(lang).run()
    live = _live(at)
    assert live["base"] == NOW and len(live["cap"]) == len(live["one"]) == len(live["count"]) == 60
    for n, text in expected.items():
        assert live["cap"][n - 1] == text
    page = html_of(at)
    assert '"data-gx-year"' in page and "data-gx-hide" in page
    with i18n.use(lang):
        assert at.toggle(key="gm_1").label == t("goals.repeat")


def test_live_texts_are_the_phrases_the_server_writes_after_the_release():
    """Mentre si trascina l'intestazione si aggiorna nel browser: deve dire esattamente ciò che scriverà il server."""
    from ui.goals import _span_text
    live = _live(at_step("goals"))
    for n in (1, 8, 31, 60):
        assert live["one"][n - 1] == _span_text(n, n)
    for start, end in ((5, 14), (13, 32), (59, 60)):
        text = live["span"].format(start=start, end=end, count=live["count"][end - start], y0=NOW + start, y1=NOW + end)
        assert text == _span_text(start, end)
    assert live["every"] == t("goals.every_year")


def test_live_texts_are_only_sent_on_the_goals_page():
    marker = "data-gx-live='"                  # lo script la nomina sempre, il segnaposto con i dati c'è solo qui
    assert marker in html_of(at_step("goals")) and marker not in html_of(at_step("risk"))


def test_login_button_invites_to_sign_up_too():
    old = {"it": "Accedi", "en": "Sign in", "es": "Acceder", "fr": "Connexion", "ru": "Войти", "zh": "登录"}
    at = run_app()
    labels = {}
    for lang in LANGS:
        at.selectbox(key="lang_pick").set_value(lang).run()
        labels[lang] = at.button(key="acct-btn").label
    assert labels["it"] == "Accedi o registrati" and labels["en"] == "Sign in or sign up"
    assert all(len(labels[lang]) > len(word) for lang, word in old.items()), "ogni lingua ha l'invito a registrarsi"


# ------------------------------------------------------------------ rischio
def test_risk_page_compares_three_profiles_with_their_success_probability():
    at = at_step("risk")
    assert not at.exception
    previews = at.session_state["risk_previews"]["items"]
    assert [p.key for p in previews] == ["cautious", "balanced", "dynamic"] and [p.max_level for p in previews] == [3, 6, 9]
    page = html_of(at)
    assert len(re.findall(r'class="gx-risk(?: sel)?"', page)) == 3
    assert "disposto ad assumere" in page.replace("</span>", "").replace('<span class="gx-grad">', "")
    for key in ("cautious", "balanced", "dynamic"):
        assert t(f"risk.{key}.name") in page and t(f"risk.{key}.tag") in page
    assert "rk-btn-balanced" in keys(at)
    selected = at.button(key="rk-btn-balanced")
    assert selected.label == t("risk.selected") and not selected.disabled, "il profilo scelto resta ben visibile"
    assert at.button(key="rk-btn-cautious").label == t("risk.choose")


def test_choosing_a_profile_limits_the_search_space():
    at = at_step("risk")
    at = click(at, "rk-btn-cautious")
    assert at.session_state["risk"] == "cautious" and at.button(key="rk-btn-cautious").label == t("risk.selected")
    at = run_to_plan(set_step(at, "review"))
    run = at.session_state["result"]
    assert run.risk == "cautious" and run.max_level == 3 and int(run.report.path.max()) <= 3
    assert run.trace["cap"] == 3 and run.trace["K"] == 9
    assert t("risk.cautious.name") in html_of(at), "il piano ricorda il profilo scelto"


def test_risk_previews_are_not_recomputed_when_only_the_profile_changes(monkeypatch):
    import ui.risk as risk_page
    calls = []
    real = risk_page.preview_profiles
    monkeypatch.setattr(risk_page, "preview_profiles", lambda *a, **k: calls.append(1) or real(*a, **k))
    at = at_step("risk")
    click(at, "rk-btn-dynamic")
    set_step(at, "review")
    set_step(at, "risk")
    assert len(calls) == 1


def test_previews_say_whether_more_risk_would_help():
    from ui.risk import success_count
    assert success_count(0.9996) == 99 and success_count(1.0) == 100 and success_count(0.904) == 90 and success_count(0.0) == 0


# ------------------------------------------------------------------ riepilogo e impostazioni automatiche/avanzate
def test_review_asks_for_confirmation_and_summarizes_the_plan():
    at = at_step("review")
    page = html_of(at)
    assert "Confermi" in page and "gx-gauge" in page and t("review.gauge.title") in page
    assert t("risk.balanced.name") in page and "€ 50.000" in page and "€ 300.000" in page
    assert t("review.auto.title_auto") in page, "di default decide l'app"
    assert not at.session_state["use_advanced"]


def test_review_offers_a_single_prominent_advanced_button_instead_of_a_toggle_and_a_small_link():
    at = at_step("review")
    page = html_of(at) + texts(at) + " ".join(m.value for m in at.markdown)
    assert not list(at.toggle), "niente interruttore: si personalizza con il pulsante"
    assert at.button(key="to-lab").label == t("review.adv.use") and t("review.adv.use") == "Usa impostazioni avanzate"
    assert "to-lab-link" not in keys(at) and "Preferisci scegliere tu" not in page, "via il piccolo «preferisci scegliere tu?»"
    assert "review-reset" not in keys(at), "in automatico non c'è nulla da ripristinare"
    css = (ROOT_DIR / "ui" / "assets" / "theme.css").read_text(encoding="utf-8")
    assert ".st-key-to-lab button {" in css and ".st-key-review-actions" in css, "il pulsante ha uno stile dedicato"


def test_review_tells_how_ambitious_the_plan_is():
    at = at_step("review")
    assert t("review.gauge.title") in html_of(at)
    hard = at_step("review", w0=1_000.0, contribution=500.0)
    assert t("review.gauge.very_ambitious") in html_of(hard)


def test_the_advanced_button_opens_the_lab_and_coming_back_without_changes_stays_automatic():
    at = click(at_step("review"), "to-lab")
    assert at.session_state["step"] == "lab" and at.session_state["use_advanced"] is True and not at.exception
    at = click(at, "back-lab")
    assert at.session_state["step"] == "review" and at.session_state["use_advanced"] is False
    assert at.button(key="to-lab").label == t("review.adv.use") and t("review.auto.title_auto") in html_of(at)


def test_coming_back_with_changes_keeps_them_and_the_review_names_the_steps_that_changed():
    from goalga.universe import SECTOR_CATEGORIES
    at = click(at_step("review"), "to-lab")
    at.pills(key="cats_sectors").set_value(["technology"]).run()          # passo 1 · Dove investire
    at = click(at, "back-lab")
    assert at.session_state["step"] == "review" and at.session_state["use_advanced"] is True
    page = html_of(at)
    assert t("review.auto.title_adv") in page and t("lab.changed") in page and t("lab.section.universe") in page
    assert at.button(key="to-lab").label == t("review.adv.edit") and "review-reset" in keys(at)
    at = click(at, "review-reset")                                       # «Torna alle scelte automatiche» anche da qui
    assert at.session_state["step"] == "review" and at.session_state["use_advanced"] is False
    assert at.session_state["cats_sectors"] == list(SECTOR_CATEGORIES) and t("review.auto.title_auto") in html_of(at)
    assert at.button(key="to-lab").label == t("review.adv.use") and "review-reset" not in keys(at)


def test_automatic_mode_ignores_what_was_set_in_the_lab():
    """Con le impostazioni automatiche i parametri avanzati salvati non incidono sul risultato."""
    at = at_step("review", pop_size=60, n_scenarios=500, use_advanced=False)
    at = run_to_plan(at)
    run = at.session_state["result"]
    assert run.ga_config.pop_size == 100 and run.n_scenarios == 1000 and run.spec["advanced"] is False
    advanced = run_to_plan(at_step("review", pop_size=60, n_scenarios=500, use_advanced=True))
    run = advanced.session_state["result"]
    assert run.ga_config.pop_size == 60 and run.n_scenarios == 500 and run.spec["advanced"] is True


def test_back_to_automatic_choices_resets_everything_and_leaves_the_lab():
    """«Torna alle scelte automatiche» non si limita ad azzerare: riporta alla conferma, che riparte in automatico."""
    at = click(at_step("review"), "to-lab")
    at.session_state["lab_section"] = "search"
    at.run()
    at.slider(key="pop_size").set_value(60).run()
    at.session_state["lab_section"] = "returns"
    at.run()
    at = click(at, "lab-reset")
    assert at.session_state["step"] == "review" and not at.exception, "si torna alla schermata di partenza"
    assert at.session_state["use_advanced"] is False and at.session_state["pop_size"] == 100
    assert at.session_state["lab_section"] == "universe", "la prossima volta l'area avanzata riparte dal primo passo"
    assert t("review.auto.title_auto") in html_of(at) and at.button(key="to-lab").label == t("review.adv.use")
    run = run_to_plan(at).session_state["result"]
    assert run.ga_config.pop_size == 100 and run.spec["advanced"] is False


def test_back_to_automatic_choices_returns_to_the_plan_when_the_lab_was_opened_from_there():
    at = run_to_plan()
    first = at.session_state["result"]
    at = click(at, "plan-lab")
    assert at.session_state["step"] == "lab" and at.session_state["lab_from"] == "plan"
    at = click(at, "lab-reset")
    assert at.session_state["step"] == "plan" and at.session_state["result"] is first and not at.exception
    assert at.session_state["use_advanced"] is False


def test_back_to_automatic_choices_reuses_the_market_built_before_the_lab():
    """Tornare alle scelte automatiche era «laggoso»: il mercato automatico veniva ricostruito (circa 0,4 secondi)."""
    at = at_step("review")
    cache = at.session_state["market_cache"]
    (auto_sig, (base, data, automatic)), = cache.items()
    assert automatic is True
    at = click(at, "to-lab")
    at.pills(key="cats_sectors").set_value(["technology", "healthcare"]).run()
    at.session_state["lab_section"] = "returns"
    at.run()
    custom = [sig for sig, entry in at.session_state["market_cache"].items() if not entry[2]]
    assert custom and auto_sig in at.session_state["market_cache"], "il mercato personalizzato non scalza quello automatico"
    at = click(at, "lab-reset")
    assert at.session_state["step"] == "review" and not at.exception
    cache = at.session_state["market_cache"]
    assert cache[auto_sig][0] is base and cache[auto_sig][1] is data, "nessuna ricostruzione: stesso mercato di prima"
    assert [sig for sig, entry in cache.items() if entry[2]] == [auto_sig]


def test_market_cache_is_bounded():
    from ui.market_tab import CACHE_SIZE
    at = click(at_step("review"), "to-lab")
    for sectors in (["technology"], ["healthcare"], ["energy"], ["financials"], ["utilities"], ["technology", "energy"]):
        at.pills(key="cats_sectors").set_value(sectors).run()
        at.session_state["lab_section"] = "returns"
        at.run()
        at.session_state["lab_section"] = "universe"
        at.run()
    entries = at.session_state["market_cache"].values()
    assert sum(1 for e in entries if not e[2]) <= CACHE_SIZE and sum(1 for e in entries if e[2]) <= 1


# ------------------------------------------------------------------ evoluzione e piano
def test_full_flow_produces_a_validated_plan_with_a_recorded_evolution():
    at = run_to_plan(at_step("review", contribution=12_000.0))      # con l'inflazione del 2% serve un piano meno ambizioso
    assert not at.exception and at.session_state["step"] == "plan"
    run = at.session_state["result"]
    assert run.report.ga.feasible and run.report.oos is not None
    trace = run.trace
    assert trace["F"] >= 2 and trace["generations"] == run.report.ga.generations
    assert trace["pr"][-1] == pytest.approx(run.report.ga.pr)
    from goalga.universe import universe_size
    assert run.data.evaluated == universe_size() and run.data.eligible > len(run.data.requested) > 40
    assert run.spec["market"]["source"] == "market" and run.spec["market"]["universe"] == run.data.requested
    page = html_of(at)
    assert 'class="gx-ring' in page and "futuri su 100" in page and t("plan.badge.ok", target=90) in page
    assert t("risk.balanced.name") in page
    assert "Yahoo" not in page, "il fornitore dei dati non compare nell'interfaccia"


def test_evolution_cannot_be_skipped_or_replayed():
    at = at_step("review")
    click(at, "cta-btn")
    assert at.session_state["step"] == "evolve"
    assert set(keys(at)) == {"acct-btn", "cta-late-btn"}, "solo «scopri il tuo piano»: niente salta né rivedi"
    assert all(b.label not in ("Salta", "Rivedi l'evoluzione") for b in at.button)
    at = click(at, "cta-late-btn")
    assert at.session_state["step"] == "plan" and "plan-replay" not in keys(at)
    at = set_step(at, "evolve")
    assert at.session_state["step"] == "plan", "una volta finita l'evoluzione non si rivede"


def test_the_result_is_reused_when_nothing_changed(monkeypatch):
    import ui.engine as engine
    calls = []
    real = engine.optimize
    monkeypatch.setattr(engine, "optimize", lambda *a, **k: calls.append(1) or real(*a, **k))
    at = run_to_plan()
    assert len(calls) == 1
    at = set_step(at, "evolve")                      # già vista: si torna al piano senza ricalcolare
    assert at.session_state["step"] == "plan" and len(calls) == 1
    at = click(at, "plan-edit")                      # modifica: cambia il piano → nuovo calcolo
    assert at.session_state["step"] == "start"
    at.text_input(key="in_w0").set_value("90k").run()
    at = run_to_plan(set_step(at, "review"))
    assert len(calls) == 2 and at.session_state["result"].plan.w0 == 90_000


def test_the_search_runs_again_after_changing_the_risk_profile():
    at = run_to_plan(at_step("review"))
    first = at.session_state["result"]
    at = click(at, "wi-btn-cautious")                # «E con un altro livello di rischio?»
    assert at.session_state["step"] == "evolve" and at.session_state["risk"] == "cautious"
    at = click(at, "cta-late-btn")
    second = at.session_state["result"]
    assert second.sig != first.sig and second.max_level == 3 and not at.exception
    assert second.ga_config.seed == first.ga_config.seed and second.data.requested == first.data.requested, \
        "il confronto tra profili avviene a parità di seed e di asset: cambia solo il rischio"


# ------------------------------------------------------------------ seed e universo a ogni avvio
def test_every_launch_uses_a_fresh_seed_and_draws_a_different_pool():
    """Rilanciare gli stessi obiettivi e lo stesso profilo non ripropone il piano in cache: si ricalcola."""
    at = run_to_plan(at_step("review"))
    first = at.session_state["result"]
    at = run_to_plan(set_step(at, "review"))
    second = at.session_state["result"]
    assert second.ga_config.seed != first.ga_config.seed and second.sig != first.sig
    assert second.data.requested != first.data.requested, "un nuovo seed estrae altre azioni dall'universo"
    funds = lambda run: {x for x in run.data.requested if x in {"XEON.MI", "SPY", "IHYG.MI"}}   # noqa: E731
    assert funds(first) == funds(second) == {"XEON.MI", "SPY", "IHYG.MI"}, "i fondi idonei entrano sempre"
    assert not at.exception


def test_goals_are_in_todays_euros_with_two_percent_inflation_by_default_and_the_pages_say_so():
    at = at_step("review")
    page = html_of(at)
    assert html.escape(t("review.inflation_value", pct="2,0%")) in page and html.escape(t("review.inflation_sub")) in page
    at = run_to_plan(at)
    run = at.session_state["result"]
    assert run.plan.inflation == pytest.approx(0.02) and run.spec["plan"]["inflation"] == pytest.approx(0.02)
    assert html.escape(t("plan.note.infl", pct="2,0%")) in html_of(at)
    flows = run.plan.flows()
    assert flows.goals[7] == pytest.approx(40_000 * 1.02**8), "l'obiettivo di 40.000 € tra otto anni vale 46.866 € nominali"


def test_with_no_inflation_the_amounts_are_nominal_and_the_pages_say_that_instead():
    at = at_step("review", use_advanced=True, infl_pct=0.0)
    assert html.escape(t("review.inflation_none")) in html_of(at)
    at = run_to_plan(at)
    assert html.escape(t("plan.note.nominal")) in html_of(at)
    assert at.session_state["result"].plan.inflation == 0.0


def test_automatic_mode_evaluates_the_whole_universe_and_uses_stocks_from_every_sector():
    at = run_to_plan(at_step("review", risk="dynamic"))
    run = at.session_state["result"]
    from goalga.selection import MIN_POSITION, MIN_STOCK_POSITION, split_pool
    from goalga.universe import catalog
    funds, stocks = split_pool(list(run.market.names))
    table = catalog()
    assert len(funds) >= 39 and len(stocks) >= 30
    assert {table.at[s, "Categoria"] for s in stocks} >= {"technology", "healthcare", "energy", "financials", "utilities"}
    assert run.market.meta["basket"]["min_share"] == pytest.approx(0.30)
    weights = run.market.weights_frame()
    top = weights.iloc[:, -1]
    assert top[stocks].sum() > 0.1, "nel portafoglio più dinamico le azioni singole pesano davvero"
    assert not ((weights.loc[funds] > 1e-9) & (weights.loc[funds] < MIN_POSITION - 1e-7)).to_numpy().any()
    assert not ((weights.loc[stocks] > 1e-9) & (weights.loc[stocks] < MIN_STOCK_POSITION - 1e-7)).to_numpy().any(), \
        "nessuna posizione troppo piccola per essere acquistata"
    assert t("plan.badge.universe", evaluated="3.477", picked=str(len(run.data.requested)), start="x", end="y").split("·")[0] \
        in html_of(at)


def test_previews_and_the_following_search_share_the_same_seed():
    at = at_step("risk")
    seed = at.session_state["seed_next"]
    assert at.session_state["risk_previews"] and not at.exception
    at = run_to_plan(set_step(at, "review"))
    run = at.session_state["result"]
    assert run.ga_config.seed == seed, "la ricerca usa il seed delle anteprime (la breve è un prefisso della completa)"
    assert at.session_state["seed_next"] != seed, "e il prossimo avvio ne estrarrà uno nuovo"
    final = {p.key: p for p in run.previews}[run.risk]
    assert run.report.ga.pr >= final.pr - 1e-12


def test_a_fixed_seed_reproduces_the_same_plan_and_reuses_the_cached_result(monkeypatch):
    import ui.engine as engine
    calls = []
    real = engine.optimize
    monkeypatch.setattr(engine, "optimize", lambda *a, **k: calls.append(1) or real(*a, **k))
    at = at_step("review", use_advanced=True, seed_fixed=True, seed=777)
    at = run_to_plan(at)
    first = at.session_state["result"]
    assert first.ga_config.seed == 777 and len(calls) == 1
    at = click(set_step(at, "review"), "cta-btn")
    assert at.session_state["step"] == "plan", "stesso seed e stessi dati: si torna subito al piano, senza rivedere l'evoluzione"
    assert at.session_state["result"] is first and len(calls) == 1


def test_infeasible_plan_explains_why_and_suggests_what_to_change():
    at = at_step("review", w0=1_000.0, contribution=1_200.0)
    at = run_to_plan(at)
    assert not at.exception
    run = at.session_state["result"]
    assert run.report.ga.feasible is False
    from ui.result import outcome
    o = outcome(run)
    assert not o["ok"] and "non è raggiungibile" in o["lead"] and "ridurne l'importo" in o["lead"]
    assert t("plan.badge.warn", target=90) in html_of(at)


def test_the_comparison_keeps_labels_values_and_bars_in_separate_columns():
    """Con una strategia sotto soglia le etichette a sinistra delle barre non devono sovrapporsi ai valori."""
    from ui.result import compare_html
    rows = [{"label": "La tua strategia", "irr": 0.012, "pr": 0.42, "ok": False, "you": True},
            {"label": "Tutto prudente", "irr": -0.05, "pr": 0.0, "ok": False, "you": False},
            {"label": "Mix costante migliore", "irr": 0.03, "pr": 0.95, "ok": True, "you": False}]
    page = compare_html(rows)
    assert page.count('<div class="row') == 3 and page.count('<div class="lbl">') == 3
    assert page.count('<div class="bar">') == 3 and page.count('<div class="val">') == 3
    assert page.count(" dim") == 2 and 'class="row you dim"' in page
    for chunk in page.split('<div class="row')[1:]:
        assert chunk.index('class="lbl"') < chunk.index('class="bar"') < chunk.index('class="val"')
        assert '<div class="lbl"><' not in chunk, "l'etichetta contiene solo testo"
    assert t("plan.cmp.below") in page


def test_plan_page_offers_composition_downloads_and_navigation():
    at = run_to_plan()
    assert {"plan-edit", "plan-lab", "to-holdings", "save-guest"} <= set(keys(at)) and not at.exception
    assert [k for k in keys(at) if k.startswith("wi-btn-")] == ["wi-btn-cautious", "wi-btn-balanced", "wi-btn-dynamic"]
    assert "gx-link-card" in html_of(at) and t("plan.holdings.title") in html_of(at)


# ------------------------------------------------------------------ composizione nel tempo
def hrows(page: str) -> int:
    """Righe dell'elenco dei titoli dell'anno (quelle delle azioni singole sono compatte)."""
    return len(re.findall(r'class="gx-hrow(?: sm)?"', page))


def test_holdings_page_lists_the_exact_assets_year_by_year():
    at = run_to_plan()
    at = click(at, "to-holdings")
    assert at.session_state["step"] == "holding" + "s" and not at.exception
    page = html_of(at)
    run = at.session_state["result"]
    assert page.count('class="gx-phase"') >= 1 and "gx-donut" in page and "gx-hlist" in page and "gx-heat" in page
    first_year = run.report.composition.iloc[0]
    for ticker in first_year[first_year > 0.0005].index:
        assert ticker in page, "ogni asset presente nell'anno compare con il suo ticker"
    assert hrows(page) == int((first_year > 0.0005).sum())
    at = click(at, "back-holdings")
    assert at.session_state["step"] == "plan"


def test_holdings_page_shows_single_stocks_in_their_own_group_with_their_tickers():
    from goalga.selection import split_pool
    goals = [dict(GOALS[0]), {**GOALS[1], "amount": 450_000.0}]           # obiettivo ambizioso: serve più rischio
    at = run_to_plan(at_step("review", risk="dynamic", goals=goals))
    at = click(at, "to-holdings")
    run = at.session_state["result"]
    comp = run.report.composition
    stocks = split_pool(list(comp.columns))[1]
    year = int(comp[stocks].sum(axis=1).idxmax())
    held = [x for x in stocks if comp.loc[year, x] > 0.0005]
    assert held, "con un obiettivo ambizioso il piano investe anche in azioni singole"
    at.select_slider(key=f"hold_year_{run.plan.horizon}").set_value(year).run()
    page = html_of(at)
    assert page.count('class="gx-hrow sm"') == len(held) and all(x in page for x in held)
    assert html.escape(f"{t('cat.stocks')} · {len(held)}") in page
    groups = re.findall(r'<div class="gx-hgroup"[^>]*><span>([^<]*)</span>', page)
    assert len(groups) == len(set(groups)) > 1, "un solo gruppo per categoria"


def test_holdings_year_slider_changes_the_displayed_portfolio():
    at = run_to_plan()
    at = click(at, "to-holdings")
    run = at.session_state["result"]
    horizon = run.plan.horizon
    slider = at.select_slider(key=f"hold_year_{horizon}")
    slider.set_value(horizon).run()
    last = run.report.composition.iloc[-1]
    assert hrows(html_of(at)) == int((last > 0.0005).sum()) and not at.exception


# ------------------------------------------------------------------ account
def test_guest_is_invited_to_sign_in_from_the_plan_and_comes_back():
    at = run_to_plan()
    at = click(at, "save-guest")
    assert at.session_state["step"] == "account" and "back-account" in keys(at)
    assert {"su_name", "su_email", "su_password", "su_password2"} <= {w.key for w in at.text_input}
    at = click(at, "back-account")
    assert at.session_state["step"] == "plan"


def test_sign_up_saves_the_plan_and_the_portfolio_appears_in_the_personal_space():
    at = run_to_plan()
    at = sign_up(at.session_state["step"] == "plan" and click(at, "save-guest") or at)
    assert not at.exception and at.session_state["step"] == "plan", "dopo la registrazione si torna al piano"
    assert at.session_state["user"]["email"] == "mario@example.com" and "save-new" in keys(at)
    at = click(at, "save-new")
    pid = at.session_state["saved_portfolio"]
    assert "save-version" in keys(at) and not at.exception
    from ui import account
    service = account.svc()
    pf = service.get_portfolio(at.session_state["user"]["id"], pid)
    assert pf.invested and pf.start_date is not None and pf.ref_weights, "per impostazione predefinita lo si segue"
    assert [b.label for b in at.button if b.key == "acct-btn"] == ["Mario"]
    at = click(at, "acct-btn")
    assert at.session_state["step"] == "account" and f"pf-comp-{pid}" in keys(at)
    assert t("acct.pf.status.following") in html_of(at) or any(t("acct.pf.status.following") in m.value for m in at.markdown)


def test_sign_up_errors_are_shown_and_nobody_gets_logged_in():
    at = at_step("account")
    at = sign_up(at, password=PASSWORD, again="something else!")
    assert "user" not in at.session_state and t("acct.err.password_mismatch") in texts(at)
    at = sign_up(at, password="short", again="short")
    assert "user" not in at.session_state and any("8" in e.value for e in at.error)
    at = sign_up(at)
    assert at.session_state["user"]["name"] == "Mario"
    at = click(at, "signout")
    assert "user" not in at.session_state and at.session_state["step"] == "welcome"
    at = set_step(at, "account")
    at = sign_up(at)                                         # stessa email
    assert "user" not in at.session_state and t("acct.err.email_taken") in texts(at)


def test_sign_in_checks_the_password_and_restores_the_saved_language():
    at = at_step("account")
    at.selectbox(key="lang_pick").set_value("fr").run()
    at = sign_up(at, email="ana@example.com", name="Ana")
    assert at.session_state["user"]["locale"] == "fr"
    at = click(at, "signout")
    at.selectbox(key="lang_pick").set_value("zh").run()
    at = set_step(at, "account")
    at.text_input(key="si_email").set_value("ana@example.com").run()
    at.text_input(key="si_password").set_value("wrong password!").run()
    at = click(at, "si_submit")
    assert "user" not in at.session_state and t("acct.err.invalid_credentials", lang="zh") in texts(at)
    at.text_input(key="si_password").set_value(PASSWORD).run()
    at = click(at, "si_submit")
    assert at.session_state["user"]["email"] == "ana@example.com" and at.session_state["lang"] == "fr"


def test_saved_portfolio_composition_can_be_opened_from_the_account():
    at = run_to_plan()
    at = sign_up(click(at, "save-guest"))
    at = click(at, "save-new")
    pid = at.session_state["saved_portfolio"]
    at = click(at, "acct-btn")
    at = click(at, f"pf-comp-{pid}")
    assert at.session_state["step"] == "holdings" and at.session_state["holdings_pf"] == pid and not at.exception
    assert "gx-hrow" in html_of(at)
    at = click(at, "back-holdings")
    assert at.session_state["step"] == "account"


def test_editing_a_followed_portfolio_saves_a_new_version_and_alerts_if_weights_change():
    from ui import account
    at = run_to_plan()
    at = sign_up(click(at, "save-guest"))
    at = click(at, "save-new")
    pid = at.session_state["saved_portfolio"]
    saved_spec = account.svc().current_version(pid).spec
    at = click(at, "acct-btn")
    at = click(at, f"pf-edit-{pid}")
    assert at.session_state["step"] == "start" and at.session_state["editing_portfolio"] == pid
    assert at.session_state["w0"] == 50_000 and len(at.session_state["goals"]) == 2
    at.pills(key="chip-w0").set_value(250_000).run()
    at = run_to_plan(set_step(at, "review"))
    assert "save-version" in keys(at)
    edited = at.session_state["result"]
    assert edited.ga_config.seed == saved_spec["ga"]["seed"] and edited.data.requested == saved_spec["market"]["universe"], \
        "modificare il piano non rimescola gli asset: la prima ricerca dopo il caricamento riusa seed e pool salvati"
    at = click(at, "save-version")
    service = account.svc()
    me = at.session_state["user"]
    versions = service.versions(me["id"], pid)
    assert [v.number for v in versions] == [2, 1] and versions[0].reason == "edited"
    assert versions[0].spec["plan"]["w0"] == 250_000
    changed = service.list_alerts(me["id"])
    assert (len(changed) == 1) == (changed[:1] != [] and changed[0].kind == "weights"), "un avviso solo se i pesi cambiano"
    again = run_to_plan(set_step(at, "review")).session_state["result"]
    assert again.ga_config.seed != edited.ga_config.seed, "dal secondo avvio in poi si estrae di nuovo"


def _followed_for(days: int):
    """Portafoglio seguito da ``days`` giorni (l'inizio dell'investimento viene arretrato nell'archivio)."""
    from datetime import date, timedelta

    from sqlalchemy import update

    from goalga.accounts.db import portfolios
    from ui import account
    at = run_to_plan()
    at = sign_up(click(at, "save-guest"))
    at = click(at, "save-new")
    pid = at.session_state["saved_portfolio"]
    service = account.svc()
    start = date.today() - timedelta(days=days)
    with service.db.begin() as conn:
        conn.execute(update(portfolios).where(portfolios.c.id == pid).values(start_date=start))
    return at, pid, start, service


def test_editing_after_some_time_restarts_from_the_plan_that_is_left_and_does_not_restart_the_clock():
    """Il piano mostrato in modifica parte da oggi (capitale stimato, anni residui) e salvarlo non sposta le scadenze."""
    from datetime import date

    from goalga.accounts.payload import elapsed_years, fan_value, year_fraction
    from goalga.pipeline import spec_plan
    from ui import format as fmt
    at, pid, start, service = _followed_for(int(2.4 * 365))
    before = service.current_version(pid)
    at = click(click(at, "acct-btn"), f"pf-edit-{pid}")
    assert at.session_state["step"] == "start" and at.session_state["editing_portfolio"] == pid and not at.exception
    ss = at.session_state
    assert [(g["start"], g["end"]) for g in ss["goals"]] == [(6, 6), (23, 23)], "gli anni sono contati da oggi: 8-2 e 25-2"
    expected = fan_value(before.result, "p50", elapsed_years(start, date.today()), spec_plan(before.spec).flows().net)
    assert ss["w0"] == pytest.approx(expected, abs=1) and ss["w0"] != 50_000
    assert ss["plan_fp"] == pytest.approx(1 - year_fraction(start, date.today())) and 0.5 < ss["plan_fp"] < 0.7
    note = t("acct.edit.note_projection", name=ss["edit_note"]["name"], value=fmt.eur(ss["w0"]))
    assert html.escape(note) in html_of(at), "la pagina dice da dove arriva il capitale"
    at = run_to_plan(set_step(at, "review"))
    run = at.session_state["result"]
    assert run.plan.first_period == pytest.approx(ss["plan_fp"]) and run.plan.horizon == 23
    assert run.spec["plan"]["first_period"] == pytest.approx(ss["plan_fp"])
    assert "save-version" in keys(at) and "save-as-new" not in keys(at), "un piano che riparte a metà anno vale solo qui"
    at = click(at, "save-version")
    saved = service.current_version(pid)
    assert saved.number == 2 and saved.result["anchor"] == 2 and saved.result["horizon"] == 23
    assert saved.result["first_period"] == pytest.approx(ss["plan_fp"]) and not at.exception


def test_a_portfolio_with_the_alerts_off_is_edited_from_the_plan_that_is_left_too():
    at, pid, start, service = _followed_for(int(2.4 * 365))
    service.set_invested(at.session_state["user"]["id"], pid, False)
    at = click(click(at, "acct-btn"), f"pf-edit-{pid}")
    ss = at.session_state
    assert [(g["start"], g["end"]) for g in ss["goals"]] == [(6, 6), (23, 23)] and 0.5 < ss["plan_fp"] < 0.7
    at = click(run_to_plan(set_step(at, "review")), "save-version")
    assert service.current_version(pid).result["anchor"] == 2 and not at.exception


def test_editing_a_portfolio_in_its_first_year_keeps_the_saved_plan_and_the_whole_first_year():
    at, pid, start, service = _followed_for(0)
    at = click(click(at, "acct-btn"), f"pf-edit-{pid}")
    ss = at.session_state
    assert [(g["start"], g["end"]) for g in ss["goals"]] == [(8, 8), (25, 25)] and ss["w0"] == 50_000
    assert ss["plan_fp"] == 1.0, "nel giorno dell'inizio non c'è nessun anno parziale"
    at = run_to_plan(set_step(at, "review"))
    assert "save-as-new" in keys(at), "un piano normale si può salvare anche come nuovo portafoglio"


def test_the_last_year_of_a_plan_cannot_be_edited_and_says_why():
    at, pid, start, service = _followed_for(int(24.5 * 365))
    at = click(click(at, "acct-btn"), f"pf-edit-{pid}")
    assert at.session_state["step"] == "account" and "edit_note" not in at.session_state
    assert t("acct.edit.nothing_left") in texts(at)


def test_a_plan_that_restarts_mid_year_cannot_be_saved_as_a_new_portfolio_from_a_fresh_start():
    at = run_to_plan(at_step("review", plan_fp=0.6))
    at = sign_up(click(at, "save-guest"))
    at = click(at, "save-new")
    assert t("acct.save.partial") in texts(at) and "saved_portfolio" not in at.session_state


def test_deleting_a_portfolio_asks_for_confirmation():
    at = run_to_plan()
    at = sign_up(click(at, "save-guest"))
    at = click(at, "save-new")
    pid = at.session_state["saved_portfolio"]
    at = click(at, "acct-btn")
    at = click(at, f"pf-del-{pid}")
    assert f"pf-del-yes-{pid}" in keys(at) and f"pf-del-no-{pid}" in keys(at)
    at = click(at, f"pf-del-no-{pid}")
    assert f"pf-comp-{pid}" in keys(at)
    at = click(click(at, f"pf-del-{pid}"), f"pf-del-yes-{pid}")
    assert f"pf-comp-{pid}" not in keys(at) and not at.exception


# ------------------------------------------------------------------ lingue
@pytest.mark.parametrize("lang", list(LANGS))
def test_every_screen_renders_in_every_language(lang, monkeypatch):
    # AppTest valuta i format_func dei widget nel thread del test: la lingua predefinita deve coincidere con la pagina
    monkeypatch.setenv("GOALGA_DEFAULT_LANG", lang)
    at = run_app()
    assert at.session_state["lang"] == lang, "si parte nella lingua predefinita"
    at.selectbox(key="lang_pick").set_value(lang).run()
    assert not at.exception and at.button(key="cta-home-btn").label == t("welcome.cta", lang=lang)
    pages = {}
    for step in ("start", "goals", "risk", "review", "account", "lab"):
        at.session_state["step"] = step
        for key, value in (plan_state() if step not in ("start", "account") else {}).items():
            at.session_state[key] = value
        at.run()
        assert not at.exception, (lang, step)
        pages[step] = html_of(at)
    assert t("review.gauge.title", lang=lang) in pages["review"]
    assert t("risk.balanced.name", lang=lang) in pages["risk"] and t("acct.eyebrow", lang=lang) in pages["account"]
    for section in ("universe", "returns", "portfolios", "search", "checks", "method"):
        at.session_state["lab_section"] = section
        assert not at.run().exception, (lang, section)


def switch_language(at: AppTest, lang: str) -> AppTest:
    """Cambia lingua dal selettore (i format_func vanno valutati nella lingua con cui la pagina era stata disegnata)."""
    with i18n.use(at.session_state["lang"]):
        return at.selectbox(key="lang_pick").set_value(lang).run()


def test_language_can_be_switched_on_the_plan_without_recomputing(monkeypatch):
    import ui.engine as engine
    calls = []
    real = engine.optimize
    monkeypatch.setattr(engine, "optimize", lambda *a, **k: calls.append(1) or real(*a, **k))
    at = run_to_plan()
    for lang in LANGS:
        switch_language(at, lang)
        assert not at.exception, lang
        assert at.session_state["step"] == "plan" and t("plan.holdings.title", lang=lang) in html_of(at)
    for step in ("holdings", "account"):
        for lang in ("en", "ru", "zh"):
            switch_language(at, lang)
            with i18n.use(lang):
                at = set_step(at, step)
            assert not at.exception, (lang, step)
    assert len(calls) == 1


def test_the_page_language_is_declared_for_browsers_and_screen_readers():
    at = run_app()
    at.selectbox(key="lang_pick").set_value("ru").run()
    page = html_of(at)
    assert '<span data-lang="ru" data-gx-hide></span>' in page and 'd.lang="ru"' in page
    assert page.count("window.__gx = {v: VERSION") == 1, "i comportamenti del browser sono nello stesso script, caricati una volta"


# ------------------------------------------------------------------ configurazione avanzata
class StateView:
    """Vista in sola lettura dello stato di AppTest con l'interfaccia di un dizionario usata dal codice dell'app."""

    def __init__(self, at: AppTest) -> None:
        self.at = at

    def get(self, key, default=None):
        try:
            return self.at.session_state[key]
        except KeyError:
            return default

    def __contains__(self, key) -> bool:
        return key in self.at.session_state

    def __getitem__(self, key):
        return self.at.session_state[key]


LAB_SECTIONS = ("universe", "returns", "portfolios", "search", "checks", "method")


def lab(section: str, **state) -> AppTest:
    at = at_step("lab", use_advanced=True, **state)
    at.session_state["lab_section"] = section
    return at.run()


def manual_picks(stocks: int = 2) -> list[str]:
    """Etichette «TICKER · Nome» di asset idonei per provare la scelta a mano: un fondo per classe e qualche titolo."""
    from goalga import snapshot
    from goalga.selection import get_screen
    found = get_screen(snapshot.load_prices(), 10.0).eligible()
    funds = found[found["Tipo"] == "fund"]
    picks = [group.index[0] for _, group in funds.groupby("Categoria")]
    picks += list(found.index[found["Tipo"] == "stock"][:stocks])
    return [f"{x} · {found.at[x, 'Nome']}" for x in picks]


def page_text(at: AppTest) -> str:
    """Tutto il testo della pagina: HTML, markdown, messaggi ed etichette dei widget."""
    groups = (at.slider, at.number_input, at.toggle, at.button, at.pills, at.segmented_control, at.multiselect,
              at.selectbox, at.select_slider)
    labels = [getattr(w, "label", "") or "" for group in groups for w in group]
    return " ".join([html_of(at), texts(at), *(m.value for m in at.markdown), *labels])


def test_advanced_settings_are_applied_and_can_be_reset():
    from ui.lab import is_customized_from
    at = lab("search")
    assert not is_customized_from(StateView(at))
    at.slider(key="pop_size").set_value(60).run()
    at.slider(key="p_m").set_value(0.2).run()
    assert not at.exception
    at = click(at, "cta-lab-btn")                    # Applica e rilancia
    assert at.session_state["step"] == "evolve" and not at.exception
    run = at.session_state["result"]
    assert run.ga_config.pop_size == 60 and run.ga_config.p_m == pytest.approx(0.2)
    assert run.trace["pop_size"] == 60 and run.spec["advanced"] is True
    assert is_customized_from(StateView(at))
    at = set_step(at, "lab")
    at = click(at, "lab-reset")
    assert at.session_state["pop_size"] == 100 and not is_customized_from(StateView(at))
    assert at.session_state["use_advanced"] is False, "dopo il ripristino si torna alle impostazioni automatiche"
    assert at.session_state["step"] == "review", "e si esce dall'area avanzata"


def test_the_lab_is_a_five_step_guide_with_next_and_back_buttons():
    from ui.lab import NUMBERED
    at = lab(NUMBERED[0])
    assert "lab-prev" not in keys(at) and "lab-next" in keys(at)
    for index, section in enumerate(NUMBERED):
        assert at.session_state["lab_section"] == section and not at.exception, section
        assert f'<div class="no">{index + 1}</div>' in html_of(at), f"il passo {index + 1} si apre con la sua guida"
        if index < len(NUMBERED) - 1:
            at = click(at, "lab-next")
    assert "lab-next" not in keys(at) and "lab-prev" in keys(at)
    at = click(at, "lab-prev")
    assert at.session_state["lab_section"] == NUMBERED[-2]


def test_every_lab_section_has_no_uploads_no_synthetic_data_and_no_data_provider_name():
    for section in LAB_SECTIONS:
        at = lab(section)
        assert not at.exception, section
        assert not list(at.file_uploader), (section, "nessun caricamento di file")
        page = page_text(at).lower()
        for banned in ("yahoo", "sintetic", "csv", "excel", "xlsx"):
            assert banned not in page, (section, banned)


def test_no_help_popup_cites_the_paper_and_the_search_parameters_are_explained():
    for section in LAB_SECTIONS:
        at = lab(section)
        widgets = [*at.slider, *at.number_input, *at.select_slider, *at.toggle, *at.button, *at.text_input,
                   *at.selectbox, *at.multiselect, *at.text_area]
        helps = [w.help for w in widgets if getattr(w, "help", None)]
        assert not [h for h in helps if re.match(r"\s*paper\b", h, re.I)], (section, helps)
    at = lab("search")
    assert at.slider(key="pop_size").help and "100" in at.slider(key="pop_size").help


def test_the_universe_step_shows_the_funnel_and_lists_the_assets_by_category():
    from goalga.universe import CATEGORIES, catalog
    from ui import format as fmt
    at = lab("universe")
    page = html_of(at)
    assert not at.exception and 'class="gx-funnel"' in page and fmt.number(len(catalog())) in page, \
        "l'imbuto dice quanti asset sono stati valutati, quanti sono idonei e quanti usati"
    assert len(at.pills(key="cats_funds").options) + len(at.pills(key="cats_sectors").options) == len(CATEGORIES)
    picker = at.selectbox(key="browse_cat")
    assert len(picker.options) == len(CATEGORIES)
    at = at.selectbox(key="browse_cat").set_value("healthcare").run()
    frame = at.dataframe[0].value
    table = catalog()
    assert len(frame) > 0 and set(frame[t("lab.u.col_ticker")]) <= set(table.index[table["Categoria"] == "healthcare"])


def test_the_history_required_by_the_screen_changes_how_many_assets_are_eligible():
    from goalga import snapshot
    from goalga.selection import get_screen
    from ui import format as fmt
    prices = snapshot.load_prices()
    n10, n5 = get_screen(prices, 10.0).n_eligible, get_screen(prices, 5.0).n_eligible
    assert n5 > n10, "con meno storia richiesta idonea qualche titolo in più"
    at = lab("universe", min_years=5)
    assert not at.exception and f"<b>{fmt.number(n5)}</b>" in html_of(at)


def test_the_history_slider_stops_at_the_estimation_window_and_runs_record_the_position_rules():
    from goalga.selection import MAX_WINDOW_YEARS, MIN_POSITION, MIN_STOCK_POSITION
    at = lab("universe")
    slider = at.slider(key="min_years")
    assert (slider.min, slider.max) == (3, MAX_WINDOW_YEARS), "gli ultimi anni, senza i primi mesi errati degli ETF giovani"
    at = click(at, "cta-lab-btn")
    market = at.session_state["result"].spec["market"]
    assert market["min_position"] == MIN_POSITION and market["min_stock_position"] == MIN_STOCK_POSITION
    assert market["max_years"] == MAX_WINDOW_YEARS and not at.exception


def test_a_saved_spec_asking_for_more_history_than_the_window_allows_loads_within_the_slider_range():
    from goalga.selection import MAX_WINDOW_YEARS

    def script():
        import streamlit as st

        from ui.state import apply_spec, init_state
        init_state()
        apply_spec({"plan": {"w0": 1000.0, "contribution": 100.0, "horizon": 10, "last_contribution_year": 9, "goals": []},
                    "advanced": True, "risk": "balanced", "market": {"min_years": 18}})
        st.session_state["loaded_min_years"] = st.session_state["min_years"]

    at = AppTest.from_function(script).run()
    assert not at.exception and at.session_state["loaded_min_years"] == MAX_WINDOW_YEARS


def test_category_shortcuts_select_all_or_none_and_the_app_warns_when_no_fund_is_left():
    from goalga.universe import FUND_CATEGORIES
    at = lab("universe")
    at = click(at, "cats_funds-none")
    assert at.session_state["cats_funds"] == [] and t("lab.u.no_funds") in texts(at) and not at.exception
    at = click(at, "cats_funds-all")
    assert t("lab.u.no_funds") not in texts(at) and at.session_state["cats_funds"] == list(FUND_CATEGORIES)


def test_choosing_categories_restricts_the_pool_to_them():
    from goalga.selection import split_pool
    from goalga.universe import catalog
    from ui.lab import changed_groups
    at = lab("universe")
    at.pills(key="cats_sectors").set_value(["technology", "healthcare"]).run()
    assert not at.exception and changed_groups(StateView(at)) == ["universe"]
    at = click(at, "cta-lab-btn")
    run = at.session_state["result"]
    funds, stocks = split_pool(run.data.requested)
    assert len(funds) >= 39, "i fondi restano tutti"
    assert stocks and {catalog().at[s, "Categoria"] for s in stocks} <= {"technology", "healthcare"}
    assert run.spec["market"]["categories"] and "energy" not in run.spec["market"]["categories"]


def test_excluded_assets_never_enter_the_pool():
    from goalga.selection import split_pool
    from goalga.universe import catalog
    at = lab("universe", seed_fixed=True, seed=777)
    at = click(at, "cta-lab-btn")
    stock = split_pool(at.session_state["result"].data.requested)[1][0]
    at = set_step(at, "lab")
    at.multiselect(key="excluded_sel").set_value([f"{stock} · {catalog().at[stock, 'Nome']}"]).run()
    assert not at.exception
    at = click(at, "cta-lab-btn")
    run = at.session_state["result"]
    assert stock not in run.data.requested and stock in run.spec["market"]["excluded"]


def test_the_number_of_stocks_and_their_share_are_adjustable():
    from goalga.selection import split_pool
    at = lab("universe", seed_fixed=True, seed=11, pool_stocks=50, stock_share_pct=50)
    at = click(at, "cta-lab-btn")
    run = at.session_state["result"]
    assert len(split_pool(run.data.requested)[1]) == 50
    assert run.market.meta["basket"]["min_share"] == pytest.approx(0.5)
    at = lab("universe", seed_fixed=True, seed=11, pool_stocks=0)
    at = click(at, "cta-lab-btn")
    run = at.session_state["result"]
    assert split_pool(run.data.requested)[1] == [] and not run.market.meta.get("basket")


def test_manual_mode_uses_exactly_the_chosen_assets_without_the_stock_basket():
    picks = manual_picks()
    at = lab("universe", pool_mode="manual")
    assert not at.exception and t("lab.u.pick_more", n=0, min=5) in texts(at)
    at.multiselect(key="manual_sel").set_value(picks).run()
    assert not at.exception and "lab.u.pick_more" not in texts(at) and t("lab.u.pick_more", n=0, min=5) not in texts(at)
    at = click(at, "cta-lab-btn")
    run = at.session_state["result"]
    wanted = [p.split(" · ")[0] for p in picks]
    assert run.data.requested == wanted and set(run.market.names) == set(wanted)
    assert not run.market.meta.get("basket") and run.spec["market"]["mode"] == "manual"
    assert run.spec["market"]["stock_share"] == 0.0 and run.spec["market"]["class_caps"] is False


def test_the_assets_picked_by_hand_can_be_reset_and_replaced_by_the_funds_only():
    picks = manual_picks(stocks=0)
    at = lab("universe", pool_mode="manual", manual_sel=picks[:3])
    assert t("lab.u.pick_more", n=3, min=5) in texts(at)
    at = click(at, "pick-funds")
    assert len(at.session_state["manual_sel"]) >= 39
    at = click(at, "pick-none")
    assert at.session_state["manual_sel"] == []


def test_returns_step_shows_the_resulting_range_and_the_outlook_moves_every_expected_return():
    from ui.lab import changed_groups
    at = lab("returns", seed_fixed=True, seed=777)
    assert not at.exception and "returns" not in changed_groups(StateView(at))
    assert t("lab.r.result_low") in html_of(at) and t("lab.r.result_high") in html_of(at)
    at = click(at, "cta-lab-btn")
    base = at.session_state["result"].market
    at = set_step(at, "lab")
    at.select_slider(key="outlook_pt").set_value(1.0).run()
    assert not at.exception and "returns" in changed_groups(StateView(at))
    at = click(at, "cta-lab-btn")
    shifted = at.session_state["result"].market
    assert list(shifted.names) == list(base.names), "stesso seed e stesso pool: cambiano solo i rendimenti"
    assert np.allclose(np.asarray(shifted.mu) - np.asarray(base.mu), 0.01)


def test_class_assumptions_move_only_the_funds_of_that_class():
    from goalga.universe import catalog
    at = lab("returns", seed_fixed=True, seed=777)
    at = click(at, "cta-lab-btn")
    base = at.session_state["result"].market
    at = set_step(at, "lab")
    start = at.session_state["cls_dev_equity"]
    at.number_input(key="cls_dev_equity").set_value(start + 1.0).run()
    assert not at.exception
    at = click(at, "cta-lab-btn")
    shifted = at.session_state["result"].market
    table = catalog()
    delta = np.asarray(shifted.mu) - np.asarray(base.mu)
    moved = [n for n, d in zip(base.names, delta) if abs(d) > 1e-9]
    assert moved and all(table.at[n, "Categoria"] == "dev_equity" for n in moved)
    assert np.allclose(delta[delta != 0], 0.01)
    at = set_step(at, "lab")
    click(at, "cls-restore")
    assert at.session_state["cls_dev_equity"] == start


def test_historical_returns_come_with_a_warning_and_count_as_a_change():
    from ui.lab import changed_groups
    at = lab("returns", assump_source="historical")
    assert not at.exception and t("lab.r.hist_warning") in texts(at)
    assert "returns" in changed_groups(StateView(at))
    assert not [e for e in at.expander if t("lab.r.classes") in e.label], "le ipotesi per classe valgono solo di lungo periodo"


def test_the_portfolio_cap_is_respected_by_every_portfolio():
    at = lab("portfolios", max_weight_pct=25, seed_fixed=True, seed=5)
    assert not at.exception and len(at.get("plotly_chart")) == 2
    at = click(at, "cta-lab-btn")
    run = at.session_state["result"]
    assert np.asarray(run.market.weights).max() <= 0.25 + 1e-6
    assert run.spec["market"]["max_weight"] == pytest.approx(0.25)


def test_expert_options_of_the_portfolios_reach_the_spec():
    from goalga.market import METHODS
    other = next(m for m in METHODS if m != "annual")
    at = lab("portfolios", use_shrinkage=False, boot_method=other, seed_fixed=True, seed=5)
    assert not at.exception
    at = click(at, "cta-lab-btn")
    spec = at.session_state["result"].spec["market"]
    assert spec["shrinkage"] is False and spec["method"] == other


def test_custom_portfolio_weights_are_used_by_the_optimizer_in_manual_mode_only():
    at = lab("portfolios")
    assert "use_custom_weights" not in [w.key for w in at.toggle], "con la scelta automatica i pesi li decide l'app"
    at = lab("portfolios", pool_mode="manual", manual_sel=manual_picks())
    assert not at.exception
    at.toggle(key="use_custom_weights").set_value(True).run()
    assert not at.exception
    at = click(at, "cta-lab-btn")
    market = at.session_state["result"].market
    assert market.custom_weights is True and np.allclose(market.weights.sum(axis=0), 1.0)
    assert at.session_state["result"].spec["market"]["custom_weights"] is True


def test_effort_presets_set_the_search_parameters_and_say_when_they_are_customized():
    from ui.lab import effort_of
    from ui.state import EFFORTS
    at = lab("search")
    assert at.segmented_control(key="effort").value == "standard"
    at.segmented_control(key="effort").set_value("quick").run()
    assert not at.exception
    for key, value in EFFORTS["quick"].items():
        assert at.session_state[key] == value, key
    assert effort_of(StateView(at)) == "quick"
    at.slider(key="pop_size").set_value(90).run()
    assert effort_of(StateView(at)) is None and at.segmented_control(key="effort").value is None
    assert t("lab.s.effort_custom") in html_of(at)
    at = click(at, "ga-reset")
    assert effort_of(StateView(at)) == "standard" and at.session_state["pop_size"] == 100


def test_the_seed_can_be_fixed_in_the_search_step_and_is_reported_afterwards():
    at = lab("search")
    assert "seed" not in [w.key for w in at.number_input], "il campo compare solo con l'estrazione fissa"
    at.toggle(key="seed_fixed").set_value(True).run()
    assert "seed" in [w.key for w in at.number_input]
    before = at.session_state["seed"]
    next(b for b in at.button if b.label == t("lab.ga.reseed")).click().run()
    assert at.session_state["seed"] != before and not at.exception
    at.number_input(key="seed").set_value(2024).run()
    at = click(at, "cta-lab-btn")
    assert at.session_state["result"].ga_config.seed == 2024
    at = set_step(at, "lab")
    assert html.escape(t("lab.s.last_seed", seed=2024)) in html_of(at)


def test_changes_are_summarized_by_step():
    from ui.lab import changed_groups
    at = lab("search", outlook_pt=1.0, pool_stocks=10)
    assert changed_groups(StateView(at)) == ["universe", "returns"]
    page = html_of(at)
    assert t("lab.changed") in page and t("lab.section.universe") in page and t("lab.section.returns") in page
    at = lab("search")
    assert t("lab.all_auto") in html_of(at)


def test_the_analysis_step_asks_for_a_run_first_and_then_shows_the_detailed_report():
    at = lab("checks")
    assert t("lab.no_result") in texts(at) and not at.exception
    at = run_to_plan()
    at = click(at, "plan-lab")
    assert at.session_state["step"] == "lab" and at.session_state["lab_section"] == "checks"
    assert not at.exception
    assert len([m for m in at.markdown if 'class="gx-stat"' in m.value]) == 5
