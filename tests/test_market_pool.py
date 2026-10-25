"""Test del mercato con cesta di titoli, tetti per classe e tetti per asset."""
import numpy as np
import pytest

from goalga import build_market
from goalga.market import Basket

STOCKS = ("EQ_EUR", "EQ_USA", "EQ_PAC")
BONDS = ["EUR_BT", "EUR_GOV", "EUR_CORP", "GLOB_BOND"]


def test_the_basket_is_one_asset_for_the_frontier_and_is_expanded_to_equal_weights(monthly_returns):
    basket = Basket(STOCKS, min_share=0.30, max_weight=0.60, equity=("EQ_EM",))
    market = build_market(monthly_returns, max_weight=0.40, basket=basket)
    w = market.weights_frame()
    members = w.loc[list(STOCKS)]
    assert np.allclose(members.std(), 0.0, atol=1e-9), "pesi uguali per tutti i titoli della cesta"
    total = members.sum()
    assert (total <= 0.60 + 1e-7).all() and (total >= 0.30 * (total + w.loc["EQ_EM"]) - 1e-7).all()
    assert np.allclose(w.sum(), 1.0, atol=1e-7) and w.min().min() >= -1e-9
    assert market.meta["basket"] == {"members": list(STOCKS), "min_share": 0.30, "max_weight": 0.60}


def test_the_minimum_share_binds_in_the_portfolios_that_hold_equity(monthly_returns):
    members = list(STOCKS)

    def slack(frame):
        """Quota minima della cesta rispetto all'esposizione azionaria: positivo se la regola è rispettata."""
        basket = frame.loc[members].sum()
        return basket - 0.50 * (basket + frame.loc["EQ_EM"])

    free = build_market(monthly_returns, max_weight=0.40).weights_frame()
    ruled = build_market(monthly_returns, max_weight=0.40,
                         basket=Basket(STOCKS, min_share=0.50, max_weight=0.60, equity=("EQ_EM",))).weights_frame()
    assert (slack(ruled) >= -1e-7).all()
    assert (slack(free) < -1e-3).any(), "senza la regola le azioni singole sarebbero meno usate"


@pytest.mark.parametrize("basket", [
    None,
    Basket(STOCKS, min_share=0.0),                                        # nessuna quota minima: niente cesta
    Basket(("NOPE",)),                                                    # nessun membro nel mercato
])
def test_without_a_usable_basket_the_market_is_the_plain_one(monthly_returns, basket):
    plain = build_market(monthly_returns, max_weight=0.40)
    market = build_market(monthly_returns, max_weight=0.40, basket=basket)
    assert "basket" not in market.meta and np.allclose(market.weights, plain.weights, atol=1e-9)


def test_members_unknown_to_the_market_are_ignored(monthly_returns):
    market = build_market(monthly_returns, max_weight=0.40, basket=Basket(("EQ_EUR", "EQ_USA", "NOPE"), equity=("EQ_EM",)))
    assert market.meta["basket"]["members"] == ["EQ_EUR", "EQ_USA"]


def test_a_basket_made_of_every_asset_is_not_reduced(monthly_returns):
    market = build_market(monthly_returns, max_weight=1.0, basket=Basket(tuple(monthly_returns.columns)))
    assert "basket" not in market.meta


def test_an_asset_class_cannot_exceed_its_cap_through_several_funds(monthly_returns):
    free = build_market(monthly_returns, max_weight=0.40).weights_frame()
    capped = build_market(monthly_returns, max_weight=0.40, groups=[BONDS]).weights_frame()
    assert free.loc[BONDS].sum().max() > 0.40 + 1e-3, "senza tetto di classe i fondi obbligazionari superano il 40%"
    assert capped.loc[BONDS].sum().max() <= 0.40 + 1e-7 and np.allclose(capped.sum(), 1.0, atol=1e-7)


def test_the_class_cap_has_its_own_value(monthly_returns):
    capped = build_market(monthly_returns, max_weight=0.40, groups=[BONDS], group_cap=0.25).weights_frame()
    assert capped.loc[BONDS].sum().max() <= 0.25 + 1e-7


def test_class_caps_that_would_make_the_problem_impossible_are_skipped(monthly_returns):
    market = build_market(monthly_returns, max_weight=0.40, groups=[list(monthly_returns.columns)], group_cap=0.05)
    assert np.allclose(market.weights.sum(axis=0), 1.0, atol=1e-7) and market.weights.max() <= 0.40 + 1e-7


def test_a_single_fund_is_not_a_group(monthly_returns):
    single = build_market(monthly_returns, max_weight=0.40, groups=[["EUR_BT"], []])
    plain = build_market(monthly_returns, max_weight=0.40)
    assert np.allclose(single.weights, plain.weights, atol=1e-9)


def test_every_asset_can_have_its_own_cap(monthly_returns):
    """Un tetto per asset più stretto del 40% generale (ma non sotto 2/n: con 12 asset sarebbe il 16,7%)."""
    caps = np.full(monthly_returns.shape[1], 0.40)
    caps[list(monthly_returns.columns).index("EQ_USA")] = 0.20
    free = build_market(monthly_returns, max_weight=0.40).weights_frame()
    market = build_market(monthly_returns, max_weight=caps)
    w = market.weights_frame()
    assert free.loc["EQ_USA"].max() > 0.20 + 1e-3, "con il tetto generale EQ_USA supererebbe il 20%"
    assert w.loc["EQ_USA"].max() <= 0.20 + 1e-7 and w.drop("EQ_USA").max().max() <= 0.40 + 1e-7


def test_basket_and_class_caps_work_together(monthly_returns):
    market = build_market(monthly_returns, max_weight=0.40, groups=[BONDS],
                          basket=Basket(STOCKS, min_share=0.30, max_weight=0.50, equity=("EQ_EM",)))
    w = market.weights_frame()
    assert w.loc[BONDS].sum().max() <= 0.40 + 1e-7 and w.loc[list(STOCKS)].sum().max() <= 0.50 + 1e-7
    assert np.all(np.diff(market.stats[1]) > 0) and np.allclose(w.sum(), 1.0, atol=1e-7)


# ------------------------------------------------------------------ posizioni minime
def _dust(frame, minimum):
    return int(((frame > 1e-6) & (frame < minimum - 1e-6)).to_numpy().sum())


@pytest.mark.parametrize("minimum", [0.03, 0.08])
def test_a_minimum_position_removes_the_dust_from_every_portfolio(monthly_returns, minimum):
    free = build_market(monthly_returns, max_weight=0.40)
    market = build_market(monthly_returns, max_weight=0.40, min_weight=minimum)
    w = market.weights_frame()
    assert _dust(free.weights_frame(), minimum) > 0, "senza minimo ci sono posizioni minuscole"
    assert _dust(w, minimum) == 0
    assert np.allclose(w.sum(), 1.0, atol=1e-7) and w.max().max() <= 0.40 + 1e-7 and w.min().min() >= -1e-9
    assert np.all(np.diff(market.stats[1]) > 0), "i portafogli restano ordinati per rischio"
    assert np.allclose(market.stats[1], free.stats[1], atol=2e-3), "e il rischio di ogni portafoglio non cambia"


def test_a_pruned_market_keeps_the_simulated_history_centred_on_the_expected_returns(monthly_returns):
    market = build_market(monthly_returns, max_weight=0.40, min_weight=0.05)
    assert np.allclose(market.history.mean(axis=0), market.stats[0], atol=1e-9)


def test_no_minimum_leaves_the_market_as_it_was(monthly_returns):
    plain = build_market(monthly_returns, max_weight=0.40)
    zero = build_market(monthly_returns, max_weight=0.40, min_weight=0.0, basket_member_min=0.0)
    assert np.allclose(zero.weights, plain.weights, atol=1e-9)


def test_the_basket_is_held_only_when_every_stock_reaches_its_minimum(monthly_returns):
    basket = Basket(STOCKS, min_share=0.30, max_weight=0.60, equity=("EQ_EM",))
    market = build_market(monthly_returns, max_weight=0.40, basket=basket, min_weight=0.01, basket_member_min=0.05)
    w = market.weights_frame()
    held = w.loc[list(STOCKS)]
    total = held.sum()
    assert ((total < 1e-9) | (held.min() >= 0.05 - 1e-7)).all(), "ogni titolo vale almeno lo 0,05 oppure la cesta è esclusa"
    assert (total < 1e-9).any() and (total > 1e-9).any(), "la cesta compare solo nei portafogli aggressivi"
    out = total < 1e-9
    assert (w.loc["EQ_EM", out] > 1e-3).any(), "senza cesta la quota minima cade e i fondi azionari restano ammessi"
    assert np.allclose(w.sum(), 1.0, atol=1e-7) and _dust(w, 0.01) == 0
