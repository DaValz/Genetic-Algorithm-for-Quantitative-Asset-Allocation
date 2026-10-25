"""Test di covarianza (Ledoit-Wolf) e frontiera efficiente."""
import numpy as np
import pytest

from goalga.portfolios import (
    _caps_array,
    _max_return_weights,
    _mix_at_vol,
    _project,
    _vol,
    efficient_portfolios,
    ledoit_wolf_constant_correlation,
    portfolio_stats,
    prune_positions,
)


def _true_cov(n, rng):
    sd = rng.uniform(0.01, 0.06, n)
    corr = np.full((n, n), 0.35) + 0.65 * np.eye(n)
    return corr * np.outer(sd, sd)


def test_shrinkage_in_unit_interval_and_psd():
    rng = np.random.default_rng(0)
    x = rng.multivariate_normal(np.zeros(8), _true_cov(8, rng), size=60)
    cov, delta = ledoit_wolf_constant_correlation(x)
    assert 0.0 <= delta <= 1.0
    assert np.linalg.eigvalsh(cov).min() > 0
    assert np.allclose(cov, cov.T)
    assert np.allclose(np.diag(cov), x.var(axis=0), rtol=1e-9)  # le varianze restano quelle campionarie


def test_shrinkage_reduces_estimation_error_when_data_are_scarce():
    rng = np.random.default_rng(1)
    n, t = 20, 36
    truth = _true_cov(n, rng)
    err_sample, err_lw = [], []
    for _ in range(40):
        x = rng.multivariate_normal(np.zeros(n), truth, size=t)
        s = np.cov(x, rowvar=False, ddof=0)
        lw, _ = ledoit_wolf_constant_correlation(x)
        err_sample.append(np.linalg.norm(s - truth))
        err_lw.append(np.linalg.norm(lw - truth))
    assert np.mean(err_lw) < 0.85 * np.mean(err_sample)


def test_shrinkage_vanishes_with_abundant_data():
    """Con molti dati e correlazioni NON costanti il target non serve: δ -> 0."""
    rng = np.random.default_rng(2)
    n = 6
    sd = np.linspace(0.01, 0.05, n)
    corr = np.eye(n)
    corr[:3, :3] = 0.9
    corr[3:, 3:] = 0.9
    corr[:3, 3:] = corr[3:, :3] = 0.05
    np.fill_diagonal(corr, 1.0)
    x = rng.multivariate_normal(np.zeros(n), corr * np.outer(sd, sd), size=20_000)
    _, delta = ledoit_wolf_constant_correlation(x)
    assert delta < 0.05


def test_shrinkage_is_full_when_target_is_exact():
    """Se la correlazione vera è costante il target è esatto e la stima ottima coincide con esso."""
    rng = np.random.default_rng(2)
    x = rng.multivariate_normal(np.zeros(4), _true_cov(4, rng), size=20_000)
    _, delta = ledoit_wolf_constant_correlation(x)
    assert delta > 0.9


# ------------------------------------------------------------------ frontiera
@pytest.fixture()
def universe():
    rng = np.random.default_rng(4)
    n = 8
    mu = np.sort(rng.uniform(0.02, 0.09, n))
    sd = np.linspace(0.01, 0.20, n)
    corr = np.full((n, n), 0.4) + 0.6 * np.eye(n)
    return mu, corr * np.outer(sd, sd)


@pytest.mark.parametrize("cap", [1.0, 0.5, 0.3])
def test_frontier_constraints_and_ordering(universe, cap):
    mu, cov = universe
    fr = efficient_portfolios(mu, cov, 9, cap)
    assert fr.weights.shape == (8, 9)
    assert np.allclose(fr.weights.sum(axis=0), 1.0, atol=1e-8)
    assert fr.weights.min() >= -1e-9 and fr.weights.max() <= cap + 1e-8
    assert np.all(np.diff(fr.vols) > 0)                   # rischio crescente da P1 a P9
    assert np.all(np.diff(fr.returns) >= -1e-9)           # e rendimento atteso non decrescente


def test_frontier_portfolios_are_efficient(universe):
    mu, cov = universe
    fr = efficient_portfolios(mu, cov, 9, 1.0)
    rng = np.random.default_rng(0)
    w = rng.dirichlet(np.ones(8) * 0.3, size=20_000)
    ret, vol = portfolio_stats(w.T, mu, cov)
    for k in range(9):
        dominating = (vol <= fr.vols[k] - 1e-6) & (ret >= fr.returns[k] + 1e-6)
        assert not dominating.any(), f"P{k + 1} è dominato da un portafoglio casuale"


def test_first_and_last_portfolios_are_extremes(universe):
    mu, cov = universe
    fr = efficient_portfolios(mu, cov, 9, 1.0)
    rng = np.random.default_rng(1)
    w = rng.dirichlet(np.ones(8), size=20_000)
    ret, vol = portfolio_stats(w.T, mu, cov)
    assert fr.vols[0] <= vol.min() + 1e-9
    assert fr.returns[-1] >= ret.max() - 1e-9
    assert fr.returns[-1] == pytest.approx(mu.max())


def test_infeasible_cap_is_raised_automatically(universe):
    mu, cov = universe
    fr = efficient_portfolios(mu, cov, 9, 0.05)  # 8 asset x 5% < 100%: tetto alzato a 2/n = 25%
    assert fr.max_weight == pytest.approx(0.25)
    assert np.allclose(fr.weights.sum(axis=0), 1.0, atol=1e-8)
    assert fr.vols[-1] - fr.vols[0] > 0.01  # i portafogli restano distinguibili


def test_two_assets_are_never_forced_to_equal_weights():
    mu = np.array([0.03, 0.08])
    cov = np.array([[0.0004, 0.0], [0.0, 0.0225]])
    fr = efficient_portfolios(mu, cov, 9, 0.4)
    assert fr.max_weight == 1.0 and not fr.degenerate
    assert fr.weights[0, 0] > 0.9 and fr.weights[1, -1] > 0.99


def test_frontier_needs_two_assets():
    with pytest.raises(ValueError):
        efficient_portfolios(np.array([0.05]), np.array([[0.04]]))


def test_degenerate_universe_is_flagged():
    mu = np.full(3, 0.05)
    cov = np.eye(3) * 0.04
    assert efficient_portfolios(mu, cov, 9, 1.0).vols[-1] - 0 >= 0  # non solleva eccezioni
    identical = efficient_portfolios(np.array([0.05, 0.05]), np.array([[0.04, 0.04], [0.04, 0.04]]), 9, 1.0)
    assert identical.degenerate


# ------------------------------------------------------------------ tetti per asset, regole lineari, tetto di volatilità
def test_each_asset_can_have_its_own_cap(universe):
    mu, cov = universe
    caps = np.array([0.25, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.3])
    fr = efficient_portfolios(mu, cov, 9, caps)
    assert np.all(fr.weights <= caps[:, None] + 1e-8) and np.allclose(fr.weights.sum(axis=0), 1.0, atol=1e-8)
    assert fr.caps is not None and np.allclose(fr.caps, caps) and fr.max_weight == pytest.approx(0.5)
    assert efficient_portfolios(mu, cov, 9, 0.5).caps is None, "con un tetto unico non serve il vettore"


def test_linear_rules_hold_for_every_portfolio(universe):
    mu, cov = universe
    rules = np.zeros((1, 8))
    rules[0, 7], rules[0, 0] = 1.0, -0.5                  # w7 >= 0.5 * w0
    free = efficient_portfolios(mu, cov, 9, 1.0)
    ruled = efficient_portfolios(mu, cov, 9, 1.0, rules=rules)
    assert (rules @ free.weights < -1e-3).any(), "senza la regola il portafoglio prudente la violerebbe"
    assert (rules @ ruled.weights >= -1e-7).all() and np.allclose(ruled.weights.sum(axis=0), 1.0, atol=1e-8)
    assert np.all(np.diff(ruled.vols) > 0) and ruled.vols[0] > free.vols[0], "la regola ha un costo in termini di rischio"


def test_rules_are_ignored_when_empty(universe):
    mu, cov = universe
    free = efficient_portfolios(mu, cov, 9, 0.5)
    for empty in (None, np.zeros((0, 8))):
        assert np.allclose(efficient_portfolios(mu, cov, 9, 0.5, rules=empty).weights, free.weights, atol=1e-9)


def test_volatility_ceiling_limits_the_most_aggressive_portfolio(universe):
    mu, cov = universe
    free = efficient_portfolios(mu, cov, 9, 1.0)
    ceiling = 0.5 * (free.vols[0] + free.vols[-1])
    capped = efficient_portfolios(mu, cov, 9, 1.0, vol_ceiling=ceiling)
    assert capped.vol_ceiling == pytest.approx(ceiling) and capped.vols[-1] == pytest.approx(ceiling, rel=1e-3)
    assert np.all(np.diff(capped.vols) > 0) and capped.returns[-1] < free.returns[-1]
    assert np.allclose(capped.weights.sum(axis=0), 1.0, atol=1e-8) and capped.weights.min() >= -1e-9
    loose = efficient_portfolios(mu, cov, 9, 1.0, vol_ceiling=10.0)
    assert np.allclose(loose.weights, free.weights, atol=1e-6), "un tetto non vincolante non cambia nulla"


def test_a_ceiling_below_the_minimum_variance_is_raised_to_it(universe):
    mu, cov = universe
    fr = efficient_portfolios(mu, cov, 9, 1.0, vol_ceiling=1e-6)
    assert fr.vol_ceiling == pytest.approx(fr.vols[0]) and fr.vols[-1] - fr.vols[0] < 1e-3


@pytest.mark.parametrize("raw", [[0.5, 0.5, 0.5], [2.0, -1.0, 0.3], [0.0, 0.0, 0.0], [np.nan, 0.2, 0.2], [5.0, 5.0, 5.0]])
def test_projection_gives_non_negative_weights_within_the_caps_summing_to_one(raw):
    caps = np.array([0.5, 0.6, 0.7])
    out = _project(np.array(raw), caps)
    assert out.min() >= 0.0 and np.all(out <= caps + 1e-12) and out.sum() == pytest.approx(1.0, abs=1e-9)


def test_caps_are_always_feasible():
    assert _caps_array(0.05, 8) == pytest.approx(np.full(8, 0.25)), "mai sotto 2/n: con pochi asset non si forzano pesi uguali"
    caps = _caps_array(np.array([0.0, 0.1, 5.0]), 3)
    assert caps.sum() >= 1.0 and caps.min() > 0.0 and caps.max() <= 1.0


def test_the_maximum_return_portfolio_fills_the_best_assets_up_to_their_caps():
    mu = np.array([0.01, 0.05, 0.03])
    assert _max_return_weights(mu, np.array([0.5, 0.4, 0.5])) == pytest.approx([0.1, 0.4, 0.5])
    rules = np.array([[1.0, -1.0, 0.0]])                  # w0 >= w1: il migliore (asset 1) non può superare l'asset 0
    w = _max_return_weights(np.array([0.04, 0.05, 0.01]), np.array([0.8, 0.8, 0.8]), rules)
    assert w == pytest.approx([0.5, 0.5, 0.0], abs=1e-6)


def test_mixing_the_extreme_portfolios_hits_the_volatility_target(universe):
    mu, cov = universe
    fr = efficient_portfolios(mu, cov, 9, 1.0)
    w_min, w_max = fr.weights[:, 0], fr.weights[:, -1]
    target = 0.5 * (fr.vols[0] + fr.vols[-1])
    assert _vol(_mix_at_vol(w_min, w_max, cov, target), cov) == pytest.approx(target, rel=1e-6)
    assert np.allclose(_mix_at_vol(w_min, w_max, cov, fr.vols[0] * 0.5), w_min)
    assert np.allclose(_mix_at_vol(w_min, w_max, cov, fr.vols[-1] * 2.0), w_max)


# ------------------------------------------------------------------ posizioni minime
def _dust(weights, minimum):
    return int(((weights > 1e-9) & (weights < minimum - 1e-9)).sum())


@pytest.mark.parametrize("minimum", [0.02, 0.05])
def test_pruning_leaves_no_position_below_the_minimum_at_the_same_risk(universe, minimum):
    mu, cov = universe
    fr = efficient_portfolios(mu, cov, 9, 0.4)
    assert _dust(fr.weights, minimum) > 0, "il test ha senso solo se la frontiera ha posizioni minuscole"
    pruned = prune_positions(fr.weights, mu, cov, 0.4, minimum)
    assert _dust(pruned, minimum) == 0
    assert np.allclose(pruned.sum(axis=0), 1.0, atol=1e-8) and pruned.min() >= -1e-9 and pruned.max() <= 0.4 + 1e-8
    ret0, vol0 = portfolio_stats(fr.weights, mu, cov)
    ret1, vol1 = portfolio_stats(pruned, mu, cov)
    assert np.allclose(vol1[1:], vol0[1:], atol=1e-6), "il rischio di ogni portafoglio resta quello di prima"
    assert 0 <= vol1[0] - vol0[0] < 0.001, "tranne la minima varianza, che senza la posizione minuscola sale appena"
    assert (ret1[1:] <= ret0[1:] + 1e-9).all(), "togliere un asset non può dare più rendimento a parità di rischio"
    assert (ret0 - ret1).max() < 0.005, "e il costo in rendimento è piccolo"


def test_pruning_leaves_a_frontier_without_small_positions_untouched(universe):
    mu, cov = universe
    fr = efficient_portfolios(mu, cov, 9, 0.4)
    assert np.allclose(prune_positions(fr.weights, mu, cov, 0.4, 0.001), fr.weights)
    assert np.allclose(prune_positions(fr.weights, mu, cov, 0.4, 0.0), fr.weights)


def test_pruning_takes_a_minimum_per_asset(universe):
    mu, cov = universe
    fr = efficient_portfolios(mu, cov, 9, 0.4)
    minimum = np.zeros(8)
    minimum[3] = 0.10                                         # solo l'asset 3 ha un minimo
    pruned = prune_positions(fr.weights, mu, cov, 0.4, minimum)
    assert _dust(pruned[3:4], 0.10) == 0 and (fr.weights[3] > 1e-9).any() and (fr.weights[3] < 0.10 - 1e-9).any()
    untouched = [j for j in range(9) if not 1e-9 < fr.weights[3, j] < 0.10 - 1e-9]
    assert np.allclose(pruned[:, untouched], fr.weights[:, untouched])


def test_pruning_keeps_a_position_when_the_rest_could_not_make_a_portfolio():
    mu = np.array([0.05, 0.03])
    cov = np.diag([0.04, 0.02])
    weights = np.array([[0.95], [0.05]])
    pruned = prune_positions(weights, mu, cov, 1.0, 0.10)      # senza il secondo asset resterebbe un solo asset
    assert np.allclose(pruned, weights) and pruned.sum() == pytest.approx(1.0)


def test_pruning_respects_the_rules_and_drops_the_ones_that_belong_to_an_excluded_asset(universe):
    mu, cov = universe
    rules = np.zeros((1, 8))
    rules[0, 7], rules[0, 0] = 1.0, -0.5                      # w7 >= 0.5 * w0
    fr = efficient_portfolios(mu, cov, 9, 0.5, rules=rules)
    pruned = prune_positions(fr.weights, mu, cov, 0.5, 0.05, rules)
    assert _dust(pruned, 0.05) == 0 and (rules @ pruned >= -1e-7).all()
    free = prune_positions(fr.weights, mu, cov, 0.5, np.where(np.arange(8) == 7, 0.9, 0.0), rules,
                           rule_owner={0: 7})                 # l'asset 7 non può avere il 90%: viene escluso e la regola cade
    assert (free[7] < 1e-9).all() and np.allclose(free.sum(axis=0), 1.0, atol=1e-8)
