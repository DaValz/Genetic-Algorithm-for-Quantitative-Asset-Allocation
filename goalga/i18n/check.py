"""Verifica dei cataloghi di traduzione: stesse chiavi, stessi segnaposto, stessi tag di formattazione.

    python -m goalga.i18n.check            # tutte le lingue
    python -m goalga.i18n.check es fr      # solo alcune

Il catalogo italiano è il riferimento. Per ogni altra lingua si controlla che
  * non manchino né avanzino chiavi (le forme plurali dipendono dalla lingua: vedi ``PLURAL_FORMS``);
  * nessun testo sia vuoto;
  * i segnaposto ``{nome}`` e i modelli Plotly ``%{...}`` coincidano con l'originale;
  * i tag ``[[...]]`` (gradiente), ``**grassetto**`` e gli a capo ``\\n`` siano in numero uguale.
"""
from __future__ import annotations

import importlib
import re
import string
import sys

from . import LANGS

REFERENCE = "it"
PLURAL_FORMS: dict[str, tuple[str, ...]] = {"ru": ("one", "few", "many", "other"), "zh": ("other",)}
DEFAULT_FORMS = ("one", "other")
_SUFFIX = re.compile(r"\.(one|few|many|other)$")
_PLOTLY = re.compile(r"%\{[^}]*\}")


def load(lang: str) -> dict[str, str]:
    return importlib.import_module(f"goalga.i18n.catalogs.{lang}").STRINGS


def plural_bases(strings: dict[str, str]) -> set[str]:
    """Chiavi con forme plurali (hanno una variante ``.one``): ``unit.years`` per ``unit.years.one``."""
    return {key[:-4] for key in strings if key.endswith(".one")}


def split_plurals(strings: dict[str, str], bases: set[str]) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    plain: dict[str, str] = {}
    plural: dict[str, dict[str, str]] = {}
    for key, text in strings.items():
        match = _SUFFIX.search(key)
        if match and key[:match.start()] in bases:
            plural.setdefault(key[:match.start()], {})[match.group(1)] = text
        else:
            plain[key] = text
    return plain, plural


def placeholders(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(nomi dei segnaposto ``{x}``, modelli Plotly ``%{...}``) di un testo."""
    templates = tuple(sorted(_PLOTLY.findall(text)))
    names = {name.split(".")[0].split("[")[0].split("!")[0]
             for _, name, _, _ in string.Formatter().parse(_PLOTLY.sub("", text)) if name is not None}
    return tuple(sorted(names)), templates


def markup(text: str) -> tuple[int, int, int, int]:
    return text.count("[["), text.count("]]"), text.count("**"), text.count("\n")


def _compare(key: str, ref: str, text: str, problems: list[str], *, optional: frozenset[str] = frozenset()) -> None:
    if not isinstance(text, str) or not text.strip():
        problems.append(f"{key}: testo vuoto")
        return
    try:
        want, want_tpl = placeholders(ref)
        got, got_tpl = placeholders(text)
    except ValueError as exc:
        problems.append(f"{key}: parentesi graffe non valide ({exc})")
        return
    missing = [n for n in want if n not in got and n not in optional]
    extra = [n for n in got if n not in want]
    if missing or extra:
        problems.append(f"{key}: segnaposto diversi (mancano {missing or '-'}, in più {extra or '-'})")
    if want_tpl != got_tpl:
        problems.append(f"{key}: modelli Plotly diversi ({list(want_tpl)} -> {list(got_tpl)})")
    if markup(ref) != markup(text):
        problems.append(f"{key}: tag [[ ]], ** o a capo diversi dall'originale {markup(ref)} -> {markup(text)}")


def check(lang: str) -> list[str]:
    """Elenco dei problemi del catalogo ``lang`` (vuoto se coerente con quello italiano)."""
    if lang not in LANGS:
        return [f"lingua non supportata: {lang}"]
    try:
        strings = load(lang)
    except ImportError as exc:
        return [f"catalogo mancante: {exc}"]
    ref_strings = load(REFERENCE)
    bases = plural_bases(ref_strings)
    ref_plain, ref_plural = split_plurals(ref_strings, bases)
    plain, plural = split_plurals(strings, bases)
    problems: list[str] = []

    for key in sorted(set(ref_plain) - set(plain)):
        problems.append(f"{key}: chiave mancante")
    for key in sorted(set(plain) - set(ref_plain)):
        problems.append(f"{key}: chiave non presente nel catalogo italiano")
    for key in sorted(set(ref_plain) & set(plain)):
        _compare(key, ref_plain[key], plain[key], problems)

    forms = PLURAL_FORMS.get(lang, DEFAULT_FORMS)
    for base in sorted(bases):
        have = plural.get(base, {})
        for form in forms:
            if form not in have:
                problems.append(f"{base}.{form}: forma plurale mancante")
        for form in sorted(set(have) - set(forms) - {"one"}):
            problems.append(f"{base}.{form}: forma plurale non usata in questa lingua")
        reference = ref_plural[base]["other"]
        for form, text in have.items():
            _compare(f"{base}.{form}", reference, text, problems, optional=frozenset({"n"}))
    return problems


def main(argv: list[str]) -> int:
    langs = argv or [code for code in LANGS if code != REFERENCE]
    bad = 0
    for lang in langs:
        problems = check(lang)
        total = len(load(lang)) if not problems or not problems[0].startswith("catalogo mancante") else 0
        print(f"[{lang}] {'OK' if not problems else str(len(problems)) + ' problemi'} ({total} chiavi)")
        for line in problems:
            print("   -", line)
        bad += bool(problems)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
