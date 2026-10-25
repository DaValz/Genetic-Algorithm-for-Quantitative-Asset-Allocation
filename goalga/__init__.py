"""goalga - allocazione dinamica goal-based con algoritmi genetici.

Implementazione del modello di Pomante, Farina e Cucurachi, "A 'Plug-and-Play,' Goal-Based,
Dynamic Asset Allocation Model with Genetic Algorithms", The Journal of Wealth Management, 2024.
"""
from .genetic import GAConfig, GAProgress, GAResult, run_ga
from .market import Market, build_market
from .problem import Evaluation, Flows, GoalProblem, build_flows, required_return

__all__ = [
    "Evaluation", "Flows", "GAConfig", "GAProgress", "GAResult", "GoalProblem", "Market",
    "build_flows", "build_market", "required_return", "run_ga",
]
__version__ = "2.0.0"
