"""Test del modello: flussi, successo, IRR, rendimento richiesto."""
import numpy as np
import numpy_financial as npf
import pytest

from goalga import GoalProblem, build_flows, required_return
from goalga.problem import terminal_value_curve

from conftest import PAPER_GOALS


# ------------------------------------------------------------------ flussi
def test_goals_in_same_year_are_summed():
    flows = build_flows(10_000, 10, 0, goals=[(5, 30_000), (5, 20_000), (8, 1_000)])
    assert flows.goals[4] == 50_000  # il vecchio dizionario sovrascriveva: 20.000
    assert flows.goals[7] == 1_000


def test_goal_outside_horizon_is_rejected():
    with pytest.raises(ValueError):
        build_flows(10_000, 10, 0, goals={11: 1_000})


def test_contribution_schedule_and_indexation():
    flows = build_flows(0, 5, 100, last_contribution_year=3, contribution_growth=0.10,
                        goals={5: 1_000}, goal_inflation=0.02)
    assert np.allclose(flows.contributions, [100, 110, 121, 0, 0])
    assert flows.goals[4] == pytest.approx(1_000 * 1.02**5)


def test_default_last_contribution_is_horizon_minus_one():
    flows = build_flows(0, 6, 100, goals={6: 1})
    assert flows.contributions[-1] == 0 and flows.contributions[-2] == 100


# -------------------------------------------------- rendimento richiesto (paper)
def test_required_return_matches_paper_case_study():
    """Il paper riporta un rendimento minimo di 4,43% per il caso con tre obiettivi."""
    flows = build_flows(160_000, 50, 10_000, last_contribution_year=49, goals=PAPER_GOALS)
    assert required_return(flows) == pytest.approx(0.0443, abs=5e-5)


def test_required_return_none_without_goals():
    assert required_return(build_flows(1_000, 10, 100)) is None


def test_required_return_is_exact_zero_wealth_point():
    flows = build_flows(50_000, 20, 5_000, goals={20: 400_000})
    r = required_return(flows)
    w = flows.w0
    for t in range(20):
        w = w * (1 + r) + flows.net[t]
    assert w == pytest.approx(0.0, abs=1.0)


# ------------------------------------------------------------------ IRR
def test_irr_inverse_roundtrip(small_problem):
    rates = np.array([-0.2, 0.0, 0.035, 0.0443, 0.10, 0.25])
    wealth = terminal_value_curve(small_problem.flows, rates)
    assert np.allclose(small_problem.irr_from_terminal(wealth), rates, atol=1e-6)


def _reference_metrics(problem, path):
    """Implementazione lenta, a cicli, equivalente al vecchio codice (con IRR di numpy_financial)."""
    flows = problem.flows
    gf = np.transpose(problem._gf, (2, 0, 1))  # (S, T, H)
    terminal, success, cashflows = [], 0, []
    for s in range(problem.S):
        w, ok = flows.w0, True
        cf = [-flows.w0]
        for t in range(problem.T):
            w = w * gf[s, t, path[t] - 1] + flows.contributions[t]
            c = -flows.contributions[t]
            if flows.goals[t] > 0:
                w -= flows.goals[t]
                c += flows.goals[t]
                ok &= w >= 0
            cf.append(c)
        success += ok
        terminal.append(w)
        cf[-1] += w
        cashflows.append(cf)
    terminal = np.array(terminal)
    worst = np.argsort(terminal)[: problem.n_worst]
    irr = np.mean([npf.irr(cashflows[i]) for i in worst])
    return success / problem.S, irr, terminal[worst].mean()


@pytest.mark.parametrize("level", [1, 2, 3, 4])
def test_vectorised_evaluation_matches_reference(small_problem, level):
    path = np.full(small_problem.T, level)
    ev = small_problem.evaluate(path)
    pr, irr, tail = _reference_metrics(small_problem, path)
    assert ev.pr[0] == pytest.approx(pr)
    assert ev.tail_wealth[0] == pytest.approx(tail, rel=1e-9)
    assert ev.irr_es[0] == pytest.approx(irr, abs=1e-6)


def test_vectorised_evaluation_matches_reference_on_dynamic_path(small_problem):
    path = np.array([4, 4, 4, 3, 3, 3, 2, 2, 1, 1])
    ev = small_problem.evaluate(path)
    pr, irr, tail = _reference_metrics(small_problem, path)
    assert (ev.pr[0], ev.tail_wealth[0]) == (pytest.approx(pr), pytest.approx(tail, rel=1e-9))
    assert ev.irr_es[0] == pytest.approx(irr, abs=1e-6)


def test_score_follows_equation_1(small_problem):
    paths = np.vstack([np.full(10, k) for k in (1, 2, 3, 4)])
    ev = small_problem.evaluate(paths)
    for i in range(4):
        expected = 2.0 + ev.irr_es[i] if ev.pr[i] >= small_problem.pr_target else ev.pr[i]
        assert ev.score[i] == pytest.approx(expected)
        assert ev.feasible[i] == (ev.pr[i] >= small_problem.pr_target - 1e-12)


def test_wealth_paths_are_consistent_with_evaluation(small_problem):
    path = np.array([4, 4, 3, 3, 3, 2, 2, 2, 1, 1])
    wp = small_problem.wealth_paths(path)
    ev = small_problem.evaluate(path)
    assert np.allclose(wp.post[:, -1], small_problem.terminal_wealth(path))
    assert wp.joint_ok[:, -1].mean() == pytest.approx(ev.pr[0])
    assert np.all(np.diff(wp.joint_ok.sum(axis=0)) <= 0)  # la probabilità cumulata non può crescere


def test_success_definition_on_deterministic_scenario():
    flows = build_flows(1_000, 3, 0, last_contribution_year=0, goals={2: 1_100, 3: 500})
    scen = np.zeros((10, 3, 2))
    scen[:, :, 1] = 0.10  # portafoglio 2 rende +10% l'anno
    problem = GoalProblem(flows, scen, pr_target=0.95, alpha=0.1)
    # P1: 1000 -> goal 1100 al 2° anno non coperto
    assert problem.evaluate(np.array([1, 1, 1])).pr[0] == 0.0
    # P2: 1000*1.1^2 = 1210 >= 1100 -> 110 -> *1.1 = 121 -> goal 500 non coperto
    assert problem.evaluate(np.array([2, 2, 2])).pr[0] == 0.0
    flows_ok = build_flows(1_000, 3, 0, last_contribution_year=0, goals={2: 1_100, 3: 100})
    ok = GoalProblem(flows_ok, scen, pr_target=0.95, alpha=0.1)
    assert ok.evaluate(np.array([2, 2, 2])).pr[0] == 1.0


def test_invalid_paths_are_rejected(small_problem):
    with pytest.raises(ValueError):
        small_problem.evaluate(np.full(10, 9))
    with pytest.raises(ValueError):
        small_problem.evaluate(np.full(7, 1))


# ------------------------------------------------------------------ primo anno parziale (piani che ripartono a metà anno)
def _constant_account(flows, r):
    """Patrimonio dopo ogni flusso di un conto che rende sempre ``r`` (primo anno accorciato se ``first_period < 1``)."""
    w, out = flows.w0, []
    for t in range(flows.horizon):
        w = w * (1 + r) ** (flows.first_period if t == 0 else 1.0) + flows.net[t]
        out.append(w)
    return np.array(out)


def test_a_partial_first_year_is_rejected_outside_zero_one():
    for bad in (0.0, -0.2, 1.01):
        with pytest.raises(ValueError):
            build_flows(1_000, 5, 100, goals={5: 500}, first_period=bad)
    assert build_flows(1_000, 5, 100, goals={5: 500}).first_period == 1.0


def test_a_partial_first_year_scales_only_the_first_growth_factor():
    flows = build_flows(1_000, 4, 100, goals={4: 1_500}, first_period=0.4)
    rng = np.random.default_rng(3)
    scen = rng.normal(0.04, 0.10, size=(50, 4, 3))
    problem = GoalProblem(flows, scen, pr_target=0.9, alpha=0.1)
    wp = problem.wealth_paths(np.array([2, 3, 1, 3]))
    expected = np.full(50, 1_000.0)
    for t, level in enumerate((1, 2, 0, 2)):
        step = (1 + scen[:, t, level]) ** (0.4 if t == 0 else 1.0)
        expected = expected * step + flows.net[t]
        assert np.allclose(wp.post[:, t + 1], expected)


def test_full_first_year_is_untouched_by_the_option():
    flows = build_flows(1_000, 4, 100, goals={4: 1_500})
    same = build_flows(1_000, 4, 100, goals={4: 1_500}, first_period=1.0)
    scen = np.random.default_rng(1).normal(0.03, 0.1, size=(20, 4, 2))
    a, b = GoalProblem(flows, scen), GoalProblem(same, scen)
    path = np.array([1, 2, 2, 1])
    assert np.array_equal(a.terminal_wealth(path), b.terminal_wealth(path))
    rates = np.array([-0.1, 0.0, 0.05])
    assert np.allclose(terminal_value_curve(flows, rates), flows.w0 * (1 + rates) ** 4 + sum(
        flows.net[t] * (1 + rates) ** (3 - t) for t in range(4)))


@pytest.mark.parametrize("first", [1.0, 0.75, 0.3])
def test_terminal_value_curve_and_irr_follow_the_partial_first_year(first):
    flows = build_flows(20_000, 6, 3_000, goals={3: 15_000, 6: 40_000}, first_period=first)
    rates = np.array([-0.05, 0.0, 0.03, 0.08])
    curve = terminal_value_curve(flows, rates)
    assert np.allclose(curve, [_constant_account(flows, r)[-1] for r in rates])
    problem = GoalProblem(flows, np.zeros((10, 6, 2)), pr_target=0.9, alpha=0.1)
    assert np.allclose(problem.irr_from_terminal(curve), rates, atol=1e-6)


@pytest.mark.parametrize("first", [1.0, 0.5, 0.1])
def test_required_return_is_the_exact_zero_wealth_point_with_a_partial_first_year(first):
    flows = build_flows(30_000, 8, 4_000, goals={4: 25_000, 8: 120_000}, first_period=first)
    r = required_return(flows)
    after = _constant_account(flows, r)
    assert after[[3, 7]].min() == pytest.approx(0.0, abs=1.0)
    assert (_constant_account(flows, r + 0.01)[[3, 7]] > 0).all()
    shorter = required_return(build_flows(30_000, 8, 4_000, goals={4: 25_000, 8: 120_000}))
    assert (first == 1.0) or r > shorter, "meno tempo per crescere nel primo anno: serve un rendimento più alto"
