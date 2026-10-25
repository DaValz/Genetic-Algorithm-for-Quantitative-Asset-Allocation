"""Costruzione dei 9 portafogli A-O (asset-only) sulla frontiera efficiente.

Il paper lascia libera la scelta del modello A-O ("plug-and-play"): qui i portafogli sono
punti della frontiera efficiente media-varianza *long-only* con tetto al peso del singolo asset,
ordinati per volatilità crescente (1 = più difensivo, 9 = più aggressivo).  La covarianza può
essere stabilizzata con lo shrinkage di Ledoit-Wolf (target a correlazione costante).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

import numpy as np
from scipy.optimize import linprog, minimize

from .i18n import LocalizedError


# --------------------------------------------------------------------------------------
# Covarianza
# --------------------------------------------------------------------------------------
def ledoit_wolf_constant_correlation(returns: np.ndarray) -> tuple[np.ndarray, float]:
    """Stimatore di Ledoit-Wolf (2003) con target a correlazione costante.

    Preserva le varianze campionarie e restringe solo le correlazioni verso la loro media.
    Restituisce ``(covarianza, intensità di shrinkage)``; la covarianza è per periodo.
    """
    x = np.asarray(returns, dtype=float)
    t, n = x.shape
    x = x - x.mean(axis=0)
    s = x.T @ x / t
    if n < 2:
        return s, 0.0
    var = np.diag(s).copy()
    sd = np.sqrt(var)
    if np.any(sd <= 0):
        return s, 0.0
    corr = s / np.outer(sd, sd)
    rbar = (corr.sum() - n) / (n * (n - 1))
    target = rbar * np.outer(sd, sd)
    np.fill_diagonal(target, var)

    x2 = x**2
    pi_mat = x2.T @ x2 / t - s**2
    pi_hat = pi_mat.sum()
    theta = (x**3).T @ x / t - var[:, None] * s  # theta[i, j] = cov(x_i^2, x_i x_j)
    a = (sd[None, :] / sd[:, None]) * theta
    rho_hat = np.trace(pi_mat) + rbar * (a.sum() - np.trace(a))
    gamma_hat = np.sum((target - s) ** 2)
    if gamma_hat < 1e-20:
        return s, 0.0
    delta = float(np.clip((pi_hat - rho_hat) / gamma_hat / t, 0.0, 1.0))
    return delta * target + (1.0 - delta) * s, delta


# --------------------------------------------------------------------------------------
# Frontiera efficiente
# --------------------------------------------------------------------------------------
@dataclass
class Frontier:
    weights: np.ndarray   # (n_assets, n_portfolios), colonne ordinate per volatilità crescente
    returns: np.ndarray   # rendimento atteso annuo di ciascun portafoglio
    vols: np.ndarray      # volatilità annua di ciascun portafoglio
    max_weight: float     # tetto (il più alto, se ce n'è uno per asset) effettivamente applicato
    caps: np.ndarray | None = None   # tetti applicati a ciascun asset (None = tetto unico)
    vol_ceiling: float | None = None  # volatilità massima consentita al portafoglio più aggressivo, se imposta

    @property
    def degenerate(self) -> bool:
        """True se i portafogli sono (quasi) indistinguibili tra loro."""
        return bool(self.vols[-1] - self.vols[0] < 1e-4)


def portfolio_stats(weights: np.ndarray, mu: np.ndarray, cov: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    w = np.atleast_2d(weights.T).T if weights.ndim == 1 else weights
    ret = mu @ w
    vol = np.sqrt(np.einsum("ip,ij,jp->p", w, cov, w))
    return np.atleast_1d(ret), np.atleast_1d(vol)


def _project(w: np.ndarray, caps: np.ndarray) -> np.ndarray:
    """Pesi non negativi, entro i tetti e con somma pari a 1 (il surplus va agli asset con margine)."""
    w = np.clip(np.nan_to_num(np.asarray(w, dtype=float)), 0.0, caps)
    if w.sum() <= 0:
        w = caps / caps.sum()
    else:
        w = w / w.sum()
    for _ in range(50):
        w = np.minimum(w, caps)
        deficit = 1.0 - w.sum()
        if abs(deficit) < 1e-13:
            break
        slack = caps - w if deficit > 0 else w
        if slack.sum() <= 1e-15:
            break
        w = np.clip(w + deficit * slack / slack.sum(), 0.0, caps)
    return w


def _caps_array(max_weight, n: int) -> np.ndarray:
    """Tetti per asset: un numero unico o uno per asset; sempre ammissibili (somma >= 1, almeno due asset)."""
    caps = np.clip(np.broadcast_to(np.asarray(max_weight, dtype=float), (n,)).copy(), 0.0, 1.0)
    caps = np.maximum(caps, min(1.0, 2.0 / n))           # con pochi asset un tetto stretto forzerebbe pesi uguali
    total = caps.sum()
    if total < 1.0 + 1e-9:
        caps = np.minimum(1.0, caps * (1.0 + 1e-6) / total) if total > 0 else np.full(n, 1.0)
        if caps.sum() < 1.0:
            caps = np.full(n, 1.0)
    return caps


def _max_return_weights(mu: np.ndarray, caps: np.ndarray, rules: np.ndarray | None = None) -> np.ndarray:
    """Portafoglio a massimo rendimento atteso entro i tetti (e le eventuali regole lineari ``rules @ w >= 0``)."""
    n = mu.size
    if rules is not None and len(rules):
        res = linprog(-mu, A_ub=-rules, b_ub=np.zeros(len(rules)), A_eq=np.ones((1, n)), b_eq=[1.0],
                      bounds=list(zip(np.zeros(n), caps)), method="highs")
        if res.success:
            return _project(res.x, caps)
    w = np.zeros_like(mu)
    remaining = 1.0
    for i in np.argsort(-mu, kind="stable"):
        w[i] = min(caps[i], remaining)
        remaining -= w[i]
        if remaining <= 1e-12:
            break
    return w


def _rule_constraints(rules: np.ndarray | None) -> list[dict]:
    if rules is None or not len(rules):
        return []
    return [{"type": "ineq", "fun": lambda w: rules @ w, "jac": lambda w: rules}]


def _min_variance_weights(cov: np.ndarray, caps: np.ndarray, rules: np.ndarray | None = None,
                          start: np.ndarray | None = None) -> np.ndarray:
    n = cov.shape[0]
    scale = np.mean(np.diag(cov))
    c = cov / scale
    res = minimize(
        lambda w: w @ c @ w, caps / caps.sum() if start is None else start, jac=lambda w: 2.0 * c @ w,
        bounds=list(zip(np.zeros(n), caps)), method="SLSQP",
        constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0, "jac": lambda w: np.ones(n)},
                     *_rule_constraints(rules)],
        options={"maxiter": 500, "ftol": 1e-14},
    )
    return _project(res.x, caps)


def _max_return_given_vol(
    mu: np.ndarray, cov: np.ndarray, vol_target: float, caps: np.ndarray, x0: np.ndarray,
    rules: np.ndarray | None = None,
) -> np.ndarray:
    n = mu.size
    scale = np.mean(np.diag(cov))
    c = cov / scale
    var_target = vol_target**2 / scale
    mu_s = mu / max(np.abs(mu).max(), 1e-12)
    cons = [
        {"type": "eq", "fun": lambda w: w.sum() - 1.0, "jac": lambda w: np.ones(n)},
        {"type": "ineq", "fun": lambda w: var_target - w @ c @ w, "jac": lambda w: -2.0 * c @ w},
        *_rule_constraints(rules),
    ]
    res = minimize(
        lambda w: -mu_s @ w, x0, jac=lambda w: -mu_s, bounds=list(zip(np.zeros(n), caps)),
        constraints=cons, method="SLSQP", options={"maxiter": 500, "ftol": 1e-14},
    )
    w = _project(res.x, caps)
    # in caso di mancata convergenza si ripiega sul punto di partenza (ammissibile)
    if not res.success and np.sqrt(w @ cov @ w) > vol_target * 1.001:
        return _project(x0, caps)
    return w


def _vol(w: np.ndarray, cov: np.ndarray) -> float:
    return float(np.sqrt(max(w @ cov @ w, 0.0)))


def _mix_at_vol(w_min: np.ndarray, w_max: np.ndarray, cov: np.ndarray, vol_target: float) -> np.ndarray:
    """Combinazione dei due portafogli estremi con volatilità pari al target (la volatilità cresce con il peso di ``w_max``)."""
    lo, hi = 0.0, 1.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if _vol((1.0 - mid) * w_min + mid * w_max, cov) <= vol_target:
            lo = mid
        else:
            hi = mid
    return (1.0 - lo) * w_min + lo * w_max


def efficient_portfolios(
    mu: np.ndarray, cov: np.ndarray, n_portfolios: int = 9, max_weight=1.0, vol_ceiling: float | None = None,
    rules: np.ndarray | None = None,
) -> Frontier:
    """Calcola ``n_portfolios`` portafogli efficienti equispaziati in volatilità.

    Il primo è il portafoglio a minima varianza, l'ultimo quello a massimo rendimento atteso compatibile con i
    tetti ``max_weight`` (un numero, oppure uno per asset), con l'eventuale ``vol_ceiling`` e con le regole lineari
    ``rules @ w >= 0`` (una per riga); quelli intermedi massimizzano il rendimento a parità di volatilità target.
    """
    mu = np.asarray(mu, dtype=float)
    cov = np.asarray(cov, dtype=float)
    n = mu.size
    if n < 2:
        raise LocalizedError("core.market.min_assets")
    caps = _caps_array(max_weight, n)
    rules = None if rules is None or not np.size(rules) else np.atleast_2d(np.asarray(rules, dtype=float))

    w_max = _max_return_weights(mu, caps, rules)
    w_min = _min_variance_weights(cov, caps, rules, start=w_max if rules is not None else None)
    vol_min = _vol(w_min, cov)
    vol_max = _vol(w_max, cov)
    ceiling = None
    if vol_ceiling is not None and vol_ceiling > 0:
        ceiling = max(float(vol_ceiling), vol_min)
        if vol_max > ceiling * (1.0 + 1e-9):
            start = _mix_at_vol(w_min, w_max, cov, ceiling)
            w_max = _max_return_given_vol(mu, cov, ceiling, caps, start, rules)
            vol_max = _vol(w_max, cov)

    columns = [w_min]
    if n_portfolios > 2:
        for k in range(1, n_portfolios - 1):
            lam = k / (n_portfolios - 1)
            target = vol_min + lam * (vol_max - vol_min)
            columns.append(_max_return_given_vol(mu, cov, target, caps, _mix_at_vol(w_min, w_max, cov, target), rules))
    columns.append(w_max)
    weights = np.column_stack(columns)

    ret, vol = portfolio_stats(weights, mu, cov)
    order = np.argsort(vol, kind="stable")
    uniform = bool(np.all(caps == caps[0]))
    return Frontier(weights[:, order], ret[order], vol[order], float(caps.max()),
                    None if uniform else caps, ceiling)


# --------------------------------------------------------------------------------------
# Posizioni minime
# --------------------------------------------------------------------------------------
def _solve_at_vol(mu: np.ndarray, cov: np.ndarray, target: float, caps: np.ndarray, rules: np.ndarray | None,
                  start: np.ndarray) -> np.ndarray:
    """Massimo rendimento con volatilità non oltre ``target``; se il target non è raggiungibile, la minima varianza."""
    w_min = _min_variance_weights(cov, caps, rules, start=start)
    if target <= _vol(w_min, cov) * (1.0 + 1e-9):
        return w_min
    return _max_return_given_vol(mu, cov, target, caps, w_min, rules)


def prune_positions(
    weights: np.ndarray, mu: np.ndarray, cov: np.ndarray, caps, min_weight, rules: np.ndarray | None = None,
    rule_owner: Mapping[int, int] | None = None, rounds: int = 8,
) -> np.ndarray:
    """Elimina le posizioni troppo piccole per essere acquistate davvero, mantenendo il portafoglio efficiente.

    Per ogni portafoglio (colonna di ``weights``) la posizione non nulla più piccola tra quelle sotto ``min_weight`` (un
    numero, o uno per asset) viene esclusa e il portafoglio è rifatto senza di essa: massimo rendimento a parità di
    volatilità, entro gli stessi tetti e le stesse regole. Si ripete finché non resta alcuna posizione sotto il minimo.
    ``rule_owner`` indica, per le regole che dipendono dalla presenza di un asset (riga della regola -> asset), quali
    vanno tolte quando quell'asset è escluso (es. «la cesta vale almeno il 30% dell'azionario» non ha senso senza cesta).
    """
    out = np.array(weights, dtype=float, copy=True)
    n, h = out.shape
    caps = _caps_array(caps, n)
    minimum = np.broadcast_to(np.asarray(min_weight, dtype=float), (n,))
    rules = None if rules is None or not np.size(rules) else np.atleast_2d(np.asarray(rules, dtype=float))
    owner = dict(rule_owner or {})
    for j in range(h):
        w = out[:, j]
        target = _vol(w, cov)
        allowed = np.ones(n, dtype=bool)
        for _ in range(rounds):
            tiny = allowed & (w > 1e-9) & (w < minimum - 1e-9)
            if not tiny.any():
                break
            trial = allowed.copy()
            trial[int(np.argmin(np.where(tiny, w, np.inf)))] = False
            caps_now = np.where(trial, caps, 0.0)
            if caps_now.sum() < 1.0 + 1e-6:
                break                                   # senza quell'asset non si arriva al 100%: si tiene la posizione
            if rules is None:
                active = None
            else:
                keep = [i for i in range(len(rules)) if owner.get(i) is None or trial[owner[i]]]
                active = rules[keep] if keep else None
            w = _solve_at_vol(mu, cov, target, caps_now, active, _project(w * trial, caps_now))
            w = _project(np.where(w < 1e-9, 0.0, w), caps_now)
            allowed = trial
        out[:, j] = w
    return out
