"""Modello di pianificazione per obiettivi (goal-based investing).

Convenzioni, coerenti con Pomante, Farina e Cucurachi (2024):

* ``t = 0`` è oggi e il capitale iniziale ``W0`` viene investito in ``t = 0``.
* Durante l'anno ``t`` (da ``t-1`` a ``t``) il portafoglio scelto per quell'anno rende ``r_t``.
* A fine anno ``t`` vengono regolati insieme il versamento ``c_t`` e l'eventuale uscita
  per obiettivo ``g_t``.
* Probabilità di successo ``Pr_Goal``: quota di scenari in cui il patrimonio non è mai
  negativo dopo il regolamento di ciascun obiettivo (equivale a "in ogni istante il capitale
  investito è positivo", perché tra due obiettivi il patrimonio non può diventare negativo).
* IRR: tasso interno di rendimento dei flussi dell'investitore ``-W0, (g_t - c_t), +W_T`` dove
  ``W_T`` è il patrimonio terminale (negativo = deficit).  Poiché i flussi intermedi sono uguali in
  tutti gli scenari, l'IRR è l'inversa della funzione ``V(r)`` (valore terminale di un conto che
  rende sempre ``r``) calcolata in ``W_T``: ciò consente di ottenerlo senza risolvere polinomi.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping

import numpy as np

from .i18n import LocalizedError

IRR_MIN, IRR_MAX, IRR_STEP = -0.99, 1.0, 1e-4
_MAX_CELLS = 6_000_000  # dimensione massima (N x S) di un blocco di simulazione


# --------------------------------------------------------------------------------------
# Flussi
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Flows:
    """Flussi annuali deterministici del piano (importi nominali, a fine anno).

    ``first_period`` è la durata del primo anno in anni (1 = anno intero): serve ai piani che ripartono a metà anno,
    quando il primo flusso arriva al prossimo anniversario e non tra dodici mesi esatti.
    """

    w0: float
    contributions: np.ndarray  # shape (T,), indice t-1 -> versamento a fine anno t
    goals: np.ndarray          # shape (T,), indice t-1 -> uscita a fine anno t
    first_period: float = 1.0

    def __post_init__(self) -> None:
        if self.contributions.shape != self.goals.shape or self.goals.ndim != 1:
            raise ValueError("contributions e goals devono avere la stessa lunghezza (T).")
        if self.w0 < 0 or np.any(self.contributions < 0) or np.any(self.goals < 0):
            raise ValueError("Capitale, versamenti e obiettivi devono essere non negativi.")
        if not 0.0 < self.first_period <= 1.0:
            raise ValueError("first_period deve essere in (0, 1].")

    @property
    def horizon(self) -> int:
        return int(self.goals.shape[0])

    @property
    def net(self) -> np.ndarray:
        return self.contributions - self.goals

    @property
    def goal_years(self) -> np.ndarray:
        """Anni (1-based) in cui è previsto un obiettivo."""
        return np.flatnonzero(self.goals > 0) + 1


def build_flows(
    w0: float,
    horizon: int,
    annual_contribution: float = 0.0,
    last_contribution_year: int | None = None,
    contribution_growth: float = 0.0,
    goals: Mapping[int, float] | Iterable[tuple[int, float]] | None = None,
    goal_inflation: float = 0.0,
    first_period: float = 1.0,
) -> Flows:
    """Costruisce i flussi del piano.

    ``last_contribution_year`` vale ``horizon - 1`` per default (convenzione del paper: un
    versamento a fine ultimo anno coinciderebbe con l'orizzonte e non verrebbe investito).
    Più obiettivi nello stesso anno vengono **sommati**; gli importi sono espressi in euro
    di oggi e rivalutati con ``goal_inflation`` annua.
    """
    if horizon < 2:
        raise LocalizedError("core.flows.horizon")
    if last_contribution_year is None:
        last_contribution_year = horizon - 1
    last_contribution_year = int(min(max(last_contribution_year, 0), horizon))

    years = np.arange(1, horizon + 1)
    contributions = np.where(
        years <= last_contribution_year,
        annual_contribution * (1.0 + contribution_growth) ** (years - 1),
        0.0,
    )

    goal_arr = np.zeros(horizon)
    items = goals.items() if isinstance(goals, Mapping) else (goals or [])
    for year, amount in items:
        year = int(year)
        if not 1 <= year <= horizon:
            raise LocalizedError("core.flows.goal_out", year=year, horizon=horizon)
        goal_arr[year - 1] += float(amount) * (1.0 + goal_inflation) ** year
    return Flows(float(w0), contributions.astype(float), goal_arr, float(first_period))


def terminal_value_curve(flows: Flows, rates: np.ndarray) -> np.ndarray:
    """``V(r)``: patrimonio finale di un conto che rende sempre ``r`` con i flussi del piano."""
    rates = np.asarray(rates, dtype=float)
    T = flows.horizon
    growth = 1.0 + rates
    exponents = T - np.arange(1, T + 1)
    powers = growth[:, None] ** exponents[None, :]
    span = T if flows.first_period == 1.0 else T - 1 + flows.first_period
    return flows.w0 * growth**span + powers @ flows.net


def required_return(flows: Flows, r_min: float = -0.5, r_max: float = 0.8) -> float | None:
    """Rendimento annuo costante minimo che soddisfa tutti gli obiettivi.

    È il più piccolo ``r`` tale che il patrimonio dopo ogni obiettivo resta >= 0 per ogni
    rendimento costante >= r.  Restituisce ``None`` se non esiste entro ``r_max`` (o se non
    ci sono obiettivi).
    """
    if flows.goals.max() <= 0:
        return None

    def min_goal_wealth(rates: np.ndarray) -> np.ndarray:
        growth = 1.0 + rates
        w = np.full(rates.shape, flows.w0)
        worst = np.full(rates.shape, np.inf)
        for t in range(flows.horizon):
            w = w * (growth ** flows.first_period if t == 0 and flows.first_period != 1.0 else growth) + flows.net[t]
            if flows.goals[t] > 0:
                worst = np.minimum(worst, w)
        return worst

    grid = np.arange(r_min, r_max + 1e-12, 5e-4)
    ok = min_goal_wealth(grid) >= 0
    if not ok[-1]:
        return None
    bad = np.flatnonzero(~ok)
    if bad.size == 0:
        return float(r_min)
    a, b = float(grid[bad[-1]]), float(grid[bad[-1] + 1])
    for _ in range(60):
        mid = 0.5 * (a + b)
        if min_goal_wealth(np.array([mid]))[0] >= 0:
            b = mid
        else:
            a = mid
    return float(b)


# --------------------------------------------------------------------------------------
# Valutazione
# --------------------------------------------------------------------------------------
@dataclass
class Evaluation:
    """Metriche di N strategie (ognuna è una sequenza di T indici di portafoglio)."""

    pr: np.ndarray           # probabilità di successo
    irr_es: np.ndarray       # IRR medio nel peggior alpha% degli scenari
    tail_wealth: np.ndarray  # patrimonio finale medio nel peggior alpha% (negativo = deficit)
    score: np.ndarray        # funzione obiettivo S (Eq. 1 del paper)
    feasible: np.ndarray     # Pr >= Pr*


@dataclass
class WealthPaths:
    post: np.ndarray      # (S, T+1) patrimonio dopo i flussi di fine anno (t = 0..T)
    pre_goal: np.ndarray  # (S, T) patrimonio appena prima di pagare l'obiettivo (nan se assente)
    joint_ok: np.ndarray  # (S, T) True se tutti gli obiettivi fino all'anno t sono soddisfatti


class GoalProblem:
    """Problema di allocazione dinamica per obiettivi su un insieme fisso di scenari."""

    def __init__(
        self,
        flows: Flows,
        scenarios: np.ndarray,
        pr_target: float = 0.95,
        alpha: float = 0.02,
    ) -> None:
        if scenarios.ndim != 3 or scenarios.shape[1] != flows.horizon:
            raise ValueError("scenarios deve avere forma (S, T, H) con T pari all'orizzonte.")
        if not 0 < pr_target <= 1:
            raise ValueError("La probabilità minima di successo deve essere in (0, 1].")
        if not 0 < alpha <= 1:
            raise ValueError("alpha deve essere in (0, 1].")
        self.flows = flows
        self.S, self.T, self.H = scenarios.shape
        self.pr_target = float(pr_target)
        self.alpha = float(alpha)
        self.min_successes = int(np.ceil(pr_target * self.S - 1e-9))
        self.n_worst = max(1, int(round(alpha * self.S)))
        # (T, H, S): per ogni anno e portafoglio, i fattori di crescita sugli S scenari
        self._gf = np.ascontiguousarray(1.0 + scenarios.transpose(1, 2, 0))
        if flows.first_period != 1.0:                      # primo anno parziale: crescita elevata alla frazione d'anno
            self._gf[0] = self._gf[0] ** flows.first_period
        self._net = flows.net
        self._goal_mask = flows.goals > 0
        self._build_irr_inverse()

    # ------------------------------------------------------------------ IRR
    def _build_irr_inverse(self) -> None:
        self._r_grid = np.arange(IRR_MIN, IRR_MAX + IRR_STEP / 2, IRR_STEP)
        v = terminal_value_curve(self.flows, self._r_grid)
        self.irr_reliable = bool(np.all(np.diff(v) > 0))
        if not self.irr_reliable:  # inviluppo monotono: IRR definito ma meno affidabile
            v = np.maximum.accumulate(v) + np.arange(v.size) * 1e-9
        self._v_grid = v

    def irr_from_terminal(self, terminal_wealth: np.ndarray) -> np.ndarray:
        """IRR dei flussi dell'investitore dato il patrimonio terminale (vettorizzato)."""
        w = np.asarray(terminal_wealth, dtype=float)
        irr = np.interp(w, self._v_grid, self._r_grid)
        return np.where(w < self._v_grid[0], -1.0, irr)

    # ------------------------------------------------------------ simulazione
    def _simulate(self, idx: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        n = idx.shape[0]
        W = np.full((n, self.S), self.flows.w0, dtype=np.float64)
        ok = np.ones((n, self.S), dtype=bool)
        for t in range(self.T):
            W *= self._gf[t][idx[:, t]]
            W += self._net[t]
            if self._goal_mask[t]:
                ok &= W >= 0.0
        return W, ok

    def evaluate(self, paths: np.ndarray) -> Evaluation:
        """Valuta una o più strategie. ``paths``: indici di portafoglio 1-based, shape (N, T)."""
        paths = np.atleast_2d(np.asarray(paths, dtype=np.int64))
        if paths.shape[1] != self.T:
            raise ValueError(f"Ogni strategia deve avere T={self.T} elementi.")
        if paths.min() < 1 or paths.max() > self.H:
            raise ValueError(f"Gli indici di portafoglio devono essere in 1..{self.H}.")
        idx = paths - 1
        chunk = max(1, _MAX_CELLS // self.S)
        parts = [self._evaluate_block(idx[i : i + chunk]) for i in range(0, idx.shape[0], chunk)]
        fields = ("pr", "irr_es", "tail_wealth", "score", "feasible")
        return Evaluation(*(np.concatenate([getattr(p, f) for p in parts]) for f in fields))

    def _evaluate_block(self, idx: np.ndarray) -> Evaluation:
        W, ok = self._simulate(idx)
        successes = ok.sum(axis=1)
        pr = successes / self.S
        k = self.n_worst
        worst = np.partition(W, k - 1, axis=1)[:, :k] if k < self.S else W
        irr_es = self.irr_from_terminal(worst).mean(axis=1)
        tail = worst.mean(axis=1)
        feasible = successes >= self.min_successes
        score = np.where(feasible, 2.0 + irr_es, pr)
        return Evaluation(pr, irr_es, tail, score, feasible)

    def terminal_wealth(self, path: np.ndarray) -> np.ndarray:
        """Patrimonio finale in ciascuno scenario per una singola strategia."""
        W, _ = self._simulate(np.asarray(path, dtype=np.int64)[None, :] - 1)
        return W[0]

    def wealth_paths(self, path: np.ndarray) -> WealthPaths:
        """Traiettorie del patrimonio di una strategia (grafici e analisi per obiettivo)."""
        idx = np.asarray(path, dtype=np.int64) - 1
        post = np.empty((self.S, self.T + 1))
        pre_goal = np.full((self.S, self.T), np.nan)
        joint = np.empty((self.S, self.T), dtype=bool)
        post[:, 0] = self.flows.w0
        alive = np.ones(self.S, dtype=bool)
        for t in range(self.T):
            w = post[:, t] * self._gf[t][idx[t]] + self.flows.contributions[t]
            if self._goal_mask[t]:
                pre_goal[:, t] = w
                w = w - self.flows.goals[t]
                alive &= w >= 0.0
            post[:, t + 1] = w
            joint[:, t] = alive
        return WealthPaths(post, pre_goal, joint)
