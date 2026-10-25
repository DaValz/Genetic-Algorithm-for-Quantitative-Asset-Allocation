"""Test della generazione degli scenari e dell'oggetto Market."""
import numpy as np
import pandas as pd
import pytest

from goalga import build_market
from goalga.scenarios import (
    annual_windows, bootstrap_annual, bootstrap_monthly, expected_annual_return,
    recenter_annual, recenter_monthly,
)


def test_annual_windows_match_manual_compounding():
    rng = np.random.default_rng(0)
    r = rng.normal(0.005, 0.03, size=(30, 3))
    w = annual_windows(r)
    assert w.shape == (19, 3)
    assert np.allclose(w[0], np.prod(1 + r[:12], axis=0) - 1)
    assert np.allclose(w[-1], np.prod(1 + r[-12:], axis=0) - 1)


def test_recentering_imposes_the_requested_means():
    rng = np.random.default_rng(1)
    r = rng.normal(0.01, 0.04, size=(120, 4))
    target = np.array([0.02, 0.05, 0.08, -0.01])
    assert np.allclose(recenter_annual(annual_windows(r), target).mean(axis=0), target, atol=1e-12)
    centred = recenter_monthly(r, target)
    assert np.allclose(expected_annual_return(centred), target, atol=1e-12)


def test_bootstrap_shapes_and_reproducibility():
    hist = np.random.default_rng(0).normal(0.05, 0.1, size=(100, 9))
    a = bootstrap_annual(hist, 20, 50, np.random.default_rng(7))
    b = bootstrap_annual(hist, 20, 50, np.random.default_rng(7))
    assert a.shape == (50, 20, 9) and np.array_equal(a, b)
    m = bootstrap_monthly(hist / 4, 20, 50, np.random.default_rng(7))
    assert m.shape == (50, 20, 9) and m.min() > -1


def test_bootstrap_rows_keep_cross_sectional_dependence():
    rng = np.random.default_rng(3)
    common = rng.normal(size=400)
    hist = np.column_stack([common + 0.2 * rng.normal(size=400), common + 0.2 * rng.normal(size=400)]) * 0.1
    scen = bootstrap_annual(hist, 30, 400, np.random.default_rng(0)).reshape(-1, 2)
    assert np.corrcoef(scen.T)[0, 1] == pytest.approx(np.corrcoef(hist.T)[0, 1], abs=0.03)


def test_monthly_bootstrap_mean_matches_target():
    rng = np.random.default_rng(2)
    hist = recenter_monthly(rng.normal(0.006, 0.04, size=(200, 2)), np.array([0.04, 0.09]))
    scen = bootstrap_monthly(hist, 1, 40_000, np.random.default_rng(5))[:, 0, :]
    assert scen.mean(axis=0) == pytest.approx([0.04, 0.09], abs=0.004)


# ------------------------------------------------------------------ Market
@pytest.mark.parametrize("method", ["annual", "monthly"])
def test_market_scenarios_are_centred_on_expected_returns(monthly_returns, method):
    custom = {"EQ_USA": 0.03, "CASH": 0.01}
    mk = build_market(monthly_returns, expected_returns=custom, method=method, max_weight=1.0)
    assert mk.mu[mk.names.index("EQ_USA")] == 0.03 and mk.mu[mk.names.index("CASH")] == 0.01
    scen = mk.draw_scenarios(1, 60_000, np.random.default_rng(0))[:, 0, :]
    expected, _ = mk.stats
    assert scen.mean(axis=0) == pytest.approx(expected, abs=0.004)


def test_market_without_custom_returns_keeps_history(monthly_returns):
    mk = build_market(monthly_returns, method="annual", max_weight=1.0)
    assert np.allclose(mk.mu, mk.mu_hist)
    assert np.allclose(mk.history.mean(axis=0), mk.stats[0], atol=1e-9)


def test_custom_weights_are_validated(monthly_returns):
    mk = build_market(monthly_returns, max_weight=1.0)
    w = np.full((mk.n_assets, 9), 1.0 / mk.n_assets)
    assert mk.with_weights(w).custom_weights
    with pytest.raises(ValueError):
        mk.with_weights(w * 1.1)
    with pytest.raises(ValueError):
        mk.with_weights(-w)


def test_custom_portfolios_are_ordered_by_risk_so_that_the_glide_path_can_only_de_risk(monthly_returns):
    """Se i portafogli arrivassero dal più al meno rischioso, il percorso «mai in aumento» crescerebbe di rischio."""
    mk = build_market(monthly_returns, max_weight=1.0)
    reversed_weights = mk.weights[:, ::-1]
    custom = mk.with_weights(reversed_weights)
    assert np.all(np.diff(custom.stats[1]) >= 0) and custom.custom_weights
    assert np.allclose(custom.weights, mk.weights), "stessi portafogli, ordinati dal meno al più rischioso"
    shuffled = mk.with_weights(mk.weights[:, np.random.default_rng(4).permutation(9)])
    assert np.all(np.diff(shuffled.stats[1]) >= 0) and np.allclose(shuffled.weights.sum(axis=0), 1.0)


def test_market_input_validation(monthly_returns):
    with pytest.raises(ValueError):
        build_market(monthly_returns.iloc[:10])
    with pytest.raises(ValueError):
        build_market(monthly_returns.iloc[:, :1])
    bad = monthly_returns.copy()
    bad.iloc[3, 2] = np.nan
    with pytest.raises(ValueError):
        build_market(bad)
    with pytest.raises(ValueError):
        build_market(monthly_returns, method="foo")


def test_shrinkage_toggle(monthly_returns):
    sample = build_market(monthly_returns, use_shrinkage=False)
    assert sample.shrinkage == 0.0
    shrunk = build_market(monthly_returns, use_shrinkage=True)
    assert 0.0 <= shrunk.shrinkage <= 1.0
    assert isinstance(shrunk.summary(), pd.DataFrame) and shrunk.weights_frame().shape[1] == 9
