"""Test della selezione: valutazione dell'universo, pool estratto dal seed, rendimenti attesi e mercato del pool."""
import numpy as np
import pandas as pd
import pytest

from goalga import snapshot
from goalga.pipeline import proxy_returns
from goalga.scenarios import expected_annual_return
from goalga.selection import (
    BLUME,
    DEFAULT_STOCKS,
    MIN_POSITION,
    MIN_STOCK_POSITION,
    REASONS,
    Assumptions,
    PoolSettings,
    build_pool_market,
    draw_pool,
    estimate_betas,
    expected_returns,
    fingerprint,
    get_screen,
    quotas,
    screen_universe,
    split_pool,
)
from goalga.universe import (
    CATEGORIES,
    FUND_CATEGORIES,
    SECTOR_CATEGORIES,
    catalog,
    equity_premium_default,
    investable_tickers,
    risk_free_default,
)


@pytest.fixture(scope="module")
def prices(snapshot_file):
    return snapshot.load_prices(snapshot_file)


@pytest.fixture(scope="module")
def screen(prices):
    return screen_universe(prices, min_years=10)


# ------------------------------------------------------------------ valutazione di tutto l'universo
def test_every_catalog_asset_is_evaluated_and_each_exclusion_has_a_reason(screen, prices):
    table = screen.table
    assert screen.n_evaluated == len(catalog()) and set(table.index) == set(catalog().index)
    assert table.loc[~table["Eligible"], "Reason"].ne("").all() and table.loc[table["Eligible"], "Reason"].eq("").all()
    counts = screen.reason_counts()
    assert set(counts) <= set(REASONS) and list(counts) == [r for r in REASONS if r in counts], "ordine standard dei motivi"
    assert counts["no_data"] == len(investable_tickers()) - prices.shape[1], "gli asset investibili senza prezzi sono «senza dati»"
    assert counts["preferred"] > 100 and counts["fund"] > 200 and counts["misc"] > 20 and counts["crypto"] == 2


def test_the_screen_catches_short_stale_and_abnormal_series(screen, prices):
    counts = screen.reason_counts()
    assert counts["short"] == 1 and counts["stale"] == 1 and counts["extreme"] == 1, "i tre casi dimostrativi dell'archivio"
    assert screen.n_eligible == prices.shape[1] - 3


def test_funds_are_always_eligible_when_they_have_a_complete_history(screen):
    table = screen.table
    funds = table[table["Tipo"] == "fund"]
    assert len(funds) == 40 and funds["Eligible"].all()


def test_a_shorter_required_history_lets_more_assets_in(prices):
    ten, five, three = (screen_universe(prices, min_years=y) for y in (10, 5, 3))
    assert five.n_eligible == ten.n_eligible + 1 and "short" not in five.reason_counts(), \
        "il titolo con sei anni di storico entra con meno richiesta"
    assert three.n_eligible == five.n_eligible + 1 and "extreme" not in three.reason_counts(), \
        "il salto anomalo di 40 mesi fa esce dalla finestra di 3 anni"
    assert ten.min_years == 10.0 and five.min_years == 5.0 and three.start > five.start > ten.start


def test_the_screen_measures_beta_volatility_and_a_rank_inside_each_category(screen):
    ok = screen.eligible()
    assert ok[["Vol", "Beta", "R2", "Score", "Rank"]].notna().all().all()
    assert ok["Rank"].between(0.0, 1.0).all() and ok["Vol"].gt(0).all()
    assert screen.table.loc[~screen.table["Eligible"], "Rank"].eq(0.0).all()
    beta = ok[ok["Tipo"] == "stock"].groupby("Categoria")["Beta"].mean()
    assert beta["technology"] > beta["utilities"] + 0.3, "i settori ciclici hanno beta più alto di quelli difensivi"


def test_category_counts_cover_every_category(screen):
    counts = screen.category_counts()
    assert list(counts) == list(CATEGORIES) and sum(counts.values()) == screen.n_eligible
    assert sum(counts[c] for c in FUND_CATEGORIES) == 40 and all(counts[c] > 0 for c in SECTOR_CATEGORIES)


def test_the_screen_is_cached_by_the_content_of_the_prices(prices):
    first = get_screen(prices, 10.0)
    assert get_screen(prices, 10.0) is first and get_screen(prices.copy(), 10.0) is first
    assert get_screen(prices, 5.0) is not first
    assert fingerprint(prices) != fingerprint(prices.iloc[:-1])


def test_the_screen_cache_is_safe_when_many_sessions_ask_at_once(prices):
    """Più sessioni (thread) dello stesso processo condividono la cache: nessun errore, nessun risultato scambiato."""
    from concurrent.futures import ThreadPoolExecutor

    from goalga import selection
    years = [3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0] * 2                           # più chiavi di quante ne contiene la cache
    with ThreadPoolExecutor(8) as workers:
        results = list(workers.map(lambda y: get_screen(prices, y), years))
    assert [r.min_years for r in results] == years and len(selection._SCREENS) <= 6


def test_a_very_short_archive_still_yields_a_screen():
    index = pd.date_range("2026-01-31", periods=6, freq="ME")
    tiny = pd.DataFrame({"SPY": np.linspace(100, 110, 6), "AAPL": np.linspace(10, 12, 6)}, index=index)
    result = screen_universe(tiny, min_years=10)
    assert result.n_eligible == 0 and result.reason_counts()["short"] == 2


# ------------------------------------------------------------------ quote per settore
def test_quotas_split_the_stock_budget_by_the_square_root_of_the_sector_size():
    out = quotas({"a": 400, "b": 100, "c": 25, "d": 0}, 33)
    assert sum(out.values()) == 33 and out["d"] == 0 and min(out["a"], out["b"], out["c"]) >= 1
    assert out["a"] > out["b"] > out["c"] and out["a"] / out["c"] < 400 / 25, "più titoli, più quota, ma meno che proporzionale"


@pytest.mark.parametrize("counts, total, expected_total", [
    ({"a": 2, "b": 1}, 10, 3),               # non si pesca più di quanto c'è
    ({"a": 5, "b": 5, "c": 5}, 2, 2),        # meno titoli che settori
    ({"a": 5, "b": 5}, 0, 0),
    ({}, 5, 0),
    ({"a": 0, "b": 0}, 5, 0),
])
def test_quotas_never_exceed_the_budget_or_the_availability(counts, total, expected_total):
    out = quotas(counts, total)
    assert sum(out.values()) == expected_total and all(out[c] <= counts[c] for c in counts)


# ------------------------------------------------------------------ pool
def test_the_pool_has_every_eligible_fund_and_a_stock_basket_from_every_sector(screen):
    pool = draw_pool(screen, 1)
    funds, stocks = split_pool(pool)
    table = screen.eligible()
    assert set(funds) == set(table.index[table["Tipo"] == "fund"]) and len(stocks) == DEFAULT_STOCKS
    sectors = table.loc[stocks, "Categoria"].value_counts()
    assert set(sectors.index) == set(SECTOR_CATEGORIES) and sectors.min() >= 1
    assert pool == funds + sorted(stocks) and len(set(pool)) == len(pool)


def test_the_same_seed_gives_the_same_pool_and_another_seed_another_one(screen):
    assert draw_pool(screen, 7) == draw_pool(screen, 7)
    assert split_pool(draw_pool(screen, 7))[1] != split_pool(draw_pool(screen, 8))[1]


def test_over_many_seeds_the_whole_universe_gets_its_chance(screen):
    table = screen.eligible()
    eligible_stocks = set(table.index[table["Tipo"] == "stock"])
    seen: dict[str, int] = {}
    for seed in range(1, 121):
        for ticker in split_pool(draw_pool(screen, seed))[1]:
            seen[ticker] = seen.get(ticker, 0) + 1
    assert set(seen) <= eligible_stocks, "solo titoli idonei"
    assert len(seen) / len(eligible_stocks) > 0.9, "nel tempo quasi ogni titolo idoneo entra almeno una volta"
    rank = table.loc[list(eligible_stocks), "Rank"]
    freq = pd.Series({t: seen.get(t, 0) for t in eligible_stocks})
    top, bottom = freq[rank[rank >= rank.quantile(2 / 3)].index].mean(), freq[rank[rank <= rank.quantile(1 / 3)].index].mean()
    assert top > bottom, "i titoli con più rischio remunerato escono più spesso, ma tutti hanno la loro possibilità"


def test_excluded_assets_and_unselected_categories_stay_out_of_the_pool(screen):
    pool = draw_pool(screen, 3)
    funds, stocks = split_pool(pool)
    dropped = [funds[0], stocks[0].lower()]               # l'esclusione non dipende da maiuscole e minuscole
    again = draw_pool(screen, 3, excluded=dropped)
    assert funds[0] not in again and stocks[0] not in again
    only = draw_pool(screen, 3, categories=["dev_equity", "technology"], stocks=10)
    table = screen.eligible()
    assert {table.at[x, "Categoria"] for x in only} == {"dev_equity", "technology"} and len(split_pool(only)[1]) == 10


def test_asking_for_more_stocks_than_a_sector_has_takes_them_all(screen):
    table = screen.eligible()
    tech = table.index[(table["Tipo"] == "stock") & (table["Categoria"] == "technology")]
    pool = draw_pool(screen, 2, categories=["technology"], stocks=500)
    assert set(split_pool(pool)[1]) == set(tech) and split_pool(pool)[0] == []


def test_a_pool_without_stocks_is_just_the_funds(screen):
    funds, stocks = split_pool(draw_pool(screen, 4, stocks=0))
    assert stocks == [] and len(funds) == 40


# ------------------------------------------------------------------ ipotesi di rendimento
def test_assumptions_round_trip_and_know_when_they_are_the_default():
    custom = Assumptions(source="historical", outlook=0.01, class_shift={"cash": 0.005})
    assert Assumptions.from_dict(custom.to_dict()) == custom and Assumptions.from_dict(None) == Assumptions()
    assert Assumptions().is_default and Assumptions(class_shift={"cash": 0.0}).is_default
    assert not custom.is_default and not Assumptions(outlook=0.001).is_default


def test_betas_are_recovered_and_pulled_towards_one():
    rng = np.random.default_rng(0)
    proxy = pd.Series(rng.normal(0.008, 0.04, 4000))
    frame = pd.DataFrame({"HIGH": 1.5 * proxy + rng.normal(0, 0.01, 4000), "LOW": 0.4 * proxy + rng.normal(0, 0.01, 4000)})
    betas = estimate_betas(frame, proxy)
    assert betas["HIGH"] == pytest.approx(BLUME[0] * 1.5 + BLUME[1], abs=0.03)
    assert betas["LOW"] == pytest.approx(BLUME[0] * 0.4 + BLUME[1], abs=0.03)
    assert estimate_betas(frame, None) == {} and estimate_betas(frame.iloc[:8], proxy.iloc[:8]) == {}
    assert estimate_betas(frame, proxy.where(proxy.index != 5)) == {}, "con buchi nell'indice non si stima"


def _returns(prices, tickers):
    return prices[tickers].pct_change().iloc[1:]


def test_funds_use_the_long_term_assumption_and_stocks_use_the_capm(prices, screen):
    stock = split_pool(draw_pool(screen, 1))[1][0]
    frame = _returns(prices, ["XEON.MI", "SXR8.DE", stock, "SPY"])
    proxy = proxy_returns(prices, frame.index)
    mu = expected_returns(frame, Assumptions(), proxy)
    table = catalog()
    assert mu["XEON.MI"] == pytest.approx(table.at["XEON.MI", "CMA"]) and mu["SXR8.DE"] == pytest.approx(table.at["SXR8.DE", "CMA"])
    beta = estimate_betas(frame, proxy)[stock]
    assert mu[stock] == pytest.approx(risk_free_default() + beta * equity_premium_default())


def test_class_shifts_and_the_outlook_move_the_expected_returns(prices, screen):
    stock = split_pool(draw_pool(screen, 1))[1][0]
    frame = _returns(prices, ["XEON.MI", "SXR8.DE", "IEAC.MI", stock])
    proxy = proxy_returns(prices, frame.index)
    base = expected_returns(frame, Assumptions(), proxy)
    equity = expected_returns(frame, Assumptions(class_shift={"dev_equity": 0.01}), proxy)
    assert equity["SXR8.DE"] == pytest.approx(base["SXR8.DE"] + 0.01) and equity["XEON.MI"] == base["XEON.MI"]
    premium = expected_returns(frame, Assumptions(class_shift={"stocks": 0.01}), proxy)
    beta = estimate_betas(frame, proxy)[stock]
    assert premium[stock] == pytest.approx(base[stock] + beta * 0.01) and premium["IEAC.MI"] == base["IEAC.MI"]
    cash = expected_returns(frame, Assumptions(class_shift={"cash": 0.01}), proxy)
    assert cash[stock] == pytest.approx(base[stock] + 0.01), "il tasso privo di rischio sposta anche il CAPM"
    outlook = expected_returns(frame, Assumptions(outlook=-0.01), proxy)
    assert all(outlook[t] == pytest.approx(base[t] - 0.01) for t in base)


def test_historical_source_uses_the_sample_means_and_unknown_assets_fall_back_to_them(prices):
    frame = _returns(prices, ["XEON.MI", "SPY"]).assign(NOPE=0.004)
    hist = dict(zip(frame.columns, expected_annual_return(frame.to_numpy())))
    mu = expected_returns(frame, Assumptions(source="historical"))
    assert all(mu[t] == pytest.approx(hist[t]) for t in frame.columns)
    base = expected_returns(frame, Assumptions())
    assert base["NOPE"] == pytest.approx(hist["NOPE"]) and base["XEON.MI"] == pytest.approx(catalog().at["XEON.MI", "CMA"])


def test_expected_returns_stay_in_a_sensible_range(prices):
    frame = _returns(prices, ["XEON.MI", "SPY"])
    high, low = expected_returns(frame, Assumptions(outlook=1.0)), expected_returns(frame, Assumptions(outlook=-1.0))
    assert max(high.values()) == 0.60 and min(low.values()) == -0.05


# ------------------------------------------------------------------ mercato del pool
@pytest.fixture(scope="module")
def pool_market(prices, screen):
    pool = draw_pool(screen, 3)
    frame = _returns(prices, pool)
    return pool, build_pool_market(frame, PoolSettings(), proxy_returns(prices, frame.index))


def test_the_pool_market_has_nine_ordered_portfolios_within_the_caps(pool_market):
    pool, market = pool_market
    assert market.weights.shape == (len(pool), 9) and np.allclose(market.weights.sum(axis=0), 1.0, atol=1e-7)
    assert market.weights.min() >= -1e-9 and np.all(np.diff(market.stats[1]) > 0) and not market.frontier.degenerate
    funds, stocks = split_pool(market.names)
    assert market.meta["pool"] == {"funds": len(funds), "stocks": len(stocks)}
    w = pd.DataFrame(market.weights, index=market.names)
    assert w.loc[funds].to_numpy().max() <= 0.40 + 1e-7, "tetto per fondo"


def test_a_whole_asset_class_cannot_exceed_the_cap_even_through_duplicate_funds(pool_market):
    pool, market = pool_market
    w = pd.DataFrame(market.weights, index=market.names)
    table = catalog()
    for category in FUND_CATEGORIES:
        members = [t for t in market.names if table.at[t, "Tipo"] == "fund" and table.at[t, "Categoria"] == category]
        assert w.loc[members].sum().max() <= 0.40 + 1e-6, category


def test_stocks_form_an_equal_weight_basket_with_a_minimum_share_of_the_equity_exposure(pool_market):
    pool, market = pool_market
    funds, stocks = split_pool(market.names)
    table = catalog()
    w = pd.DataFrame(market.weights, index=market.names)
    equity_funds = [t for t in funds if table.at[t, "Categoria"] in ("dev_equity", "em_equity")]
    basket = w.loc[stocks].sum()
    held = basket > 1e-9
    assert market.meta["basket"]["min_share"] == 0.30 and market.meta["basket"]["max_weight"] == 0.60
    assert held.any() and (~held).any(), "la cesta compare nei portafogli più aggressivi e manca in quelli prudenti"
    assert (basket <= 0.60 + 1e-7).all()
    assert (basket[held] >= 0.30 * (basket[held] + w.loc[equity_funds].sum()[held]) - 1e-7).all()
    assert np.allclose(w.loc[stocks].to_numpy().std(axis=0), 0.0, atol=1e-9), "stessi pesi per tutti i titoli della cesta"
    assert basket.iloc[0] < basket.iloc[-1], "il portafoglio aggressivo ha più azioni di quello prudente"


def test_no_position_is_too_small_to_buy_in_the_pool_market(pool_market, prices):
    pool, market = pool_market
    funds, stocks = split_pool(market.names)
    w = pd.DataFrame(market.weights, index=market.names)
    fund_w, stock_w = w.loc[funds].to_numpy(), w.loc[stocks].to_numpy()
    assert not ((fund_w > 1e-9) & (fund_w < MIN_POSITION - 1e-7)).any(), "nessun fondo sotto l'1%"
    assert not ((stock_w > 1e-9) & (stock_w < MIN_STOCK_POSITION - 1e-7)).any(), "nessun titolo sotto lo 0,5%"
    frame = _returns(prices, pool)
    free = build_pool_market(frame, PoolSettings(min_position=0.0, min_stock_position=0.0), proxy_returns(prices, frame.index))
    f = pd.DataFrame(free.weights, index=free.names)
    dust = ((f.loc[funds].to_numpy() > 1e-9) & (f.loc[funds].to_numpy() < MIN_POSITION - 1e-7)).sum() \
        + ((f.loc[stocks].to_numpy() > 1e-9) & (f.loc[stocks].to_numpy() < MIN_STOCK_POSITION - 1e-7)).sum()
    assert dust > 0, "senza minimi il mercato avrebbe posizioni minuscole: il test ha senso"
    assert np.allclose(w.sum(), 1.0, atol=1e-7) and np.allclose(market.history.mean(axis=0), market.stats[0], atol=1e-9)


def test_without_a_stock_share_every_asset_is_free_and_there_is_no_basket(prices, screen):
    table = screen.eligible()
    picks = [group.index[0] for _, group in table[table["Tipo"] == "fund"].groupby("Categoria")]
    picks += list(table.index[table["Tipo"] == "stock"][:3])
    frame = _returns(prices, picks)
    market = build_pool_market(frame, PoolSettings(stock_share=0.0, class_caps=False), proxy_returns(prices, frame.index))
    assert "basket" not in market.meta and market.n_assets == len(picks) and market.weights.max() <= 0.40 + 1e-7
    assert np.allclose(market.weights.sum(axis=0), 1.0, atol=1e-7)


def test_explicit_assumptions_per_asset_take_precedence(prices, screen):
    picks = ["XEON.MI", "IEAC.MI", "SXR8.DE", "SPY", "IEMA.AS"]
    frame = _returns(prices, picks)
    market = build_pool_market(frame, PoolSettings(), proxy_returns(prices, frame.index), cma={"XEON.MI": 0.035, "ZZZ": 0.5})
    assert market.mu[market.names.index("XEON.MI")] == pytest.approx(0.035) and "ZZZ" not in market.names


def test_the_user_assumptions_reach_the_expected_returns_of_the_market(prices):
    picks = ["XEON.MI", "IEAC.MI", "SXR8.DE", "SPY", "IEMA.AS"]
    frame = _returns(prices, picks)
    proxy = proxy_returns(prices, frame.index)
    base = build_pool_market(frame, PoolSettings(), proxy)
    shifted = build_pool_market(frame, PoolSettings(assumptions=Assumptions(outlook=0.01)), proxy)
    assert np.allclose(shifted.mu - base.mu, 0.01)
    assert base.mu[base.names.index("IEMA.AS")] == pytest.approx(catalog().at["IEMA.AS", "CMA"])
