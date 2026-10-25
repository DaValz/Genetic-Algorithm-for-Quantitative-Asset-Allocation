"""Compatibilità con la vecchia API ``ga_model.GoalBasedGA``.

.. deprecated:: 2.0
    Usa il pacchetto :mod:`goalga`. Questo modulo espone la stessa interfaccia della versione
    precedente ma delega al nuovo motore (vettorizzato e fedele al paper): i risultati numerici
    differiscono perché la vecchia implementazione aveva difetti di operatori e di valutazione
    (vedi ``docs/AUDIT.md``).
"""
from __future__ import annotations

import warnings

import numpy as np

from goalga import GAConfig, GoalProblem, build_flows, run_ga


class GoalBasedGA:
    def __init__(self, historical_returns, initial_wealth, running_investment, goals,
                 time_horizon=50, num_portfolios=9, min_success_prob=0.95, alpha_es=0.02,
                 pop_size=100, max_generations=200, p_c=0.55, p_m=0.30, mut_v=2, seed=None):
        warnings.warn("ga_model.GoalBasedGA è deprecato: usa il pacchetto goalga.", DeprecationWarning, stacklevel=2)
        history = np.asarray(historical_returns, dtype=float)
        if history.ndim != 2 or history.shape[1] != num_portfolios:
            raise ValueError(f"historical_returns deve avere {num_portfolios} colonne (un portafoglio per colonna).")
        rng = np.random.default_rng(seed)
        scenarios = history[rng.integers(0, history.shape[0], size=(1000, time_horizon))]
        # la vecchia versione prevedeva un versamento anche a fine ultimo anno
        flows = build_flows(initial_wealth, time_horizon, running_investment, time_horizon, goals=dict(goals))
        self.problem = GoalProblem(flows, scenarios, min_success_prob, alpha_es)
        self.config = GAConfig(pop_size=pop_size, p_c=p_c, p_m=p_m, mut_v=mut_v, patience=max_generations,
                               max_generations=max_generations, seed=seed)

    def run(self, progress_callback=None):
        """Restituisce ``(glide_path, (probabilità di successo, IRR atteso in coda))``."""
        def adapter(progress):
            if progress_callback is not None:
                progress_callback(progress.generation, self.config.max_generations, progress.best_score,
                                  progress.best_path, (progress.best_pr, progress.best_irr_es))

        result = run_ga(self.problem, self.config, callback=adapter)
        return result.path, (result.pr, result.irr_es)
