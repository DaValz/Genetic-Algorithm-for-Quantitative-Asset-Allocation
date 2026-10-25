"""Algoritmo genetico per il glide path ottimale (sezione IV del paper).

Codifica: un individuo è la sequenza ``I_1 >= I_2 >= ... >= I_T`` di indici di portafoglio
(1 = più difensivo, H = più aggressivo): il rischio non può aumentare nel tempo (Eq. 2).

Operatori (fedeli al paper):

* popolazione iniziale pseudo-casuale con *intervalli di variazione diversi* per massimizzare la
  diversità (nota 8);
* selezione con torneo binario, estrazione con reinserimento, finché il mating pool ha la stessa
  dimensione della popolazione;
* crossover a un punto con probabilità ``p_c``; i figli che violano il vincolo vengono scartati;
* mutazione con probabilità ``p_m``: un gene scelto a caso varia di ±v; se il vincolo è violato la
  soluzione viene corretta *minimizzando le modifiche* (i geni precedenti vengono alzati, o quelli
  successivi abbassati, solo quanto basta - cfr. esempio ``8 8 7 7 8 3 2 1 -> 8 8 8 8 8 3 2 1``);
* terminazione se la miglior soluzione non migliora per ``patience`` generazioni (200 nel paper).

Scelte di implementazione non descritte nel paper: elitismo (1 individuo, disattivabile con
``elitism=0``) e un tetto massimo di generazioni per garantire la terminazione.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .problem import GoalProblem


@dataclass(frozen=True)
class GAConfig:
    pop_size: int = 100      # paper: 100 (range testato 100-300)
    p_c: float = 0.55        # probabilità di crossover (paper: 0.55)
    p_m: float = 0.30        # probabilità di mutazione (paper: 0.30)
    mut_v: int = 2           # ampiezza massima della mutazione (paper: ±2)
    patience: int = 200      # generazioni senza miglioramento prima di fermarsi (paper: 200)
    max_generations: int = 1000
    elitism: int = 1
    seed: int | None = 42

    def validate(self) -> None:
        if self.pop_size < 4:
            raise ValueError("La popolazione deve contare almeno 4 individui.")
        if not (0.0 <= self.p_c <= 1.0 and 0.0 <= self.p_m <= 1.0):
            raise ValueError("p_c e p_m devono essere probabilità in [0, 1].")
        if self.mut_v < 1:
            raise ValueError("L'ampiezza di mutazione deve essere >= 1.")
        if self.patience < 1 or self.max_generations < 1:
            raise ValueError("patience e max_generations devono essere >= 1.")
        if not 0 <= self.elitism < self.pop_size:
            raise ValueError("L'elitismo deve essere compreso tra 0 e pop_size - 1.")


@dataclass
class GAProgress:
    generation: int
    best_score: float
    best_pr: float
    best_irr_es: float
    best_path: np.ndarray
    stall: int
    patience: int
    elapsed: float
    unique: int
    population: np.ndarray | None = None   # individui valutati in questa generazione (N, T)
    scores: np.ndarray | None = None       # punteggio di ciascun individuo
    evaluations: int = 0                   # valutazioni effettive (cache esclusa) fino a ora


@dataclass
class GAResult:
    path: np.ndarray
    score: float
    pr: float
    irr_es: float
    tail_wealth: float
    feasible: bool
    generations: int
    best_generation: int
    stopped_by: str
    elapsed: float
    history: dict[str, np.ndarray]
    config: GAConfig


# --------------------------------------------------------------------------------------
# Operatori
# --------------------------------------------------------------------------------------
def is_valid(paths: np.ndarray) -> np.ndarray:
    """True per le sequenze non crescenti (vincolo di Eq. 2). Opera sull'ultimo asse."""
    paths = np.asarray(paths)
    return np.all(paths[..., :-1] >= paths[..., 1:], axis=-1)


def _staircase(rng: np.random.Generator, T: int, lo: int, hi: int) -> np.ndarray:
    m = int(rng.integers(1, min(hi - lo + 1, 5, T) + 1))
    levels = np.sort(rng.choice(np.arange(lo, hi + 1), size=m, replace=False))[::-1]
    cuts = np.sort(rng.choice(np.arange(1, T), size=m - 1, replace=False)) if m > 1 else []
    sizes = np.diff(np.concatenate(([0], cuts, [T])).astype(int))
    return np.repeat(levels, sizes)


def random_population(rng: np.random.Generator, n: int, T: int, H: int) -> np.ndarray:
    """Popolazione iniziale diversificata: ogni individuo usa un proprio intervallo [lo, hi]."""
    hi = rng.integers(1, H + 1, size=n)
    lo = rng.integers(1, hi + 1)
    span = hi - lo + 1
    genes = lo[:, None] + np.floor(rng.random((n, T)) * span[:, None]).astype(np.int64)
    genes = -np.sort(-genes, axis=1)
    stairs = rng.random(n) < 0.5  # metà degli individui ha un profilo "a gradini"
    for i in np.flatnonzero(stairs):
        genes[i] = _staircase(rng, T, int(lo[i]), int(hi[i]))
    return genes


def tournament(rng: np.random.Generator, scores: np.ndarray, n: int) -> np.ndarray:
    """Torneo binario con reinserimento: restituisce gli indici dei vincitori."""
    a = rng.integers(0, scores.size, size=n)
    b = rng.integers(0, scores.size, size=n)
    return np.where(scores[a] >= scores[b], a, b)


def crossover(rng: np.random.Generator, pool: np.ndarray, p_c: float, n_out: int) -> np.ndarray:
    """Crossover a un punto; i figli non validi vengono scartati e la popolazione rifornita."""
    N, T = pool.shape
    cols = np.arange(T)[None, :]
    collected: list[np.ndarray] = []
    total = 0
    for _ in range(100):
        a = rng.integers(0, N, size=n_out)
        b = rng.integers(0, N, size=n_out)
        p1, p2 = pool[a], pool[b]
        do_x = rng.random(n_out) <= p_c
        if T > 1:
            cut = rng.integers(1, T, size=n_out)
            left = cols < cut[:, None]
            c1, c2 = np.where(left, p1, p2), np.where(left, p2, p1)
        else:
            c1, c2 = p1, p2
        kids = np.stack([np.where(do_x[:, None], c1, p1), np.where(do_x[:, None], c2, p2)], axis=1)
        keep = np.stack([~do_x | is_valid(c1), ~do_x | is_valid(c2)], axis=1)
        flat = kids[keep]
        collected.append(flat)
        total += flat.shape[0]
        if total >= n_out:
            return np.concatenate(collected)[:n_out]
    return np.concatenate(collected + [pool[rng.integers(0, N, size=n_out)]])[:n_out]


def apply_gene_mutation(
    paths: np.ndarray, pos: np.ndarray, new_val: np.ndarray
) -> np.ndarray:
    """Imposta ``paths[i, pos[i]] = new_val[i]`` e ripristina il vincolo a modifiche minime.

    Se il nuovo valore supera i geni precedenti questi vengono alzati al nuovo valore; se è
    inferiore ai successivi, questi vengono abbassati.  Esempio del paper (pag. 40):
    ``8 8 7 7 7 3 2 1`` con quinto gene +1 diventa ``8 8 8 8 8 3 2 1``.
    """
    out = np.atleast_2d(paths).copy()
    cols = np.arange(out.shape[1])[None, :]
    pos = np.asarray(pos)[:, None]
    val = np.asarray(new_val)[:, None]
    out = np.where(cols < pos, np.maximum(out, val), out)
    out = np.where(cols > pos, np.minimum(out, val), out)
    out[np.arange(out.shape[0]), pos[:, 0]] = val[:, 0]
    return out


def mutate(
    rng: np.random.Generator, pop: np.ndarray, p_m: float, v: int, H: int
) -> np.ndarray:
    """Mutazione: con probabilità ``p_m`` un gene a caso varia di ±1..±v (mai 0)."""
    out = pop.copy()
    rows = np.flatnonzero(rng.random(pop.shape[0]) <= p_m)
    if rows.size == 0:
        return out
    T = pop.shape[1]
    pos = rng.integers(0, T, size=rows.size)
    step = rng.integers(1, v + 1, size=rows.size) * rng.choice(np.array([-1, 1]), size=rows.size)
    sub = out[rows]
    new_val = np.clip(sub[np.arange(rows.size), pos] + step, 1, H)
    out[rows] = apply_gene_mutation(sub, pos, new_val)
    return out


# --------------------------------------------------------------------------------------
# Ciclo evolutivo
# --------------------------------------------------------------------------------------
def run_ga(
    problem: GoalProblem,
    config: GAConfig | None = None,
    callback: Callable[[GAProgress], None] | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> GAResult:
    """Esegue l'algoritmo genetico e restituisce la miglior strategia trovata."""
    config = config or GAConfig()
    config.validate()
    rng = np.random.default_rng(config.seed)
    T, H, N = problem.T, problem.H, config.pop_size
    start = time.perf_counter()

    cache: dict[bytes, tuple[float, float, float, float, bool]] = {}

    def evaluate(pop: np.ndarray) -> np.ndarray:
        """Restituisce una matrice (N, 5) [score, pr, irr_es, tail, feasible] usando la cache."""
        keys = [row.astype(np.int8).tobytes() for row in pop]
        todo: dict[bytes, int] = {}
        for i, k in enumerate(keys):
            if k not in cache and k not in todo:
                todo[k] = i
        if todo:
            ev = problem.evaluate(pop[list(todo.values())])
            for j, k in enumerate(todo):
                cache[k] = (ev.score[j], ev.pr[j], ev.irr_es[j], ev.tail_wealth[j], bool(ev.feasible[j]))
        return np.array([cache[k] for k in keys], dtype=float)

    pop = random_population(rng, N, T, H)
    best = dict(score=-np.inf, pr=0.0, irr=0.0, tail=0.0, feas=False, path=pop[0].copy(), gen=0)
    hist = {k: [] for k in ("best_score", "best_pr", "best_irr_es", "mean_score", "unique")}
    stall, stopped_by, gen = 0, "max_generations", -1

    for gen in range(config.max_generations):
        res = evaluate(pop)
        scores = res[:, 0]
        i = int(np.argmax(scores))
        if scores[i] > best["score"] + 1e-12:
            best.update(score=scores[i], pr=res[i, 1], irr=res[i, 2], tail=res[i, 3],
                        feas=bool(res[i, 4]), path=pop[i].copy(), gen=gen)
            stall = 0
        else:
            stall += 1
        unique = len({row.tobytes() for row in pop})
        hist["best_score"].append(best["score"])
        hist["best_pr"].append(best["pr"])
        hist["best_irr_es"].append(best["irr"])
        hist["mean_score"].append(float(scores.mean()))
        hist["unique"].append(unique)

        if callback is not None:
            callback(GAProgress(gen, best["score"], best["pr"], best["irr"], best["path"], stall,
                                config.patience, time.perf_counter() - start, unique,
                                population=pop, scores=scores, evaluations=len(cache)))
        if stall >= config.patience:
            stopped_by = "patience"
            break
        if should_stop is not None and should_stop():
            stopped_by = "user"
            break

        elite = pop[np.argsort(-scores)[: config.elitism]] if config.elitism else pop[:0]
        winners = tournament(rng, scores, N)
        offspring = crossover(rng, pop[winners], config.p_c, N - config.elitism)
        offspring = mutate(rng, offspring, config.p_m, config.mut_v, H)
        pop = np.concatenate([elite, offspring]) if config.elitism else offspring

    return GAResult(
        path=best["path"].astype(int), score=float(best["score"]), pr=float(best["pr"]),
        irr_es=float(best["irr"]), tail_wealth=float(best["tail"]), feasible=bool(best["feas"]),
        generations=gen + 1, best_generation=int(best["gen"]), stopped_by=stopped_by,
        elapsed=time.perf_counter() - start,
        history={k: np.asarray(v, dtype=float) for k, v in hist.items()}, config=config,
    )
