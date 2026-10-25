"""Casi limite: il modello deve restare finito e coerente con parametri estremi."""
import numpy as np
import pytest

from goalga import GAConfig, GoalProblem, build_flows, run_ga
from goalga.genetic import is_valid


def make_problem(market, flows, S=400, pr=0.9, alpha=0.05, seed=0):
    scen = market.draw_scenarios(flows.horizon, S, np.random.default_rng(seed))
    return GoalProblem(flows, scen, pr, alpha)


def fast(seed=1):
    return GAConfig(pop_size=30, patience=15, max_generations=60, seed=seed)


def assert_sane(result, problem):
    assert is_valid(result.path) and len(result.path) == problem.T
    assert result.path.min() >= 1 and result.path.max() <= problem.H
    assert np.isfinite([result.score, result.pr, result.irr_es, result.tail_wealth]).all()
    assert 0.0 <= result.pr <= 1.0 and result.irr_es >= -1.0


@pytest.mark.parametrize("horizon", [2, 3, 60])
def test_extreme_horizons(market, horizon):
    flows = build_flows(50_000, horizon, 2_000, goals={horizon: 60_000})
    problem = make_problem(market, flows)
    assert_sane(run_ga(problem, fast()), problem)


def test_alpha_and_threshold_extremes(market):
    flows = build_flows(50_000, 10, 2_000, goals={10: 70_000})
    for pr, alpha in ((1.0, 0.05), (0.5, 0.5), (0.9, 1.0)):
        problem = make_problem(market, flows, pr=pr, alpha=alpha)
        assert_sane(run_ga(problem, fast()), problem)


def test_very_few_scenarios_keep_at_least_one_tail_scenario(market):
    flows = build_flows(50_000, 10, 2_000, goals={10: 70_000})
    problem = make_problem(market, flows, S=50, alpha=0.02)
    assert problem.n_worst == 1
    assert_sane(run_ga(problem, fast()), problem)


def test_no_initial_capital_and_only_contributions(market):
    flows = build_flows(0, 15, 5_000, goals={15: 60_000})
    problem = make_problem(market, flows)
    assert_sane(run_ga(problem, fast()), problem)


def test_goal_in_the_first_year_and_hopeless_plan_stay_finite(market):
    flows = build_flows(1_000, 12, 100, goals={1: 500_000, 12: 900_000})
    problem = make_problem(market, flows)
    ev = problem.evaluate(np.full((3, 12), [[1], [5], [9]]))
    assert np.isfinite(ev.irr_es).all() and np.isfinite(ev.score).all()
    assert (ev.pr == 0).all() and (ev.irr_es >= -1.0).all()
    assert_sane(run_ga(problem, fast()), problem)


def test_early_large_goal_flags_unreliable_irr(market):
    flows = build_flows(10_000, 20, 0, goals={2: 200_000, 20: 1_000})
    problem = make_problem(market, flows)
    ev = problem.evaluate(np.full(20, 5))
    assert np.isfinite(ev.irr_es).all()
    assert isinstance(problem.irr_reliable, bool)


def test_constant_portfolios_have_no_switches_in_report(market):
    from goalga.analytics import build_report

    flows = build_flows(50_000, 10, 2_000, goals={10: 70_000})
    problem = make_problem(market, flows)
    result = run_ga(problem, fast())
    report = build_report(market, flows, problem, result, oos_scenarios=0)
    assert report.oos is None and report.fan.shape == (11, 6)
    assert report.switches == int(np.count_nonzero(np.diff(result.path)))
