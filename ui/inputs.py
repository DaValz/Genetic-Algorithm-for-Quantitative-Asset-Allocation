"""Campi di input del percorso guidato: importi leggibili, scorciatoie e verifica del testo scritto."""
from __future__ import annotations

import html
import math
import re
import unicodedata
from typing import Sequence

import streamlit as st

from goalga.i18n import current, t

from . import format as fmt

MAX_AMOUNT = 1e12          # oltre mille miliardi un importo scritto a mano è quasi certamente un refuso


def _fold(text: object) -> str:
    """Minuscolo, senza accenti (millón = millon), con cifre e segni a larghezza intera e spazi speciali ridotti ai normali."""
    text = unicodedata.normalize("NFKD", str(text)).lower()
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", text).strip()


# Come si scrivono «mille», «milioni» e «miliardi»: abbreviazioni e parole nelle sei lingue (già «piegate» da ``_fold``).
_UNIT_WORDS = {
    1e3: "k mila mille migliaia thousand thousands тыс тысяча тысячи тысяч 千",
    1e6: "m mn mln mio milione milioni million millions millon millones млн миллион миллиона миллионов 百万",
    1e9: "b bn bln mld mrd md miliardo miliardi billion billions milliard milliards milmillones млрд миллиард "
         "миллиарда миллиардов 十亿",
    1e4: "万",
    1e7: "千万",
    1e8: "亿",
}
_UNITS = {_fold(word): factor for factor, words in _UNIT_WORDS.items() for word in words.split()}
_ONE = {"un", "uno", "una", "a", "one", "один", "одна", "одно", "一"}            # «un milione», «a million», «один миллион»
_CURRENCY = re.compile(r"€|(?<![a-z])euros?(?![a-z])|(?<![a-z])eur(?![a-z])|(?<![а-я])евро(?![а-я])|欧元")
_FILLER = re.compile(r"\s*(?<![a-zа-я])(?:di|de|of|d)(?![a-zа-я])['’]?\s*$")        # «2 milioni di euro», «2 millions d'euros»
_AMOUNT = re.compile(r"([.,]?\d[\d.,'’ ]*?)\s*([^\d\s.,'’]+)?\.?")


def _unit_factor(word: str) -> float | None:
    if word == "mil" and current() == "es":
        return 1e3                                   # «500 mil» = 500.000 solo in spagnolo: altrove «mil» è ambiguo
    return _UNITS.get(word)


def _grouped(text: str) -> str | None:
    """Cifre di un numero con separatori delle migliaia (``1.250.000``), anche se i gruppi non sono da tre cifre."""
    parts = re.split(r"[.,]", text)
    if not all(p.isdigit() for p in parts) or any(len(p) < 2 for p in parts[1:]):
        return None
    return "".join(parts)


def _plain(number: str) -> str | None:
    """Cifre con il punto decimale da un numero scritto all'italiana (1.234,56), all'americana (1,234.56) o alla buona.

    L'ultimo separatore è il decimale solo se lo seguono una o due cifre; altrimenti i separatori raggruppano le migliaia,
    anche con gruppi irregolari: aggiungere uno zero a «250.000» dà «250.0000», cioè 2.500.000, non 250.
    """
    marks = [ch for ch in number if ch in ".,"]
    if not marks:
        return number
    last = max(number.rfind("."), number.rfind(","))
    head, tail = number[:last], number[last + 1:]
    if len(set(marks)) == 2:                          # 1.250.000,50 / 1,250,000.50
        if len(tail) in (1, 2):
            whole = _grouped(head)
            return None if whole is None else f"{whole}.{tail}"
        return _grouped(number)
    if len(marks) > 1:                                # lo stesso segno più volte non è un decimale
        return _grouped(number)
    if len(tail) <= 2:                                # 12,5 / 12.50 / ,5
        return f"{head or '0'}.{tail}"
    if len(tail) == 3 and head in ("", "0"):
        return f"0.{tail}"                            # 0,500 = mezzo euro
    return head + tail                                # 20.000 / 50,000 / 250.0000


def parse_amount(text: object) -> float | None:
    """Interpreta un importo scritto liberamente.

    Cifre con o senza separatori (``20000``, ``20.000``, ``1,250,000``, ``€ 1.250,50``, ``250.0000``) e abbreviazioni o
    parole nelle sei lingue: ``20k``, ``1,5M``, ``2 milioni``, ``3 mln di euro``, ``2 millones``, ``1.5 million euros``,
    ``2 млн``, ``100万``. Restituisce ``None`` se non è un importo.
    """
    if text is None:
        return None
    s = _FILLER.sub("", _CURRENCY.sub(" ", _fold(text)).strip()).strip()
    s = re.sub(r"(?<![a-z])mil\s+millones", "milmillones", s)
    first, _, rest = s.partition(" ")
    if rest and first in _ONE:
        s = f"1 {rest}"                               # «un milione»
    match = _AMOUNT.fullmatch(s)
    if not match:
        return None
    number, unit = match.groups()
    number = re.sub(r"[ '’]", "", number)
    if re.search(r"[.,]{2}", number):
        return None                                   # 20..000
    number = number.rstrip(".,")                      # «50.» mentre si scrive
    if unit:
        factor = _unit_factor(unit)
        digits = number.replace(",", ".")             # con l'unità '.' e ',' sono decimali: 1,5m = 1.500.000
        if factor is None or digits.count(".") > 1:
            return None
    else:
        factor, digits = 1.0, _plain(number)
        if digits is None:
            return None
    try:
        value = float(digits) * factor
    except ValueError:
        return None
    return value if math.isfinite(value) and 0 <= value <= MAX_AMOUNT else None


def format_amount(value: float) -> str:
    return fmt.eur(float(value), 0)


def _commit(name: str) -> None:
    ss = st.session_state
    value = parse_amount(ss.get(f"in_{name}"))
    ss[f"bad_{name}"] = value is None
    if value is not None:
        ss[name] = value
    ss[f"in_{name}"] = format_amount(ss[name])


def _quick(name: str, key: str) -> None:
    ss = st.session_state
    value = ss.get(key)
    if value is not None:
        ss[name] = float(value)
        ss[f"in_{name}"] = format_amount(value)
        ss[f"bad_{name}"] = False
    ss[key] = None


def amount_field(name: str, label: str, shortcuts: Sequence[int], hint: str = "") -> None:
    """Importo grande da scrivere (``st.session_state[name]``) con scorciatoie a pillola."""
    ss = st.session_state
    key = f"in_{name}"
    if key not in ss:
        ss[key] = format_amount(ss[name])
    st.html(f'<div class="gx-label">{html.escape(label)}</div>')
    with st.container(key=f"amt-{name}"):
        st.text_input(label, key=key, label_visibility="collapsed", on_change=_commit, args=(name,),
                      placeholder=fmt.eur(0))
    if ss.get(f"bad_{name}"):
        st.html(f'<div class="gx-note" style="color:var(--warn)">{html.escape(t("input.bad_amount"))}</div>')
    elif hint:
        st.html(f'<div class="gx-note">{html.escape(hint)}</div>')
    pills_key = f"chip-{name}"
    st.pills(t("input.shortcuts", label=label), list(shortcuts), key=pills_key, label_visibility="collapsed",
             format_func=lambda v: fmt.eur_compact(v), on_change=_quick, args=(name, pills_key))


def confidence_dots(count: int, total: int = 100, cols: int = 20) -> str:
    """Pittogramma di ``total`` puntini, di cui ``count`` accesi (frequenze naturali)."""
    count = max(0, min(total, int(count)))
    dots = "".join(f'<i class="{"on" if k < count else ""}" style="--i:{k}"></i>' for k in range(total))
    return f'<div class="gx-dots" style="--cols:{int(cols)}" aria-hidden="true">{dots}</div>'
