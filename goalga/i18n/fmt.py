"""Formattazione di numeri, importi e percentuali secondo la lingua attiva (nessuna dipendenza esterna)."""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import current

NBSP = "\u00a0"
NNBSP = "\u202f"


@dataclass(frozen=True)
class Spec:
    decimal: str
    group: str
    pct: str                     # suffisso della percentuale
    cur: str                     # importo completo, es. "€ {n}"
    small: str                   # importo sintetico sotto le migliaia, es. "{n} €"
    compact: tuple[str, str, str]  # miliardi, milioni, migliaia
    plotly: str                  # separatori di Plotly: decimale + migliaia


SPECS: dict[str, Spec] = {
    "it": Spec(",", ".", "%", "€ {n}", f"{{n}}{NBSP}€",
               (f"{{n}}{NBSP}Mld{NBSP}€", f"{{n}}{NBSP}M€", f"{{n}}{NBSP}k€"), ",."),
    "en": Spec(".", ",", "%", "€{n}", "€{n}", ("€{n}B", "€{n}M", "€{n}k"), ".,"),
    "es": Spec(",", ".", f"{NBSP}%", f"{{n}}{NBSP}€", f"{{n}}{NBSP}€",
               (f"{{n}}{NBSP}mil{NBSP}M€", f"{{n}}{NBSP}M€", f"{{n}}{NBSP}k€"), ",."),
    "fr": Spec(",", NNBSP, f"{NNBSP}%", f"{{n}}{NBSP}€", f"{{n}}{NBSP}€",
               (f"{{n}}{NBSP}Md€", f"{{n}}{NBSP}M€", f"{{n}}{NBSP}k€"), f",{NNBSP}"),
    "ru": Spec(",", NBSP, f"{NBSP}%", f"{{n}}{NBSP}€", f"{{n}}{NBSP}€",
               (f"{{n}}{NBSP}млрд{NBSP}€", f"{{n}}{NBSP}млн{NBSP}€", f"{{n}}{NBSP}тыс.{NBSP}€"), f",{NBSP}"),
    "zh": Spec(".", ",", "%", "€{n}", "€{n}", ("€{n}亿", "€{n}万", "€{n}"), ".,"),
}


def spec(lang: str | None = None) -> Spec:
    return SPECS.get(lang or current(), SPECS["en"])


def _clean(x: float) -> bool:
    return x is not None and not (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))


def number(x: float, decimals: int = 0) -> str:
    if not _clean(x):
        return "—"
    s = spec()
    text = f"{x:,.{decimals}f}"
    return text.replace(",", "\0").replace(".", s.decimal).replace("\0", s.group)


def eur(x: float, decimals: int = 0) -> str:
    if not _clean(x):
        return "—"
    sign = "-" if x < 0 else ""
    return sign + spec().cur.format(n=number(abs(x), decimals))


def _trim(text: str) -> str:
    """Rimuove gli zeri decimali superflui: '20,0' -> '20', '1,90' -> '1,9'."""
    d = spec().decimal
    if d in text:
        text = text.rstrip("0").rstrip(d)
    return text


def eur_compact(x: float) -> str:
    """Importi sintetici: 1,9 M€ / 320 k€ / 950 € (in cinese 190万 / 32万)."""
    if not _clean(x):
        return "—"
    s = spec()
    sign = "-" if x < 0 else ""
    a = abs(x)
    if current() == "zh":
        if a >= 1e8:
            return sign + s.compact[0].format(n=_trim(number(a / 1e8, 1)))
        if a >= 1e4:
            v = a / 1e4
            return sign + s.compact[1].format(n=_trim(number(v, 0 if v >= 100 else 1 if v >= 10 else 2)))
        return sign + s.cur.format(n=number(a, 0))
    big, mid, kilo = s.compact
    if a >= 1e9:
        return sign + big.format(n=_trim(number(a / 1e9, 1)))
    if a >= 1e6:
        return sign + mid.format(n=_trim(number(a / 1e6, 2 if a < 1e7 else 1)))
    if a >= 1e3:
        return sign + kilo.format(n=_trim(number(a / 1e3, 0 if a >= 1e5 else 1)))
    return sign + s.small.format(n=number(a, 0))


def pct(x: float, decimals: int = 1) -> str:
    if not _clean(x):
        return "—"
    value = x * 100
    if value < 100 and round(value, decimals) >= 100:      # mai «100%» se qualcosa può ancora andare storto
        value = 100 - 10.0**-decimals
    return f"{number(value, decimals)}{spec().pct}"


def pct_short(x: float) -> str:
    """Percentuale con i decimali solo se servono: una coda del 2,5% non diventa «2%»."""
    if not _clean(x):
        return "—"
    value = x * 100
    return pct(x, 0 if abs(value - round(value)) < 1e-6 else 1)


def pct_pp(x: float, decimals: int = 1) -> str:
    """Differenza in punti percentuali con segno."""
    if not _clean(x):
        return "—"
    from . import t

    return f"{'+' if x >= 0 else '−'}{number(abs(x) * 100, decimals)}{NBSP}{t('unit.pp')}"


def years(n: float) -> str:
    from . import tn

    return tn("unit.years", n)


def plotly_separators() -> str:
    return spec().plotly
