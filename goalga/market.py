"""Mercato: dalla storia dei rendimenti ai 9 portafogli e agli scenari simulati."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from functools import cached_property
from typing import Mapping, NamedTuple, Sequence

import numpy as np
import pandas as pd

from .i18n import LocalizedError
from .portfolios import (
    Frontier,
    efficient_portfolios,
    ledoit_wolf_constant_correlation,
    portfolio_stats,
    prune_positions,
)
from .scenarios import (
    annual_windows,
    bootstrap_annual,
    bootstrap_monthly,
    expected_annual_return,
    recenter_annual,
    recenter_monthly,
)

METHODS = {
    "annual": "Annuale (finestre mobili di 12 mesi)",
    "monthly": "Mensile (12 mesi estratti e composti)",
}
MIN_MONTHS = 24


@dataclass(frozen=True)
class Basket:
    """Cesta di titoli che entra nella frontiera come un unico asset diversificato.

    Lasciato libero, un ottimizzatore media-varianza concentra l'esposizione ai titoli su 3-5 nomi (sull'archivio reale:
    fino al 100% in tre titoli nel portafoglio più aggressivo e il 55-70% in 4-5 nel sesto), perché sfrutta il rumore
    nelle stime di beta e covarianza dei singoli titoli: non è un portafoglio, è una scommessa. I titoli (``members``,
    pesi uguali) entrano allora come un'unica cesta diversificata che deve valere almeno ``min_share`` dell'esposizione
    azionaria di ogni portafoglio (fondi in ``equity`` più cesta), così l'universo dei titoli lavora davvero, e al
    massimo ``max_weight`` del portafoglio.
    """

    members: tuple[str, ...]
    min_share: float = 0.30
    max_weight: float = 0.60
    equity: tuple[str, ...] = ()


@dataclass
class Market:
    """Ipotesi di mercato usate dal modello (un'istanza è immutabile per convenzione)."""

    names: list[str]
    monthly_returns: np.ndarray       # (n_mesi, n_asset) rendimenti storici originali
    mu_hist: np.ndarray               # rendimento annuo atteso storico
    mu: np.ndarray                    # rendimento annuo atteso usato (storico o personalizzato)
    cov: np.ndarray                   # covarianza annualizzata
    shrinkage: float                  # intensità dello shrinkage applicato (0 = campionaria)
    frontier: Frontier
    weights: np.ndarray               # (n_asset, H) pesi dei portafogli effettivamente usati
    method: str = "annual"
    custom_weights: bool = False
    meta: dict = field(default_factory=dict)

    @property
    def n_assets(self) -> int:
        return len(self.names)

    @property
    def n_portfolios(self) -> int:
        return self.weights.shape[1]

    @property
    def n_months(self) -> int:
        return self.monthly_returns.shape[0]

    @cached_property
    def stats(self) -> tuple[np.ndarray, np.ndarray]:
        """Rendimento atteso e volatilità annua (da modello) dei portafogli."""
        return portfolio_stats(self.weights, self.mu, self.cov)

    @cached_property
    def compound_returns(self) -> np.ndarray:
        """Rendimento annuo composto (geometrico) atteso dei portafogli, con rendimenti lognormali.

        Il rendimento atteso (aritmetico) sovrastima la crescita di un capitale lasciato investito: la volatilità la riduce
        di circa metà della varianza. Questo è il valore da confrontare con il rendimento costante necessario.
        """
        ret, vol = self.stats
        growth = 1.0 + ret
        return growth**2 / np.sqrt(growth**2 + vol**2) - 1.0

    @cached_property
    def history(self) -> np.ndarray:
        """Serie storica dei portafogli (n_osservazioni, H), ricentrata sui rendimenti attesi."""
        if self.method == "annual":
            windows = recenter_annual(annual_windows(self.monthly_returns), self.mu)
            return windows @ self.weights
        return recenter_monthly(self.monthly_returns, self.mu) @ self.weights

    def draw_scenarios(self, horizon: int, n_scenarios: int, rng: np.random.Generator) -> np.ndarray:
        """Scenari (S, T, H) dei rendimenti annui dei portafogli."""
        draw = bootstrap_annual if self.method == "annual" else bootstrap_monthly
        return draw(self.history, horizon, n_scenarios, rng)

    def with_weights(self, weights: np.ndarray) -> "Market":
        """Sostituisce i portafogli con pesi personalizzati (approccio plug-and-play).

        I portafogli vengono ordinati per volatilità crescente: il glide path può solo ridurre il rischio, e questo
        vale solo se P1 è il meno rischioso e l'ultimo il più rischioso.
        """
        weights = np.asarray(weights, dtype=float)
        if weights.shape[0] != self.n_assets or weights.shape[1] < 2:
            raise ValueError("I pesi devono avere forma (n_asset, n_portafogli).")
        if np.any(weights < -1e-9) or not np.allclose(weights.sum(axis=0), 1.0, atol=1e-6):
            raise ValueError("Ogni portafoglio deve avere pesi non negativi con somma pari a 100%.")
        order = np.argsort(portfolio_stats(weights, self.mu, self.cov)[1], kind="stable")
        weights = weights[:, order]
        ret, vol = portfolio_stats(weights, self.mu, self.cov)
        frontier = Frontier(weights, ret, vol, float(weights.max()))
        return replace(self, weights=weights, frontier=frontier, custom_weights=True)

    def summary(self) -> pd.DataFrame:
        ret, vol = self.stats
        return pd.DataFrame(
            {"Portafoglio": [f"P{i + 1}" for i in range(self.n_portfolios)],
             "Rendimento atteso": ret, "Volatilità": vol,
             "Rapporto R/V": np.divide(ret, vol, out=np.zeros_like(ret), where=vol > 0)}
        )

    def weights_frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            self.weights, index=self.names, columns=[f"P{i + 1}" for i in range(self.n_portfolios)]
        )


class _Reduced(NamedTuple):
    """Problema ridotto: ``basis`` (n x k) riporta i pesi ridotti sugli asset veri."""

    basis: np.ndarray
    mu: np.ndarray
    cov: np.ndarray
    caps: np.ndarray
    rules: np.ndarray | None
    basket_col: int | None          # colonna ridotta della cesta di titoli (l'ultima), se c'è
    n_members: int                  # titoli nella cesta


def _reduction(names: list[str], mu: np.ndarray, cov: np.ndarray, cap, basket: "Basket | None",
               groups: Sequence[Sequence[str]], group_cap: float) -> "_Reduced | None":
    """Riduce il mercato e raccoglie le regole lineari della frontiera.

    * i titoli della cesta diventano un unico asset sintetico (pesi uguali) con la regola «almeno ``min_share``
      dell'esposizione azionaria totale» (fondi azionari più cesta);
    * ogni gruppo di fondi (asset class) pesa al massimo ``group_cap`` in totale, se la somma dei tetti lo consente.

    ``None`` se non c'è nulla da ridurre né da regolare.
    """
    n = len(names)
    position = {t: i for i, t in enumerate(names)}
    members = sorted({position[m] for m in basket.members if m in position}) if basket is not None else []
    use_basket = bool(members) and basket.min_share > 0 and len(members) < n
    others = [i for i in range(n) if not (use_basket and i in set(members))]
    k = len(others) + (1 if use_basket else 0)
    basis = np.zeros((n, k))
    for j, i in enumerate(others):
        basis[i, j] = 1.0
    column = {i: j for j, i in enumerate(others)}
    caps = np.broadcast_to(np.asarray(cap, dtype=float), (n,))[others]
    rules: list[np.ndarray] = []
    if use_basket:
        basis[members, k - 1] = 1.0 / len(members)
        caps = np.concatenate([caps, [basket.max_weight]])
        rule = np.zeros(k)
        rule[k - 1] = 1.0 - basket.min_share
        for ticker in basket.equity:
            if ticker in position and position[ticker] in column:
                rule[column[position[ticker]]] = -basket.min_share
        rules.append(rule)

    grouped: list[list[int]] = []
    for group in groups:
        idx = [column[position[g]] for g in group if g in position and position[g] in column]
        if len(idx) >= 2:
            grouped.append(idx)
    if grouped:
        free = np.ones(k, dtype=bool)
        capacity = 0.0
        for idx in grouped:
            free[idx] = False
            capacity += min(group_cap, float(caps[idx].sum()))
        capacity += float(caps[free].sum())
        if capacity >= 1.0 + 1e-6:                       # con pochi asset i tetti di classe renderebbero il problema impossibile
            for idx in grouped:
                rule = np.full(k, group_cap)
                rule[idx] = group_cap - 1.0              # tetto * somma dei pesi - peso del gruppo >= 0
                rules.append(rule)
    if not use_basket and not rules:
        return None
    return _Reduced(basis, basis.T @ mu, basis.T @ cov @ basis, caps, np.array(rules) if rules else None,
                    k - 1 if use_basket else None, len(members) if use_basket else 0)


def build_market(
    monthly_returns: pd.DataFrame,
    *,
    expected_returns: Mapping[str, float] | None = None,
    max_weight=0.40,
    use_shrinkage: bool = True,
    method: str = "annual",
    n_portfolios: int = 9,
    basket: "Basket | None" = None,
    groups: Sequence[Sequence[str]] = (),
    group_cap: float | None = None,
    min_weight: float = 0.0,
    basket_member_min: float = 0.0,
) -> Market:
    """Costruisce il mercato a partire dai rendimenti mensili (già ripuliti, senza buchi).

    ``max_weight`` è il tetto per asset (un numero, o un valore per ciascuna colonna). Con ``basket`` i titoli indicati
    formano una cesta diversificata trattata come un unico asset nella frontiera (vedi ``Basket``); con ``groups``
    (elenchi di ticker, ad esempio i fondi di una stessa asset class) la somma dei pesi di ciascun gruppo non supera
    ``group_cap`` (predefinito: ``max_weight``). I portafogli risultanti sono espressi sui singoli asset.

    ``min_weight`` è il peso minimo di una posizione (le posizioni più piccole non sono acquistabili in pratica e vengono
    eliminate rifacendo il portafoglio senza di esse, vedi ``portfolios.prune_positions``); ``basket_member_min`` è il
    minimo per ciascun titolo della cesta: la cesta compare in un portafoglio solo se vale almeno quel peso per il
    numero dei suoi titoli.
    """
    if method not in METHODS:
        raise LocalizedError("core.market.bootstrap_method", method=method)
    if monthly_returns.shape[1] < 2:
        raise LocalizedError("core.market.min_assets")
    if monthly_returns.shape[0] < MIN_MONTHS:
        raise LocalizedError("core.market.min_months", months=MIN_MONTHS)
    if monthly_returns.isna().any().any():
        raise LocalizedError("core.market.missing_values")

    names = [str(c) for c in monthly_returns.columns]
    r = monthly_returns.to_numpy(dtype=float)
    mu_hist = expected_annual_return(r)
    mu = mu_hist.copy()
    if expected_returns:
        for i, name in enumerate(names):
            if name in expected_returns and expected_returns[name] is not None:
                mu[i] = float(expected_returns[name])

    if use_shrinkage:
        cov_m, delta = ledoit_wolf_constant_correlation(r)
    else:
        cov_m, delta = np.cov(r, rowvar=False, ddof=0), 0.0
    cov = np.atleast_2d(cov_m) * 12.0

    cap_group = float(np.max(max_weight)) if group_cap is None else float(group_cap)
    reduced = _reduction(names, mu, cov, max_weight, basket, groups, cap_group)
    meta: dict = {}
    if reduced is None:
        frontier = efficient_portfolios(mu, cov, n_portfolios, max_weight)
        if min_weight > 0:
            frontier = _prune_frontier(frontier, mu, cov, max_weight, min_weight)
    else:
        small = efficient_portfolios(reduced.mu, reduced.cov, n_portfolios, reduced.caps, rules=reduced.rules)
        if min_weight > 0 or basket_member_min > 0:
            minimum = np.full(len(reduced.mu), float(min_weight))
            owner: dict[int, int] = {}
            if reduced.basket_col is not None:
                minimum[reduced.basket_col] = basket_member_min * reduced.n_members
                owner = {0: reduced.basket_col}              # la regola «quota minima della cesta» è la prima
            small = _prune_frontier(small, reduced.mu, reduced.cov, reduced.caps, minimum, reduced.rules, owner)
        weights = reduced.basis @ small.weights
        ret, vol = portfolio_stats(weights, mu, cov)
        frontier = Frontier(weights, ret, vol, float(np.max(reduced.caps)), None, small.vol_ceiling)
        if basket is not None and len(reduced.caps) == reduced.basis.shape[1] and reduced.basis.shape[1] < len(names):
            meta["basket"] = {"members": [m for m in basket.members if m in names], "min_share": basket.min_share,
                              "max_weight": basket.max_weight}
    return Market(
        names=names, monthly_returns=r, mu_hist=mu_hist, mu=mu, cov=cov, shrinkage=delta,
        frontier=frontier, weights=frontier.weights, method=method,
        meta={"start": monthly_returns.index[0], "end": monthly_returns.index[-1], **meta},
    )


def _prune_frontier(frontier: Frontier, mu: np.ndarray, cov: np.ndarray, caps, min_weight, rules=None,
                    rule_owner=None) -> Frontier:
    """Frontiera senza posizioni sotto il minimo (portafogli rifatti e riordinati per volatilità)."""
    weights = prune_positions(frontier.weights, mu, cov, caps, min_weight, rules, rule_owner)
    ret, vol = portfolio_stats(weights, mu, cov)
    order = np.argsort(vol, kind="stable")
    return Frontier(weights[:, order], ret[order], vol[order], frontier.max_weight, frontier.caps, frontier.vol_ceiling)
