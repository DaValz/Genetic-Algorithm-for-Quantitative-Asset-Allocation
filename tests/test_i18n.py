"""Test dell'internazionalizzazione: cataloghi completi, plurali, formati locali e testi traducibili."""
from __future__ import annotations

import ast
import pickle
import re
import threading
from pathlib import Path

import pytest

from goalga import i18n
from goalga.accounts.security import AccountError
from goalga.i18n import LANGS, Msg, check, fmt, plural_category, t, tn

ROOT = Path(__file__).resolve().parent.parent
OTHER_LANGS = [code for code in LANGS if code != "it"]
_CALLS = {"t", "tn", "has", "Msg", "LocalizedError", "AccountError", "DataError"}


# ------------------------------------------------------------------ cataloghi
@pytest.mark.parametrize("lang", OTHER_LANGS)
def test_catalog_is_complete_and_consistent_with_the_reference(lang):
    """Stesse chiavi, stessi segnaposto {x}, stessi tag [[ ]] e ** e stessi a capo dell'italiano."""
    assert check.check(lang) == []


def _literal_keys() -> dict[str, str]:
    used: dict[str, str] = {}
    files = [*(ROOT / "goalga").rglob("*.py"), *(ROOT / "ui").rglob("*.py"), ROOT / "app.py"]
    for path in files:
        if "catalogs" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else None
            arg = node.args[0]
            if name in _CALLS and isinstance(arg, ast.Constant) and isinstance(arg.value, str) and "." in arg.value:
                used.setdefault(arg.value, f"{path.relative_to(ROOT)}:{node.lineno}")
    return used


def test_every_translation_key_used_in_the_code_exists():
    keys = set(check.load("it"))
    missing = {k: where for k, where in _literal_keys().items()
               if k not in keys and not any(f"{k}.{form}" in keys for form in ("one", "few", "many", "other"))}
    assert not missing, f"chiavi usate nel codice ma assenti dal catalogo: {missing}"


def test_no_help_text_starts_with_a_paper_label():
    """Nei popup di aiuto non compare il prefisso «Paper:» (il lavoro è citato nella scheda Metodo e nel README)."""
    label = re.compile(r"^\s*(paper|articolo|article|artículo|статья|论文)\s*[:：]", re.I)
    for lang in LANGS:
        offenders = [k for k, v in check.load(lang).items() if label.match(v)]
        assert not offenders, f"{lang}: {offenders}"


def test_gradient_titles_keep_their_markup_in_every_language():
    for lang in LANGS:
        strings = check.load(lang)
        for key in ("welcome.title", "start.title", "goals.title", "risk.title", "review.title", "evolve.title"):
            assert strings[key].count("[[") == strings[key].count("]]") >= 1, (lang, key)


def test_welcome_texts_match_what_the_product_owner_asked_for():
    it = check.load("it")
    assert it["welcome.feat1"] == "futuri di mercato simulati dai dati storici"
    assert it["welcome.feat2"] == "strategie che si incrociano a ogni generazione"
    assert it["welcome.sub"].startswith("Simulazione di migliaia di futuri tramite algoritmi genetici")
    assert it["review.title"] == "[[Confermi]] il piano?"
    assert "disposto ad assumere" in it["risk.title"]
    assert it["evolve.title"] == "L'algoritmo sta [[ragionando]]"
    assert not any("saltare" in v.lower() or "rivedi" in v.lower() for k, v in it.items() if k.startswith("evolve."))


# ------------------------------------------------------------------ scelta della lingua
def test_normalize_and_detect():
    assert i18n.normalize("it-IT") == "it" and i18n.normalize("zh_Hans") == "zh" and i18n.normalize("ES") == "es"
    assert i18n.normalize("de") is None and i18n.normalize("") is None and i18n.normalize(None) is None
    assert i18n.detect("de-DE,de;q=0.9,fr;q=0.8,en;q=0.7") == "fr"
    assert i18n.detect(None, "") is None and i18n.detect("ru-RU") == "ru"
    assert set(LANGS) == {"en", "it", "es", "fr", "ru", "zh"}


def test_language_is_scoped_to_the_context():
    assert i18n.current() == "it"                       # impostata da conftest
    with i18n.use("zh"):
        assert i18n.current() == "zh"
        seen: list[str] = []
        worker = threading.Thread(target=lambda: seen.append(i18n.current()))
        worker.start()
        worker.join()
        assert seen == ["it"], "un altro thread non eredita la lingua attiva"
    assert i18n.current() == "it"


def test_resolver_supplies_the_language_when_none_is_active(monkeypatch):
    """I callback dei widget girano prima dello script: la lingua arriva dalla sessione tramite il resolver."""
    monkeypatch.setattr(i18n, "_resolver", lambda: "fr")
    seen: list[str] = []
    worker = threading.Thread(target=lambda: seen.append(i18n.current()))
    worker.start()
    worker.join()
    assert seen == ["fr"]
    monkeypatch.setattr(i18n, "_resolver", lambda: "xx")      # lingua non supportata: si usa quella predefinita
    worker = threading.Thread(target=lambda: seen.append(i18n.current()))
    worker.start()
    worker.join()
    assert seen[-1] == "it"


def test_lookup_falls_back_to_english_then_italian_then_the_key(monkeypatch):
    monkeypatch.setitem(i18n._catalogs, "fr", {"only.fr": "seul"})
    monkeypatch.setitem(i18n._catalogs, "en", {"only.fr": "x", "only.en": "english", "both": "EN"})
    monkeypatch.setitem(i18n._catalogs, "it", {"only.it": "italiano", "both": "IT"})
    assert t("only.fr", lang="fr") == "seul"
    assert t("only.en", lang="fr") == "english"
    assert t("only.it", lang="fr") == "italiano"
    assert t("both", lang="fr") == "EN"
    assert t("nowhere.at.all", lang="fr") == "nowhere.at.all"
    assert t("only.en", lang="de") == "english", "lingua non supportata: si usa quella attiva (it) e poi i ripieghi"


def test_placeholders_are_filled_and_a_bad_template_never_raises(monkeypatch):
    monkeypatch.setitem(i18n._catalogs, "it", {"a": "{n} cose", "b": "senza {mancante}"})
    assert t("a", n=3) == "3 cose"
    assert t("b", n=3) == "senza {mancante}"


# ------------------------------------------------------------------ plurali
@pytest.mark.parametrize("lang, n, expected", [
    ("it", 1, "one"), ("it", 2, "other"), ("it", 0, "other"), ("en", 1, "one"), ("en", 5, "other"), ("es", 1, "one"),
    ("fr", 0, "one"), ("fr", 1, "one"), ("fr", 2, "other"),
    ("ru", 1, "one"), ("ru", 21, "one"), ("ru", 101, "one"), ("ru", 2, "few"), ("ru", 24, "few"), ("ru", 5, "many"),
    ("ru", 11, "many"), ("ru", 12, "many"), ("ru", 14, "many"), ("ru", 100, "many"), ("ru", 1.5, "other"),
    ("zh", 1, "other"), ("zh", 25, "other"),
])
def test_plural_categories(lang, n, expected):
    assert plural_category(lang, n) == expected


def test_years_use_the_right_plural_form_in_every_language():
    assert tn("unit.years", 1, lang="it") == "1 anno" and tn("unit.years", 8, lang="it") == "8 anni"
    for lang in OTHER_LANGS:
        for n in (1, 2, 5, 21, 25):
            text = tn("unit.years", n, lang=lang)
            assert str(n) in text and "{" not in text and "unit.years" not in text, (lang, n, text)
    ru = {n: tn("unit.years", n, lang="ru") for n in (1, 2, 5)}
    assert len(set(re.sub(r"\d+", "", v) for v in ru.values())) == 3, "il russo distingue uno, pochi, molti"
    assert len({re.sub(r"\d+", "", tn("unit.years", n, lang="zh")) for n in (1, 2, 5)}) == 1


# ------------------------------------------------------------------ messaggi traducibili
def test_messages_can_be_rendered_in_another_language_and_survive_pickling():
    with i18n.use("it"):
        msg = Msg("core.plan.no_goals")
    assert str(msg) == t("core.plan.no_goals", lang="it")
    assert msg.render("en") != str(msg) and msg.render("en") == t("core.plan.no_goals", lang="en")
    again = pickle.loads(pickle.dumps(msg))
    assert isinstance(again, Msg) and again.key == msg.key and again.render("es") == msg.render("es")


def test_localized_errors_keep_their_key_and_render_in_any_language():
    exc = AccountError("acct.err.locked", minutes=7)
    assert exc.key == "acct.err.locked" and exc.params == {"minutes": 7}
    for lang in LANGS:
        assert "7" in i18n.render(exc, lang)
    assert i18n.render(ValueError("boom")) == "boom"


# ------------------------------------------------------------------ formati locali
@pytest.mark.parametrize("lang, eur, pct, compact, number", [
    ("it", "€ 1.250.000", "95,8%", "40\u00a0k€", "1.234,5"),
    ("en", "€1,250,000", "95.8%", "€40k", "1,234.5"),
    ("es", "1.250.000\u00a0€", "95,8\u00a0%", "40\u00a0k€", "1.234,5"),
    ("fr", "1\u202f250\u202f000\u00a0€", "95,8\u202f%", "40\u00a0k€", "1\u202f234,5"),
    ("ru", "1\u00a0250\u00a0000\u00a0€", "95,8\u00a0%", "40\u00a0тыс.\u00a0€", "1\u00a0234,5"),
    ("zh", "€1,250,000", "95.8%", "€4万", "1,234.5"),
])
def test_numbers_money_and_percentages_follow_local_conventions(lang, eur, pct, compact, number):
    with i18n.use(lang):
        assert fmt.eur(1_250_000, 0) == eur
        assert fmt.pct(0.9583, 1) == pct
        assert fmt.eur_compact(40_000) == compact
        assert fmt.number(1234.5, 1) == number


def test_plotly_separators_match_the_decimal_and_thousands_marks():
    with i18n.use("it"):
        assert fmt.plotly_separators() == ",."
    with i18n.use("en"):
        assert fmt.plotly_separators() == ".,"


# ------------------------------------------------------------------ script in st.html
def test_inline_scripts_survive_the_html_sanitizer():
    """DOMPurify scarta un <script> il cui testo contiene «<» seguito da una lettera, una cifra o «/»."""
    checked = 0
    for path in (ROOT / "ui").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "unsafe_allow_javascript" not in text and "<script>" not in text:
            continue
        for body in re.findall(r"<script>(.*?)</script>", text, re.S):
            checked += 1
            assert not re.search(r"<[/!\w]", body), f"{path.name}: lo script contiene «<»: {body[:80]!r}"
    assert checked >= 3
