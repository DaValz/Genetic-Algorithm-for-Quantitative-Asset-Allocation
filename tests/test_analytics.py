"""Test della post-elaborazione (report, benchmark, validazione, robustezza)."""
import numpy as np
import pandas as pd
import pytest

from goalga import GAConfig, GoalProblem, build_flows, run_ga
from goalga.analytics import (
    benchmark_table, build_report, linear_glide_path, run_robustness, wilson_interval,
)


@pytest.fixture()
def solved(market):
    flows = build_flows(60_000, 20, 4_000, goals={10: 40_000, 20: 300_000})
    scenarios = market.draw_scenarios(20, 1000, np.random.default_rng(0))
    problem = GoalProblem(flows, scenarios, 0.90, 0.05)
    result = run_ga(problem, GAConfig(pop_size=60, patience=40, seed=5))
    return market, flows, problem, result


def test_report_structure_and_consistency(solved):
    market, flows, problem, result = solved
    rep = build_report(market, flows, problem, result, oos_scenarios=4000)
    T = flows.horizon
    assert rep.fan.shape == (T + 1, 6) and rep.fan.index[0] == 0
    assert (np.diff(rep.fan[["P5", "P25", "P50", "P75", "P95"]].to_numpy(), axis=1) >= -1e-9).all()
    assert rep.fan.loc[0, "P50"] == flows.w0
    assert list(rep.goals["Anno"]) == [10, 20]
    assert rep.goals["Probabilità cumulata di successo"].is_monotonic_decreasing
    assert rep.goals["Probabilità cumulata di successo"].iloc[-1] == pytest.approx(result.pr)
    assert rep.composition.shape == (T, market.n_assets)
    assert np.allclose(rep.composition.sum(axis=1), 1.0)
    assert rep.oos is not None and rep.oos.pr_low <= rep.oos.pr <= rep.oos.pr_high
    assert rep.switches == np.count_nonzero(np.diff(result.path))


def test_benchmarks_include_ga_and_constant_mixes(solved):
    _, _, problem, result = solved
    table = benchmark_table(problem, result.path)
    assert table.Strategia.iloc[0].startswith("Glide path") and len(table) == 2 + problem.H
    constants = table[table.Strategia.str.startswith("Mix costante")]
    assert table.Score.iloc[0] >= constants.Score.max() - 1e-12  # il GA non può essere peggiore di un mix costante


def test_the_compound_return_is_what_a_long_run_investor_earns_not_the_arithmetic_mean(market):
    ret, vol = market.stats
    comp = market.compound_returns
    assert (comp < ret).all() and np.allclose(ret - comp, vol**2 / 2 / (1 + ret), atol=5e-4), \
        "la volatilità costa circa metà della varianza"
    assert np.all(np.diff(comp[np.argsort(vol)]) > -0.02), "e il rendimento composto resta ordinato come quello atteso"
    # controllo di Monte Carlo: rendimenti lognormali con media e varianza dei portafogli, media dei logaritmi
    rng = np.random.default_rng(11)
    for k in (0, len(ret) // 2, len(ret) - 1):
        s2 = np.log(1 + vol[k] ** 2 / (1 + ret[k]) ** 2)
        draws = rng.lognormal(np.log(1 + ret[k]) - s2 / 2, np.sqrt(s2), 2_000_000)
        assert draws.mean() == pytest.approx(1 + ret[k], abs=3e-3) and draws.var() == pytest.approx(vol[k] ** 2, rel=0.05)
        assert np.expm1(np.log(draws).mean()) == pytest.approx(comp[k], abs=4e-4)


def test_the_report_gives_the_compound_return_of_the_chosen_path(solved):
    market, flows, problem, result = solved
    rep = build_report(market, flows, problem, result, oos_scenarios=0)
    levels = result.path - 1
    assert rep.expected_path_growth == pytest.approx(np.expm1(np.mean(np.log1p(market.compound_returns[levels]))))
    assert rep.expected_path_growth < rep.expected_path_return
    constant = build_report(market, flows, problem, type(result)(**{**result.__dict__, "path": np.full_like(result.path, 4)}),
                            oos_scenarios=0)
    assert constant.expected_path_growth == pytest.approx(market.compound_returns[3])


def test_the_comparison_with_simple_strategies_is_repeated_on_the_new_scenarios(solved):
    market, flows, problem, result = solved
    rep = build_report(market, flows, problem, result, oos_scenarios=3000)
    assert rep.oos.benchmarks is not None and rep.benchmarks_validated is rep.oos.benchmarks
    assert list(rep.oos.benchmarks["Chiave"]) == list(rep.benchmarks["Chiave"])
    ga = rep.oos.benchmarks.iloc[0]
    assert ga["Probabilità di successo"] == pytest.approx(rep.oos.pr) and bool(ga["Soglia rispettata"]) == rep.oos.feasible
    assert ga["IRR atteso (coda)"] == pytest.approx(rep.oos.irr_es)
    assert not np.allclose(rep.oos.benchmarks["Probabilità di successo"], rep.benchmarks["Probabilità di successo"]), \
        "scenari diversi: i numeri non sono quelli della ricerca"
    without = build_report(market, flows, problem, result, oos_scenarios=0)
    assert without.oos is None and without.benchmarks_validated is without.benchmarks


def test_a_report_for_a_plan_that_restarts_mid_year_uses_the_partial_first_year(market):
    flows = build_flows(60_000, 20, 4_000, goals={10: 40_000, 20: 300_000}, first_period=0.4)
    scenarios = market.draw_scenarios(20, 600, np.random.default_rng(0))
    problem = GoalProblem(flows, scenarios, 0.90, 0.05)
    result = run_ga(problem, GAConfig(pop_size=40, patience=20, seed=5))
    rep = build_report(market, flows, problem, result, oos_scenarios=1000)
    ret, _ = market.stats
    first = 60_000 * (1 + ret[result.path[0] - 1]) ** 0.4 + flows.net[0]
    assert rep.fan.loc[1, "Atteso"] == pytest.approx(first), "il primo anno vale il 40% di un anno"
    assert rep.fan.loc[0, "P50"] == flows.w0 and rep.oos is not None
    whole = build_flows(60_000, 20, 4_000, goals={10: 40_000, 20: 300_000})
    assert rep.required_return > build_report(market, whole, GoalProblem(whole, scenarios, 0.9, 0.05), result,
                                              oos_scenarios=0).required_return, "meno tempo: serve più rendimento"


def test_linear_glide_path_is_valid():
    path = linear_glide_path(30, 9)
    assert path[0] == 9 and path[-1] == 1 and np.all(np.diff(path) <= 0)


def test_wilson_interval_properties():
    low, high = wilson_interval(950, 1000)
    assert low < 0.95 < high and 0.93 < low and high < 0.97
    assert wilson_interval(0, 100)[0] == 0.0 and wilson_interval(100, 100)[1] == pytest.approx(1.0)
    wide, narrow = wilson_interval(95, 100), wilson_interval(9500, 10000)
    assert wide[1] - wide[0] > narrow[1] - narrow[0]


def test_robustness_runs(solved):
    market, flows, _, _ = solved
    rob = run_robustness(market, flows, pr_target=0.90, alpha=0.05,
                         ga_config=GAConfig(pop_size=40, patience=20, seed=1), n_runs=4, n_scenarios=500)
    assert rob.paths.shape == (4, flows.horizon)
    assert np.all(rob.lower <= rob.median) and np.all(rob.median <= rob.upper)
    assert 0.0 <= rob.modal_share <= 1.0
    assert isinstance(pd.DataFrame(rob.paths), pd.DataFrame)
