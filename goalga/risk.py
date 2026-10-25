"""Profili di rischio: quanto rischio l'investitore è disposto ad assumere.

Un profilo non cambia l'obiettivo dell'algoritmo: ne limita lo spazio di ricerca. Il glide path può usare
solo i portafogli da P1 (difensivo) fino a un livello massimo; l'algoritmo genetico trova il percorso migliore
*dentro* quel limite. Confrontare la probabilità di successo ottenibile con i diversi limiti mostra il prezzo,
in termini di rischio, dei propri obiettivi.
"""
from __future__ import annotations

import math
from dataclasses import replace

import numpy as np

from .market import Market
from .portfolios import Frontier, portfolio_stats

PROFILE_KEYS = ("cautious", "balanced", "dynamic")


def profile_caps(n_portfolios: int) -> dict[str, int]:
    """Livello massimo consentito da ciascun profilo (terzi della scala: con 9 portafogli 3, 6 e 9)."""
    n = int(n_portfolios)
    cautious = min(n, max(2, math.ceil(n / 3)))
    balanced = min(n, max(cautious, math.ceil(2 * n / 3)))
    return {"cautious": cautious, "balanced": balanced, "dynamic": n}


def restrict_market(market: Market, max_level: int) -> Market:
    """Mercato con i soli portafogli P1..P``max_level`` (gli scenari estratti coincidono con le prime colonne)."""
    n = market.n_portfolios
    k = int(max_level)
    if not 1 <= k <= n:
        raise ValueError(f"max_level deve essere compreso tra 1 e {n}.")
    if k == n:
        return market
    weights = market.weights[:, :k]
    ret, vol = portfolio_stats(weights, market.mu, market.cov)
    return replace(market, weights=weights, frontier=Frontier(weights, ret, vol, market.frontier.max_weight))


def annual_return_quantile(market: Market, level: int, q: float = 5.0, n: int = 4000, seed: int = 11) -> float:
    """``q``-esimo percentile del rendimento annuo del portafoglio ``level`` (un anno sfavorevole su 20 con q=5)."""
    rng = np.random.default_rng(seed)
    sample = market.draw_scenarios(1, n, rng)[:, 0, int(level) - 1]
    return float(np.percentile(sample, q))
