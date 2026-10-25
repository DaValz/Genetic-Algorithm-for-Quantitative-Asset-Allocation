"""Post-elaborazione dei risultati: benchmark, validazione, proiezioni e robustezza."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np
import pandas as pd

from .genetic import GAConfig, GAResult, run_ga
from .i18n import Msg
from .market import Market
from .problem import Flows, GoalProblem, required_return

QUANTILES = (5, 25, 50, 75, 95)


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervallo di confidenza di Wilson per una proporzione."""
    if n <= 0:
        return 0.0, 1.0
    p = successes / n
    denom = 1.0 + z**2 / n
    centre = (p + z**2 / (2 * n)) / denom
    half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / denom
    return float(centre - half), float(centre + half)


# --------------------------------------------------------------------------------------
# Strategie di confronto (Exhibit 11 del paper)
# --------------------------------------------------------------------------------------
def linear_glide_path(horizon: int, n_portfolios: int) -> np.ndarray:
    """De-risking lineare dal portafoglio più aggressivo al più difensivo."""
    return np.round(np.linspace(n_portfolios, 1, horizon)).astype(int)


def benchmark_table(problem: GoalProblem, ga_path: np.ndarray) -> pd.DataFrame:
    """Confronta il glide path ottimizzato con mix costanti e de-risking lineare.

    La colonna ``Chiave`` identifica la strategia in modo indipendente dalla lingua
    (``ga``, ``linear``, ``const1`` ... ``constH``); ``Strategia`` è l'etichetta italiana di riferimento.
    """
    T, H = problem.T, problem.H
    labels = ["Glide path ottimizzato (GA)", "De-risking lineare"] + [f"Mix costante P{k}" for k in range(1, H + 1)]
    keys = ["ga", "linear"] + [f"const{k}" for k in range(1, H + 1)]
    paths = np.vstack([ga_path, linear_glide_path(T, H)] + [np.full(T, k) for k in range(1, H + 1)])
    ev = problem.evaluate(paths)
    return pd.DataFrame({
        "Chiave": keys,
        "Strategia": labels,
        "Probabilità di successo": ev.pr,
        "IRR atteso (coda)": ev.irr_es,
        "Patrimonio finale medio (coda)": ev.tail_wealth,
        "Soglia rispettata": ev.feasible,
        "Score": ev.score,
    })


# --------------------------------------------------------------------------------------
# Validazione fuori campione
# --------------------------------------------------------------------------------------
@dataclass
class OutOfSample:
    n_scenarios: int
    pr: float
    pr_low: float
    pr_high: float
    irr_es: float
    tail_wealth: float
    feasible: bool
    benchmarks: pd.DataFrame | None = None     # confronto con le strategie semplici sugli stessi scenari nuovi


def out_of_sample(
    market: Market, flows: Flows, path: np.ndarray, *, pr_target: float, alpha: float,
    n_scenarios: int = 10_000, seed: int = 12345,
) -> OutOfSample:
    """Rivaluta il glide path su scenari *nuovi* (non usati dall'algoritmo genetico).

    L'algoritmo ottimizza su un solo insieme di scenari e tende quindi a sovrastimare la
    probabilità di successo ("maledizione del vincitore"): questo test misura lo scarto. Anche il confronto con i mix
    costanti e il de-risking lineare è rifatto sugli scenari nuovi: sugli scenari della ricerca il glide path parte
    avvantaggiato, perché è stato scelto proprio su quelli.
    """
    rng = np.random.default_rng(seed)
    scenarios = market.draw_scenarios(flows.horizon, n_scenarios, rng)
    problem = GoalProblem(flows, scenarios, pr_target, alpha)
    ev = problem.evaluate(path)
    successes = int(round(float(ev.pr[0]) * n_scenarios))
    low, high = wilson_interval(successes, n_scenarios)
    return OutOfSample(n_scenarios, float(ev.pr[0]), low, high, float(ev.irr_es[0]),
                       float(ev.tail_wealth[0]), bool(ev.feasible[0]), benchmark_table(problem, path))


# --------------------------------------------------------------------------------------
# Report completo
# --------------------------------------------------------------------------------------
@dataclass
class OptimizationReport:
    path: np.ndarray
    ga: GAResult
    pr: float
    irr_es: float
    tail_wealth: float
    required_return: float | None
    expected_path_return: float
    switches: int
    fan: pd.DataFrame            # anni 0..T: percentili e patrimonio a rendimento atteso
    goals: pd.DataFrame          # una riga per obiettivo
    terminal: np.ndarray         # patrimonio finale per scenario (in-sample)
    terminal_quantiles: pd.Series
    benchmarks: pd.DataFrame
    composition: pd.DataFrame    # anni 1..T x asset
    path_stats: pd.DataFrame     # anni 1..T: rendimento atteso e volatilità del portafoglio scelto
    oos: OutOfSample | None
    irr_reliable: bool = True
    warnings: list[str] = field(default_factory=list)
    expected_path_growth: float = float("nan")   # rendimento annuo composto atteso lungo il percorso (confrontabile col richiesto)

    @property
    def benchmarks_validated(self) -> pd.DataFrame:
        """Confronto con le strategie semplici sugli scenari nuovi, se la validazione c'è; altrimenti su quelli della ricerca."""
        if self.oos is not None and self.oos.benchmarks is not None:
            return self.oos.benchmarks
        return self.benchmarks


def build_report(
    market: Market, flows: Flows, problem: GoalProblem, ga: GAResult, *,
    oos_scenarios: int = 10_000, oos_seed: int = 12345,
) -> OptimizationReport:
    path = np.asarray(ga.path, dtype=int)
    T = flows.horizon
    ret, vol = market.stats

    wealth = problem.wealth_paths(path)
    fan = pd.DataFrame(
        np.percentile(wealth.post, QUANTILES, axis=0).T, columns=[f"P{q}" for q in QUANTILES]
    )
    expected = np.empty(T + 1)
    expected[0] = flows.w0
    for t in range(T):
        step = 1.0 + ret[path[t] - 1]
        if t == 0 and flows.first_period != 1.0:
            step = step ** flows.first_period
        expected[t + 1] = expected[t] * step + flows.net[t]
    fan["Atteso"] = expected
    fan.index = pd.RangeIndex(0, T + 1, name="Anno")

    rows = []
    for year in flows.goal_years:
        t = int(year) - 1
        amount = float(flows.goals[t])
        coverage = wealth.pre_goal[:, t] / amount
        rows.append({
            "Anno": int(year), "Obiettivo": amount,
            "Probabilità cumulata di successo": float(wealth.joint_ok[:, t].mean()),
            "Copertura mediana": float(np.median(coverage)),
            "Copertura nel 5° percentile": float(np.percentile(coverage, 5)),
        })
    goals = pd.DataFrame(rows)

    terminal = wealth.post[:, -1]
    terminal_q = pd.Series(np.percentile(terminal, [1, 5, 25, 50, 75, 95, 99]),
                           index=["1°", "5°", "25°", "50°", "75°", "95°", "99°"])

    composition = pd.DataFrame(market.weights[:, path - 1].T, columns=market.names,
                               index=pd.RangeIndex(1, T + 1, name="Anno"))
    path_stats = pd.DataFrame({"Portafoglio": path, "Rendimento atteso": ret[path - 1],
                               "Volatilità": vol[path - 1]},
                              index=pd.RangeIndex(1, T + 1, name="Anno"))

    oos = None
    if oos_scenarios:
        oos = out_of_sample(market, flows, path, pr_target=problem.pr_target, alpha=problem.alpha,
                            n_scenarios=oos_scenarios, seed=oos_seed)

    notes: list[str] = []
    if not problem.irr_reliable:
        notes.append(Msg("core.report.irr_unreliable"))
    return OptimizationReport(
        path=path, ga=ga, pr=ga.pr, irr_es=ga.irr_es, tail_wealth=ga.tail_wealth,
        required_return=required_return(flows),
        expected_path_return=float(np.mean(ret[path - 1])),
        switches=int(np.count_nonzero(np.diff(path))),
        fan=fan, goals=goals, terminal=terminal, terminal_quantiles=terminal_q,
        benchmarks=benchmark_table(problem, path), composition=composition, path_stats=path_stats,
        oos=oos, irr_reliable=problem.irr_reliable, warnings=notes,
        expected_path_growth=float(np.expm1(np.mean(np.log1p(market.compound_returns[path - 1])))),
    )


# --------------------------------------------------------------------------------------
# Robustezza: lanci indipendenti (Exhibit 9-10 del paper)
# --------------------------------------------------------------------------------------
@dataclass
class RobustnessReport:
    paths: np.ndarray            # (K, T)
    pr: np.ndarray
    irr_es: np.ndarray
    feasible: np.ndarray
    lower: np.ndarray            # minimo per anno
    upper: np.ndarray            # massimo per anno
    median: np.ndarray
    modal_share: float           # quota di lanci a distanza <= 1 "tacca" dal percorso mediano
    max_deviation: int           # massima distanza (in tacche) dal percorso mediano


def run_robustness(
    market: Market, flows: Flows, *, pr_target: float, alpha: float, ga_config: GAConfig,
    n_runs: int = 10, n_scenarios: int = 1000, seed: int = 2024,
    progress: Callable[[int, int], None] | None = None,
) -> RobustnessReport:
    """Ripete l'ottimizzazione con scenari e popolazioni iniziali indipendenti."""
    seeds = np.random.SeedSequence(seed).spawn(n_runs)
    paths, prs, irrs, feas = [], [], [], []
    for k, ss in enumerate(seeds):
        rng = np.random.default_rng(ss)
        scenarios = market.draw_scenarios(flows.horizon, n_scenarios, rng)
        problem = GoalProblem(flows, scenarios, pr_target, alpha)
        cfg = GAConfig(**{**ga_config.__dict__, "seed": int(ss.generate_state(1)[0])})
        res = run_ga(problem, cfg)
        paths.append(res.path)
        prs.append(res.pr)
        irrs.append(res.irr_es)
        feas.append(res.feasible)
        if progress:
            progress(k + 1, n_runs)
    P = np.vstack(paths)
    median = np.round(np.median(P, axis=0)).astype(int)
    dev = np.abs(P - median[None, :]).max(axis=1)
    return RobustnessReport(
        paths=P, pr=np.array(prs), irr_es=np.array(irrs), feasible=np.array(feas),
        lower=P.min(axis=0), upper=P.max(axis=0), median=median,
        modal_share=float(np.mean(dev <= 1)), max_deviation=int(dev.max()),
    )
