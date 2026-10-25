"""Contenuto salvato di un portafoglio: risultato dell'ottimizzazione, pesi target e confronti tra versioni."""
from __future__ import annotations

import math
from datetime import date
from typing import Mapping, Sequence

import numpy as np

PAYLOAD_VERSION = 1
SOURCE_LABEL = "Market data"       # origine dei dati mostrata nel riepilogo salvato (il fornitore è nella documentazione)


def result_payload(report, market, plan, *, names: Mapping[str, str] | None, source: str, risk: str, max_level: int,
                   anchor: int = 0, as_of: date | None = None) -> dict:
    """Riepilogo serializzabile (JSON) di un'ottimizzazione: percorso, pesi di ogni livello e metriche."""
    names = names or {}
    tickers = [str(x) for x in market.names]
    fan = report.fan
    oos = report.oos
    start, end = market.meta.get("start"), market.meta.get("end")
    return {
        "v": PAYLOAD_VERSION,
        "anchor": int(anchor),
        "first_period": float(getattr(plan, "first_period", 1.0)),
        "horizon": int(plan.horizon),
        "tickers": tickers,
        "names": {t: str(names.get(t, t)) for t in tickers},
        "levels": [[round(float(w), 6) for w in col] for col in market.weights.T],
        "path": [int(x) for x in report.path],
        "risk": risk,
        "max_level": int(max_level),
        "metrics": {
            "pr": float(report.pr), "oos_pr": float(oos.pr) if oos is not None else None,
            "irr_es": float(report.irr_es) if np.isfinite(report.irr_es) else None,
            "required": float(report.required_return) if report.required_return is not None else None,
            "expected_return": float(report.expected_path_return), "generations": int(report.ga.generations),
            "expected_growth": float(report.expected_path_growth) if np.isfinite(report.expected_path_growth) else None,
            "feasible": bool(report.ga.feasible),
        },
        "fan": {"p5": [round(float(x), 2) for x in fan["P5"]], "p50": [round(float(x), 2) for x in fan["P50"]],
                "p95": [round(float(x), 2) for x in fan["P95"]]},
        "data": {"source": source, "start": f"{start:%Y-%m}" if start is not None else None,
                 "end": f"{end:%Y-%m}" if end is not None else None},
        "created": (as_of or date.today()).isoformat(),
    }


def years_elapsed(start: date, as_of: date) -> int:
    """Anni interi trascorsi tra ``start`` e ``as_of`` (mai negativo)."""
    years = as_of.year - start.year - ((as_of.month, as_of.day) < (start.month, start.day))
    return max(0, int(years))


def anniversary(start: date, n: int) -> date:
    """Data dell'n-esimo anniversario di ``start`` (un 29 febbraio ricorre il 1° marzo negli anni non bisestili)."""
    try:
        return start.replace(year=start.year + int(n))
    except ValueError:
        return date(start.year + int(n), 3, 1)


def year_fraction(start: date, as_of: date) -> float:
    """Quota dell'anno in corso (dall'ultimo anniversario di ``start``) già trascorsa, in [0, 1)."""
    k = years_elapsed(start, as_of)
    last, nxt = anniversary(start, k), anniversary(start, k + 1)
    return min(0.999, max(0.0, (as_of - last).days / max(1, (nxt - last).days)))


def elapsed_years(start: date, as_of: date) -> float:
    """Anni (con la parte frazionaria) trascorsi da ``start`` a ``as_of``."""
    return years_elapsed(start, as_of) + year_fraction(start, as_of)


def relative_index(result: Mapping, k: int) -> int:
    return min(max(int(k) - int(result.get("anchor", 0)), 0), len(result["path"]) - 1)


def is_completed(result: Mapping, k: int) -> bool:
    """True se l'orizzonte della versione è terminato dopo ``k`` anni dall'inizio dell'investimento."""
    return int(k) - int(result.get("anchor", 0)) >= int(result["horizon"])


def level_at(result: Mapping, k: int) -> int:
    return int(result["path"][relative_index(result, k)])


def target_weights(result: Mapping, k: int) -> dict[str, float]:
    """Pesi target (ticker -> peso) nell'anno ``k`` (anni trascorsi dall'inizio dell'investimento)."""
    weights = result["levels"][level_at(result, k) - 1]
    return {t: float(w) for t, w in zip(result["tickers"], weights) if w > 1e-9}


def weight_distance(a: Mapping[str, float] | None, b: Mapping[str, float] | None) -> float:
    """Massima differenza assoluta di peso tra due portafogli (in frazione: 0.05 = 5 punti percentuali)."""
    a, b = a or {}, b or {}
    return max((abs(a.get(k, 0.0) - b.get(k, 0.0)) for k in set(a) | set(b)), default=0.0)


def weight_changes(old: Mapping[str, float] | None, new: Mapping[str, float], names: Mapping[str, str],
                   min_change: float = 0.005) -> list[dict]:
    """Variazioni per asset, dalla più ampia: ``[{ticker, name, old, new}]``."""
    old = old or {}
    rows = [{"ticker": k, "name": str(names.get(k, k)), "old": float(old.get(k, 0.0)), "new": float(new.get(k, 0.0))}
            for k in set(old) | set(new)]
    rows = [r for r in rows if abs(r["new"] - r["old"]) >= min_change]
    return sorted(rows, key=lambda r: -abs(r["new"] - r["old"]))


def projected_wealth(result: Mapping, k: int) -> float | None:
    """Patrimonio mediano previsto dopo ``k`` anni (se il piano è proseguito come atteso)."""
    median = (result.get("fan") or {}).get("p50")
    if not median:
        return None
    idx = int(k) - int(result.get("anchor", 0))
    return float(median[min(max(idx, 0), len(median) - 1)])


def fan_position(result: Mapping, t: float) -> float:
    """Posizione (frazionaria) nella fascia dei patrimoni attesi al tempo ``t`` (anni dall'inizio dell'investimento).

    L'indice 0 è l'origine della versione (adesso, se è stata creata a metà anno); l'indice ``i >= 1`` è l'i-esimo
    flusso del piano, cioè l'anniversario numero ``anchor + i``.
    """
    anchor = int(result.get("anchor", 0))
    first = min(1.0, max(1e-6, float(result.get("first_period", 1.0))))
    last = max(0, len((result.get("fan") or {}).get("p50", [])) - 1)
    origin = anchor + 1.0 - first
    if t <= origin:
        position = 0.0
    elif t < anchor + 1:
        position = (t - origin) / first
    else:
        position = t - anchor
    return min(max(position, 0.0), float(last))


def fan_value(result: Mapping, key: str, t: float, net: Sequence[float] | None = None) -> float | None:
    """Valore della fascia ``key`` (``p5``, ``p50`` o ``p95``) al tempo ``t``, in anni dall'inizio dell'investimento.

    Tra due flussi il patrimonio cresce fino al flusso successivo: l'interpolazione va dal valore dopo i flussi
    dell'anniversario precedente a quello *prima* dei flussi del successivo (``net`` = versamenti meno obiettivi di
    ogni anno del piano: essendo deterministici, spostano tutti i percentili della stessa quantità).
    """
    values = (result.get("fan") or {}).get(key)
    if not values:
        return None
    position = fan_position(result, t)
    i = min(int(math.floor(position)), len(values) - 1)
    u = position - i
    if u <= 1e-12 or i + 1 >= len(values):
        return float(values[i])
    after = float(values[i + 1]) - (float(net[i]) if net is not None and i < len(net) else 0.0)
    return (1.0 - u) * float(values[i]) + u * after
