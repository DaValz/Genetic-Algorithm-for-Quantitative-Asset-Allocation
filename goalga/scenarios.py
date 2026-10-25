"""Generazione degli scenari di rendimento tramite bootstrap (sezione I del paper).

Il bootstrap con reinserimento ricampiona *righe* della serie storica dei portafoglio: in questo
modo la struttura di correlazione, l'asimmetria e le code grasse dei dati storici vengono
ereditate automaticamente, comprese le correlazioni crescenti nelle fasi di panico.
Come nel paper, le distribuzioni empiriche possono essere *ricentrate* attorno ai rendimenti
attesi scelti dall'utente (processo di normalizzazione): si mantengono i momenti di ordine
superiore ma si impone il primo momento.
"""
from __future__ import annotations

import numpy as np

MIN_RETURN = -0.999  # un rendimento non può scendere sotto -100%


def annual_windows(monthly_returns: np.ndarray) -> np.ndarray:
    """Rendimenti annuali su finestre mobili di 12 mesi (composti), una riga per finestra."""
    r = np.asarray(monthly_returns, dtype=float)
    if r.shape[0] < 12:
        raise ValueError("Servono almeno 12 rendimenti mensili.")
    csum = np.vstack([np.zeros((1, r.shape[1])), np.cumsum(np.log1p(r), axis=0)])
    return np.expm1(csum[12:] - csum[:-12])


def expected_annual_return(monthly_returns: np.ndarray) -> np.ndarray:
    """Rendimento annuo atteso implicito: ``(1 + media mensile)^12 - 1``."""
    return (1.0 + np.asarray(monthly_returns, dtype=float).mean(axis=0)) ** 12 - 1.0


def recenter_monthly(monthly_returns: np.ndarray, target_annual: np.ndarray) -> np.ndarray:
    """Trasla i rendimenti mensili affinché il rendimento annuo atteso coincida con il target."""
    r = np.asarray(monthly_returns, dtype=float)
    target_monthly = (1.0 + np.asarray(target_annual, dtype=float)) ** (1.0 / 12.0) - 1.0
    return np.maximum(r - r.mean(axis=0) + target_monthly, MIN_RETURN)


def recenter_annual(annual_returns: np.ndarray, target_annual: np.ndarray) -> np.ndarray:
    """Trasla i rendimenti annuali affinché la media coincida con il target."""
    r = np.asarray(annual_returns, dtype=float)
    return np.maximum(r - r.mean(axis=0) + np.asarray(target_annual, dtype=float), MIN_RETURN)


def bootstrap_annual(
    history: np.ndarray, horizon: int, n_scenarios: int, rng: np.random.Generator
) -> np.ndarray:
    """Scenari (S, T, H): ogni anno è una finestra annuale storica estratta con reinserimento."""
    idx = rng.integers(0, history.shape[0], size=(n_scenarios, horizon))
    return history[idx]


def bootstrap_monthly(
    history: np.ndarray,
    horizon: int,
    n_scenarios: int,
    rng: np.random.Generator,
    chunk: int = 250,
) -> np.ndarray:
    """Scenari (S, T, H): ogni anno compone 12 mesi storici estratti con reinserimento."""
    logs = np.log1p(history)
    out = np.empty((n_scenarios, horizon, history.shape[1]))
    for start in range(0, n_scenarios, chunk):
        size = min(chunk, n_scenarios - start)
        idx = rng.integers(0, history.shape[0], size=(size, horizon, 12))
        out[start : start + size] = np.expm1(logs[idx].sum(axis=2))
    return out
