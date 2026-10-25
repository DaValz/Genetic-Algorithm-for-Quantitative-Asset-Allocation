"""Registrazione dell'evoluzione dell'algoritmo genetico.

``EvolutionTrace`` si collega a ``run_ga`` come callback, conserva popolazione e miglior individuo di
ogni generazione e ne produce una versione compatta (``payload``) con cui l'interfaccia può mostrare,
fotogramma per fotogramma, come le strategie evolvono davvero.  Non dipende da Streamlit.
"""
from __future__ import annotations

import base64
import math
from dataclasses import dataclass, field

import numpy as np

from .genetic import GAProgress


def _b64(array: np.ndarray) -> str:
    return base64.b64encode(np.ascontiguousarray(array, dtype=np.uint8).tobytes()).decode("ascii")


def _finite(x: float) -> float | None:
    x = float(x)
    return x if math.isfinite(x) else None


def select_frames(best_scores: np.ndarray, max_frames: int = 110) -> np.ndarray:
    """Generazioni da mostrare: fitte all'inizio (dove l'evoluzione cambia di più).

    Sono sempre incluse la prima, l'ultima e quelle in cui la miglior soluzione migliora.
    """
    scores = np.asarray(best_scores, dtype=float)
    n = scores.size
    if n <= max_frames:
        return np.arange(n)
    dense = np.unique(np.round(np.geomspace(1, n, max(2, int(max_frames * 0.7)))).astype(int) - 1)
    improved = np.flatnonzero(np.diff(scores, prepend=-np.inf) > 1e-12)
    must = np.array([0, n - 1])
    idx = np.unique(np.concatenate([must, dense, improved]))
    if idx.size > max_frames:
        keep = np.unique(np.round(np.linspace(0, idx.size - 1, max_frames)).astype(int))
        idx = np.unique(np.concatenate([must, idx[keep]]))
    return idx


def sample_individuals(n_total: int, n_sample: int, top: int = 8) -> np.ndarray:
    """Posizioni in graduatoria (0 = migliore) degli individui da disegnare.

    I migliori sono sempre presenti, gli altri sono distribuiti uniformemente fino al peggiore.
    """
    if n_total <= n_sample:
        return np.arange(n_total)
    top = min(top, n_sample)
    rest = np.round(np.linspace(top, n_total - 1, n_sample - top)).astype(int)
    return np.unique(np.concatenate([np.arange(top), rest]))


@dataclass
class EvolutionTrace:
    """Callback per ``run_ga`` che memorizza l'intera evoluzione."""

    n_scenarios: int = 0
    n_portfolios: int = 0
    _gens: list[int] = field(default_factory=list)
    _pop: list[np.ndarray] = field(default_factory=list)      # (N, T) ordinata dal migliore al peggiore
    _champ: list[np.ndarray] = field(default_factory=list)    # miglior individuo trovato fino a quel momento
    _pr: list[float] = field(default_factory=list)
    _irr: list[float] = field(default_factory=list)
    _score: list[float] = field(default_factory=list)
    _evals: list[int] = field(default_factory=list)

    def __call__(self, progress: GAProgress) -> None:
        self.record(progress)

    def record(self, p: GAProgress) -> None:
        if p.population is None or p.scores is None:
            return
        order = np.argsort(-np.asarray(p.scores, dtype=float), kind="stable")
        self._gens.append(int(p.generation))
        self._pop.append(np.asarray(p.population)[order].astype(np.uint8))
        self._champ.append(np.asarray(p.best_path).astype(np.uint8).copy())
        self._pr.append(float(p.best_pr))
        self._irr.append(float(p.best_irr_es))
        self._score.append(float(p.best_score))
        self._evals.append(int(p.evaluations))

    @property
    def n_generations(self) -> int:
        return len(self._gens)

    @property
    def total_evaluations(self) -> int:
        return self._evals[-1] if self._evals else 0

    def payload(self, *, max_frames: int = 100, max_individuals: int = 80, elapsed: float = 0.0,
                stopped_by: str = "", best_generation: int | None = None) -> dict:
        """Versione compatta e serializzabile in JSON (popolazioni come byte in base64)."""
        if not self._pop:
            raise ValueError("Nessuna generazione registrata.")
        idx = select_frames(np.asarray(self._score), max_frames)
        n_pop, horizon = self._pop[0].shape
        pos = sample_individuals(n_pop, max_individuals)
        pop = np.stack([self._pop[i][pos] for i in idx])
        champ = np.stack([self._champ[i] for i in idx])
        levels = int(max(self.n_portfolios, pop.max(), champ.max()))
        return {
            "T": int(horizon), "K": levels, "F": int(idx.size), "N": int(pos.size),
            "gens": [self._gens[i] + 1 for i in idx],
            "pr": [_finite(self._pr[i]) for i in idx],
            "irr": [_finite(self._irr[i]) for i in idx],
            "score": [_finite(self._score[i]) for i in idx],
            "evals": [self._evals[i] for i in idx],
            "generations": self.n_generations,
            "best_generation": None if best_generation is None else int(best_generation) + 1,
            "pop_size": int(n_pop), "n_scenarios": int(self.n_scenarios),
            "evaluations": self.total_evaluations,
            "elapsed": float(elapsed), "stopped_by": stopped_by,
            "pop": _b64(pop), "champ": _b64(champ),
        }
