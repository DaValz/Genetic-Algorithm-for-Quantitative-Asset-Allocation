"""Internazionalizzazione: cataloghi di messaggi, regole dei plurali e formattazione locale.

Nessuna dipendenza esterna e nessun import di Streamlit: libreria di calcolo, interfaccia e monitor in
background usano la stessa API.

* ``t("chiave", nome=valore)`` restituisce il testo nella lingua attiva (ripiego: inglese, poi italiano);
* ``tn("chiave", n)`` sceglie la forma plurale corretta (``chiave.one`` / ``.few`` / ``.many`` / ``.other``);
* la lingua attiva vive in una ``ContextVar``: l'interfaccia la imposta a ogni esecuzione con ``activate`` e il
  monitor la imposta per ogni destinatario con ``use``.
"""
from __future__ import annotations

import importlib
import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Callable, Iterator

LANGS: dict[str, str] = {
    "en": "English", "it": "Italiano", "es": "Español", "fr": "Français", "ru": "Русский", "zh": "中文",
}
LOCALE_TAGS = {"en": "en-GB", "it": "it-IT", "es": "es-ES", "fr": "fr-FR", "ru": "ru-RU", "zh": "zh-CN"}
FALLBACKS = ("en", "it")

_active: ContextVar[str | None] = ContextVar("goalga_lang", default=None)
_resolver: Callable[[], object] | None = None
_catalogs: dict[str, dict[str, str]] = {}


# ------------------------------------------------------------------ scelta della lingua
def normalize(code: object) -> str | None:
    """``'it-IT'`` -> ``'it'``, ``'zh_Hans'`` -> ``'zh'``; ``None`` se la lingua non è supportata."""
    if not code:
        return None
    base = str(code).strip().lower().replace("_", "-").split("-")[0]
    return base if base in LANGS else None


def default_language() -> str:
    """Lingua usata quando nulla è stato scelto (variabile d'ambiente ``GOALGA_DEFAULT_LANG``, altrimenti inglese)."""
    return normalize(os.environ.get("GOALGA_DEFAULT_LANG")) or "en"


def set_resolver(resolver: Callable[[], object] | None) -> None:
    """Fonte di ripiego della lingua quando nessuna è stata attivata nel contesto corrente.

    L'interfaccia la usa per i callback dei widget: Streamlit li esegue *prima* dello script, quando la lingua
    della sessione non è ancora stata attivata.
    """
    global _resolver
    _resolver = resolver


def current() -> str:
    lang = _active.get()
    if lang is None and _resolver is not None:
        try:
            lang = normalize(_resolver())
        except Exception:
            lang = None
    return lang or default_language()


def activate(code: object) -> str:
    """Imposta la lingua attiva del contesto corrente e la restituisce."""
    lang = normalize(code) or default_language()
    _active.set(lang)
    return lang


@contextmanager
def use(code: object) -> Iterator[str]:
    """Usa temporaneamente una lingua (messaggi, email, formattazione)."""
    lang = normalize(code) or default_language()
    token = _active.set(lang)
    try:
        yield lang
    finally:
        _active.reset(token)


def detect(*candidates: object) -> str | None:
    """Prima lingua supportata tra i candidati (es. intestazione ``Accept-Language``)."""
    for item in candidates:
        for part in str(item or "").split(","):
            lang = normalize(part.split(";")[0])
            if lang:
                return lang
    return None


# ------------------------------------------------------------------ cataloghi
def catalog(lang: str) -> dict[str, str]:
    if lang not in _catalogs:
        try:
            _catalogs[lang] = importlib.import_module(f"{__name__}.catalogs.{lang}").STRINGS
        except ImportError:
            _catalogs[lang] = {}
    return _catalogs[lang]


def _lookup(key: str, lang: str) -> str | None:
    for code in dict.fromkeys((lang, *FALLBACKS)):
        text = catalog(code).get(key)
        if text is not None:
            return text
    return None


def has(key: str) -> bool:
    return _lookup(key, current()) is not None


def _format(text: str, params: dict) -> str:
    if not params:
        return text
    try:
        return text.format(**params)
    except (KeyError, IndexError, ValueError):
        return text


def t(key: str, *, lang: str | None = None, **params: object) -> str:
    """Testo ``key`` nella lingua attiva (o in ``lang``); se manca ovunque restituisce la chiave."""
    text = _lookup(key, normalize(lang) or current())
    return key if text is None else _format(text, params)


def plural_category(lang: str, n: float) -> str:
    """Categoria del plurale (CLDR semplificato) per il numero ``n``."""
    if float(n) != int(n):
        return "other"
    n = abs(int(n))
    if lang == "ru":
        if n % 10 == 1 and n % 100 != 11:
            return "one"
        if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
            return "few"
        return "many"
    if lang == "zh":
        return "other"
    if lang == "fr":
        return "one" if n in (0, 1) else "other"
    return "one" if n == 1 else "other"


def tn(key: str, n: float, *, lang: str | None = None, **params: object) -> str:
    """Testo con la forma plurale adatta a ``n`` (``{n}`` è disponibile nel testo, già formattato)."""
    from .fmt import number

    code = normalize(lang) or current()
    category = plural_category(code, n)
    text = _lookup(f"{key}.{category}", code) or _lookup(f"{key}.other", code)
    if text is None:
        return f"{key}.{category}"
    params.setdefault("n", number(n, 0 if float(n) == int(n) else 1))
    return _format(text, params)


# ------------------------------------------------------------------ messaggi traducibili (errori, motivi)
class Msg(str):
    """Messaggio traducibile: si comporta come una stringa (nella lingua attiva alla creazione) ma conserva
    chiave e parametri per essere riprodotto in un'altra lingua (``render``)."""

    key: str
    params: dict

    def __new__(cls, key: str, **params: object) -> "Msg":
        obj = super().__new__(cls, t(key, **params))
        obj.key, obj.params = key, params
        return obj

    def render(self, lang: str | None = None) -> str:
        return t(self.key, lang=lang, **self.params)

    def __reduce__(self):                    # serializzabile (session_state, cache)
        return (_rebuild_msg, (self.key, self.params))


def _rebuild_msg(key: str, params: dict) -> Msg:
    return Msg(key, **params)


def render(message: object, lang: str | None = None) -> str:
    """Testo di un ``Msg`` (o di un'eccezione che ne contiene uno) nella lingua richiesta."""
    if isinstance(message, Msg):
        return message.render(lang)
    first = message.args[0] if isinstance(message, BaseException) and message.args else None
    if isinstance(first, Msg):
        return first.render(lang)
    return str(message)


class LocalizedError(ValueError):
    """Errore con messaggio traducibile (``str(exc)`` nella lingua attiva alla creazione, ``render`` altrove)."""

    def __init__(self, key: str, **params: object) -> None:
        super().__init__(Msg(key, **params))
        self.key, self.params = key, params
