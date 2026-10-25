"""Mercato corrente: dall'universo completo al pool di asset, ai rendimenti attesi e ai 9 portafogli.

Nessuno scarico mentre l'utente usa l'app: i prezzi vengono dall'archivio mensile dell'universo
(``goalga.snapshot``). Con le impostazioni automatiche l'algoritmo valuta tutti gli asset del catalogo e, a ogni
avvio, ne estrae un pool diversificato in base al seed (vedi ``goalga.selection``); nell'area avanzata si possono
limitare le categorie, escludere asset o sceglierli a mano.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from goalga import snapshot
from goalga.data import DataError
from goalga.i18n import Msg
from goalga.market import Market
from goalga.pipeline import PROXY, choose_pool, market_from_prices
from goalga.selection import Screen, fingerprint, get_screen, split_pool
from goalga.universe import universe_names

from .state import DataBundle, MarketBundle, market_options, pending_seed, setting, signature, universe_choice

MIN_ASSETS = 5          # asset minimi per costruire i 9 portafogli
CACHE_SIZE = 4          # mercati personalizzati tenuti in memoria per sessione (oltre a quello automatico)


def prices() -> pd.DataFrame:
    """Prezzi mensili in euro di tutto l'universo (archivio condiviso tra le sessioni, sola lettura)."""
    try:
        return snapshot.load_prices()
    except FileNotFoundError as exc:
        raise DataError("mkt.no_snapshot") from exc


def screen() -> Screen:
    """Valutazione di tutto l'universo con la storia minima scelta (con cache)."""
    return get_screen(prices(), float(setting("min_years")))


def pool_for(seed: int) -> list[str]:
    """Pool di asset per il seed: estratto dall'universo, oppure l'elenco scelto a mano.

    Dopo il caricamento di un portafoglio salvato il primo avvio riusa il suo stesso pool (vedi ``apply_spec``).
    """
    ss = st.session_state
    choice = universe_choice()
    pin = ss.get("pool_pin")
    if pin and pin.get("seed") == seed and pin.get("sig") == signature(choice):
        eligible = screen().eligible().index
        kept = [t for t in pin["tickers"] if t in eligible]
        if len(kept) >= MIN_ASSETS:
            return kept
    pool, _ = choose_pool(prices(), seed, choice)
    return pool


def apply_custom_weights(market: Market) -> Market:
    """Pesi dei portafogli scelti a mano nell'area avanzata (modalità «scelgo io gli asset»)."""
    ss = st.session_state
    weights = ss.get("custom_w")
    if ss.get("use_custom_weights") and weights is not None and weights.shape == (market.n_assets, market.n_portfolios):
        return market.with_weights(weights)
    return market


def market_for(seed: int | None = None) -> MarketBundle:
    """Mercato (e dati) per il seed indicato, ricostruito solo se le impostazioni o il seed sono cambiati.

    Gli ultimi mercati costruiti restano in memoria, ciascuno con la propria firma: tornando alle scelte automatiche
    dopo aver provato impostazioni personalizzate il mercato automatico è ancora lì e la schermata si apre subito.
    Solleva ``DataError`` / ``ValueError`` (con messaggio traducibile) se con le scelte fatte non si può costruire.
    I pesi personalizzati (modalità «scelgo io gli asset») si applicano a ogni chiamata, fuori dalla cache.
    """
    ss = st.session_state
    seed = pending_seed() if seed is None else int(seed)
    px = prices()
    choice = universe_choice()
    options = market_options([])
    sig = signature("market", seed, choice, {k: v for k, v in options.items() if k != "universe"}, fingerprint(px),
                    ss.get("pool_pin"))
    cache: dict = ss.setdefault("market_cache", {})          # firma -> (base, data, automatico), dal meno al più recente
    entry = cache.pop(sig, None)
    if entry is None:
        pool = pool_for(seed)
        if len(pool) < MIN_ASSETS:
            raise ValueError(Msg("mkt.pool_too_small", n=len(pool), min=MIN_ASSETS))
        options = market_options(pool)
        wanted = [t for t in dict.fromkeys([*pool, PROXY]) if t in px.columns]
        base, prepared = market_from_prices(px[wanted], options)
        found = screen()
        data = DataBundle(
            sig, prepared, list(pool), universe_names(list(base.names)), dict(zip(base.names, map(float, base.mu))),
            seed=int(seed), evaluated=found.n_evaluated, eligible=found.n_eligible)
        entry = (base, data, not ss.get("use_advanced"))
        if entry[2]:                        # del mercato automatico serve solo quello del seed corrente
            for key in [k for k, e in cache.items() if e[2]]:
                del cache[key]
    cache[sig] = entry
    for key in [k for k, e in cache.items() if not e[2]][:-CACHE_SIZE]:
        del cache[key]
    base, data, _ = entry
    market = apply_custom_weights(base)
    return MarketBundle(sig + ("c" if market.custom_weights else ""), market, data, base)


def evaluated_assets() -> int:
    """Quanti asset l'algoritmo valuta (tutto il catalogo con prezzi disponibili)."""
    return int(screen().n_evaluated)


def years_of_history(market: Market) -> float:
    return float(market.n_months) / 12.0


def stock_tickers(market: Market) -> list[str]:
    """Azioni singole del mercato (le altre posizioni sono fondi)."""
    return split_pool(list(market.names))[1]


def stock_weight(market: Market, level: int) -> float:
    """Quota del portafoglio ``level`` investita in azioni singole."""
    members = set(stock_tickers(market))
    w = market.weights[:, level - 1]
    return float(sum(x for name, x in zip(market.names, w) if name in members))
