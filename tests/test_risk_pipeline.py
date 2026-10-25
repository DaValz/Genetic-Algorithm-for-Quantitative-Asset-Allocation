"""Test dei profili di rischio e della pipeline di ottimizzazione senza interfaccia."""
import numpy as np
import pytest

from goalga import GAConfig, snapshot
from goalga.pipeline import (
    RunSettings,
    UniverseChoice,
    choose_pool,
    is_monitorable,
    make_problem,
    market_from_prices,
    optimize,
    plan_to_spec,
    prepare_market,
    preview_profiles,
    spec_market_options,
    spec_plan,
    spec_settings,
)
from goalga.plan import Plan
from goalga.risk import PROFILE_KEYS, annual_return_quantile, profile_caps, restrict_market
from goalga.selection import (
    DEFAULT_STOCKS,
    MAX_WINDOW_YEARS,
    MIN_POSITION,
    MIN_STOCK_POSITION,
    Assumptions,
    split_pool,
)
from goalga.universe import DEFAULT_ETF_SELECTION

PLAN = Plan(w0=50_000, contribution=6_000, horizon=20, goals=((8, 40_000.0), (20, 250_000.0)), pr_target=0.9, alpha=0.05)
FAST = RunSettings(GAConfig(pop_size=40, patience=25, seed=5), n_scenarios=400, oos_n=1000)


# ------------------------------------------------------------------ profili
def test_profile_caps_split_the_scale_in_thirds():
    assert profile_caps(9) == {"cautious": 3, "balanced": 6, "dynamic": 9}
    assert profile_caps(12) == {"cautious": 4, "balanced": 8, "dynamic": 12}
    for n in range(2, 20):
        caps = profile_caps(n)
        assert 2 <= caps["cautious"] <= caps["balanced"] <= caps["dynamic"] == n, (n, caps)
    assert PROFILE_KEYS == ("cautious", "balanced", "dynamic")


def test_restrict_market_keeps_the_first_portfolios_and_their_scenarios(market):
    restricted = restrict_market(market, 4)
    assert restricted.n_portfolios == 4 and np.allclose(restricted.weights, market.weights[:, :4])
    full = market.draw_scenarios(5, 60, np.random.default_rng(1))
    part = restricted.draw_scenarios(5, 60, np.random.default_rng(1))
    assert np.allclose(part, full[:, :, :4]), "gli scenari del profilo sono un prefisso di quelli completi"
    assert restrict_market(market, market.n_portfolios) is market
    for bad in (0, market.n_portfolios + 1):
        with pytest.raises(ValueError):
            restrict_market(market, bad)


def test_bad_year_quantile_is_lower_for_riskier_portfolios_and_deterministic(market):
    q = [annual_return_quantile(market, level) for level in (1, 5, 9)]
    assert q[0] > q[2], "il portafoglio più aggressivo ha un anno sfavorevole peggiore"
    assert annual_return_quantile(market, 9) == annual_return_quantile(market, 9)


# ------------------------------------------------------------------ ottimizzazione con limite di rischio
def test_optimize_respects_the_risk_cap_and_records_the_full_scale(market):
    out = optimize(PLAN, market, FAST, max_level=3)
    assert out.max_level == 3 and out.market.n_portfolios == 3
    assert int(np.max(out.report.path)) <= 3
    assert out.trace["cap"] == 3 and out.trace["K"] == market.n_portfolios, "la scena mostra tutta la scala con il limite"
    uncapped = optimize(PLAN, market, FAST, record=False, validate=False)
    assert uncapped.max_level == market.n_portfolios and uncapped.trace is None and uncapped.report.oos is None


def test_same_settings_give_the_same_result(market):
    a = optimize(PLAN, market, FAST, max_level=6, record=False, validate=False)
    b = optimize(PLAN, market, FAST, max_level=6, record=False, validate=False)
    assert a.report.path.tolist() == b.report.path.tolist() and a.report.pr == b.report.pr


def test_validation_scenarios_are_independent_of_the_search(market):
    out = optimize(PLAN, market, FAST, max_level=6)
    assert out.report.oos is not None and out.report.oos.n_scenarios == FAST.oos_n


def test_make_problem_is_reproducible(market):
    flows, problem_a = make_problem(PLAN, market, FAST)
    _, problem_b = make_problem(PLAN, market, FAST)
    path = np.full(PLAN.horizon, 3)
    assert np.array_equal(problem_a.terminal_wealth(path), problem_b.terminal_wealth(path))
    assert flows.horizon == PLAN.horizon and problem_a.S == FAST.n_scenarios and problem_a.H == market.n_portfolios
    other = RunSettings(GAConfig(pop_size=40, patience=25, seed=6), 400, 1000)
    assert not np.array_equal(problem_a.terminal_wealth(path), make_problem(PLAN, market, other)[1].terminal_wealth(path))


# ------------------------------------------------------------------ anteprime
def test_previews_cover_the_three_profiles(market):
    seen = []
    previews = preview_profiles(PLAN, market, FAST, progress=lambda done, total: seen.append((done, total)))
    assert [p.key for p in previews] == list(PROFILE_KEYS) and seen == [(1, 3), (2, 3), (3, 3)]
    assert [p.max_level for p in previews] == [3, 6, 9]
    for p in previews:
        assert 0.0 <= p.pr <= 1.0 and np.isfinite(p.bad_year) and len(p.path) == PLAN.horizon
        assert max(p.path) <= p.max_level
    assert previews[0].ret < previews[2].ret and previews[0].vol < previews[2].vol


def test_the_full_search_never_loses_what_the_preview_found(market):
    """A parità di seed la ricerca breve è un prefisso di quella completa: il risultato non può peggiorare."""
    previews = {p.key: p for p in preview_profiles(PLAN, market, FAST)}
    longer = RunSettings(GAConfig(pop_size=40, patience=120, seed=5), n_scenarios=400, oos_n=0)
    for key, cap in profile_caps(market.n_portfolios).items():
        full = optimize(PLAN, market, longer, max_level=cap, record=False, validate=False).result
        if previews[key].feasible:
            assert full.feasible, key
        else:
            assert full.pr >= previews[key].pr - 1e-9, key


def test_profiles_sharing_a_cap_are_computed_once(market):
    calls = []
    previews = preview_profiles(PLAN, market, FAST, keys=("balanced", "balanced"), progress=lambda *a: calls.append(a))
    assert previews[0].path == previews[1].path and len(calls) == 2


# ------------------------------------------------------------------ specifiche e piano residuo
def test_plan_spec_round_trip():
    rebuilt = spec_plan({"plan": plan_to_spec(PLAN, ["casa", "pensione"])})
    assert (rebuilt.w0, rebuilt.contribution, rebuilt.horizon) == (PLAN.w0, PLAN.contribution, PLAN.horizon)
    assert rebuilt.goals == PLAN.goals and rebuilt.pr_target == PLAN.pr_target and rebuilt.alpha == PLAN.alpha
    assert rebuilt.effective_last_contribution() == PLAN.effective_last_contribution()
    assert [g["kind"] for g in plan_to_spec(PLAN, ["casa", "pensione"])["goals"]] == ["casa", "pensione"]


def test_spec_settings_defaults_and_overrides():
    default = spec_settings({})
    assert (default.ga.pop_size, default.n_scenarios, default.oos_n) == (100, 1000, 10_000)
    custom = spec_settings({"ga": {"pop_size": 60, "seed": 7, "n_scenarios": 500, "oos_n": 0}})
    assert (custom.ga.pop_size, custom.ga.seed, custom.n_scenarios, custom.oos_n) == (60, 7, 500, 0)


def test_only_plans_with_prices_from_the_archive_and_efficient_portfolios_are_monitorable():
    assert is_monitorable({}) and is_monitorable({"market": {"source": "market"}})
    assert is_monitorable({"market": {"source": "yahoo"}}), "le specifiche salvate dalle versioni precedenti restano seguibili"
    assert not is_monitorable({"market": {"source": "file"}})
    assert not is_monitorable({"market": {"source": "demo"}})
    assert not is_monitorable({"market": {"source": "market", "custom_weights": True}})


def test_advance_removes_past_goals_and_keeps_the_rest_on_schedule():
    rest = PLAN.advance(8, 123_456.0)
    assert rest is not None and rest.w0 == 123_456.0 and rest.horizon == 12 and rest.goals == ((12, 250_000.0),)
    assert PLAN.advance(20, 1.0) is None and PLAN.advance(19, 1.0) is None, "non resta nulla da pianificare"
    inflated = Plan(w0=0, contribution=1_000, horizon=10, goals=((10, 100_000.0),), inflation=0.02,
                    contribution_growth=0.01).advance(5, 10_000.0)
    assert inflated.goals == ((5, pytest.approx(100_000.0 * 1.02 ** 5)),)
    assert inflated.contribution == pytest.approx(1_000 * 1.01 ** 5)


def test_goal_kinds_follow_the_goals_that_are_left_not_their_position():
    from goalga.pipeline import goal_kinds
    original = [{"kind": "casa", "start": 8, "end": 8, "amount": 40_000.0},
                {"kind": "studi", "start": 12, "end": 14, "amount": 10_000.0},
                {"kind": "pensione", "start": 25, "end": 25, "amount": 300_000.0}]
    plan = Plan(w0=50_000, contribution=6_000, horizon=25,
                goals=((8, 40_000.0), (12, 10_000.0), (13, 10_000.0), (14, 10_000.0), (25, 300_000.0)))
    assert goal_kinds(plan, original) == ["casa", "studi", "pensione"]
    rest = plan.advance(9, 70_000.0)                 # la casa è stata pagata: i gruppi restanti sono due
    assert goal_kinds(rest, original, 9) == ["studi", "pensione"], "per posizione sarebbero «casa» e «studi»"
    later = plan.advance(13, 90_000.0)               # restano l'ultimo anno degli studi e la pensione
    assert goal_kinds(later, original, 13) == ["studi", "pensione"]
    assert goal_kinds(rest, [], 9) == ["altro", "altro"], "senza informazioni vale «altro»"


def test_advance_from_the_middle_of_a_year_keeps_the_flows_on_their_anniversaries():
    rest = PLAN.advance(8, 123_456.0, fraction=0.3)
    assert rest.first_period == pytest.approx(0.7) and rest.horizon == 12 and rest.goals == ((12, 250_000.0),)
    assert rest.flows().first_period == pytest.approx(0.7)
    whole = PLAN.advance(8, 123_456.0)
    assert whole.first_period == 1.0 and rest.flows().net.tolist() == whole.flows().net.tolist(), \
        "stessi versamenti e obiettivi, alle stesse scadenze: cambia solo la durata del primo anno"
    assert PLAN.advance(0, 20_000.0, fraction=0.999).first_period == pytest.approx(1 / 52), "mai meno di una settimana"
    assert PLAN.advance(0, 20_000.0, fraction=0.0).first_period == 1.0


def test_a_partial_first_year_survives_the_serialised_spec():
    from goalga.pipeline import plan_to_spec, spec_plan
    rest = PLAN.advance(3, 80_000.0, fraction=0.45)
    spec = {"plan": plan_to_spec(rest)}
    assert spec["plan"]["first_period"] == pytest.approx(0.55) and spec_plan(spec).first_period == pytest.approx(0.55)
    assert "first_period" not in plan_to_spec(PLAN), "i piani interi restano scritti come prima"
    spec["plan"]["first_period"] = "x"
    assert spec_plan(spec).first_period == 1.0, "un valore illeggibile vale anno intero"


@pytest.mark.parametrize("field, value", [("w0", float("nan")), ("w0", float("inf")), ("contribution", float("nan")),
                                         ("contribution", float("inf"))])
def test_a_plan_with_non_finite_money_is_invalid(field, value):
    assert Plan(**{**PLAN.__dict__, field: value}).validate()


def test_a_goal_with_a_non_finite_amount_is_invalid():
    assert Plan(w0=1_000, contribution=100, horizon=5, goals=((3, float("inf")),)).validate()
    assert Plan(w0=1_000, contribution=100, horizon=5, goals=((3, float("nan")),)).validate()


# ------------------------------------------------------------------ universo, specifiche v2 e monitor
@pytest.fixture()
def archive():
    return snapshot.load_prices()


def test_specs_without_market_options_fall_back_to_the_defaults_of_earlier_versions():
    opts = spec_market_options({})
    assert opts["universe"] == DEFAULT_ETF_SELECTION and opts["years"] == 20 and opts["max_weight"] == 0.40
    assert opts["stock_share"] == 0.30 and opts["stock_max"] == 0.60 and opts["class_caps"] is True
    assert opts["assumptions"] == Assumptions() and opts["cma"] is None and opts["shrinkage"] is True
    assert opts["min_position"] == 0.0 and opts["min_stock_position"] == 0.0 and opts["max_years"] is None, \
        "le specifiche salvate prima dei minimi e del tetto di finestra restano identiche (niente falsi avvisi)"
    modern = spec_market_options({"market": {"min_position": 0.01, "min_stock_position": 0.005, "max_years": 14}})
    assert modern["min_position"] == 0.01 and modern["min_stock_position"] == 0.005 and modern["max_years"] == 14.0
    custom = spec_market_options({"market": {"universe": ["SPY", "XEON.MI"], "max_weight": 0.25, "stock_share": 0.0,
                                             "class_caps": False, "method": "monthly",
                                             "assumptions": {"source": "historical", "outlook": 0.01}}})
    assert custom["universe"] == ["SPY", "XEON.MI"] and custom["max_weight"] == 0.25 and custom["stock_share"] == 0.0
    assert custom["class_caps"] is False and custom["method"] == "monthly"
    assert custom["assumptions"] == Assumptions(source="historical", outlook=0.01)


def test_the_automatic_pool_depends_only_on_the_seed(archive):
    choice = UniverseChoice()
    pool, screen = choose_pool(archive, 11, choice)
    again, _ = choose_pool(archive, 11, choice)
    other, _ = choose_pool(archive, 12, choice)
    assert pool == again and pool != other
    funds, stocks = split_pool(pool)
    assert len(funds) == 40 and len(stocks) == DEFAULT_STOCKS and screen.n_eligible > len(pool)


def test_the_universe_choice_narrows_the_automatic_pool(archive):
    from goalga.universe import catalog
    pool, screen = choose_pool(archive, 3, UniverseChoice(categories=("cash", "dev_equity", "technology"), stocks=8,
                                                          excluded=("XEON.MI",)))
    funds, stocks = split_pool(pool)
    table, eligible = catalog(), screen.eligible()
    expected = {t for t in eligible.index[eligible["Tipo"] == "fund"] if table.at[t, "Categoria"] in ("cash", "dev_equity")}
    assert set(funds) == expected - {"XEON.MI"} and len(stocks) == 8
    assert {table.at[s, "Categoria"] for s in stocks} == {"technology"}


def test_manual_mode_keeps_only_the_picks_that_pass_the_screen(archive):
    picks = ("XEON.MI", "SPY", "IEAC.MI", "ABR-PD", "NOT-A-TICKER", "IHYG.MI", "SXR8.DE")
    pool, _ = choose_pool(archive, 99, UniverseChoice(mode="manual", picks=picks))
    assert pool == ["XEON.MI", "SPY", "IEAC.MI", "IHYG.MI", "SXR8.DE"], "ordine scelto dall'utente, solo asset idonei"
    assert choose_pool(archive, 1, UniverseChoice(mode="manual", picks=picks))[0] == pool, "il seed non conta"


def test_the_market_is_built_from_the_pool_and_the_proxy_stays_out_unless_selected(archive):
    pool, _ = choose_pool(archive, 5, UniverseChoice())
    pool = [t for t in pool if t != "SPY"]
    opts = spec_market_options({"market": {"universe": pool}})
    market, prepared = market_from_prices(archive[[*pool, "SPY"]], opts)
    assert sorted(market.names) == sorted(pool) and "SPY" not in prepared.returns.columns
    assert market.meta["basket"]["min_share"] == 0.30 and market.n_portfolios == 9 and not prepared.dropped


def test_the_position_minimums_keep_dust_out_of_the_market_built_on_the_real_archive(archive):
    pool, _ = choose_pool(archive, 5, UniverseChoice())
    pool = [t for t in pool if t != "SPY"]
    opts = {**spec_market_options({"market": {"universe": pool}}), "min_position": MIN_POSITION,
            "min_stock_position": MIN_STOCK_POSITION, "max_years": MAX_WINDOW_YEARS}
    market, prepared = market_from_prices(archive[[*pool, "SPY"]], opts)
    funds, stocks = split_pool(market.names)
    w = market.weights_frame()
    held_funds, held_stocks = w.loc[funds].to_numpy(), w.loc[stocks].to_numpy()
    assert not ((held_funds > 1e-9) & (held_funds < MIN_POSITION - 1e-7)).any(), "nessun fondo sotto l'1%"
    assert not ((held_stocks > 1e-9) & (held_stocks < MIN_STOCK_POSITION - 1e-7)).any(), "nessun titolo sotto lo 0,5%"
    assert np.allclose(w.sum(), 1.0, atol=1e-7) and w.min().min() >= -1e-9 and w.loc[funds].max().max() <= 0.40 + 1e-7
    assert np.all(np.diff(market.stats[1]) > 0) and np.allclose(market.history.mean(axis=0), market.stats[0], atol=1e-9)
    assert prepared.n_months <= MAX_WINDOW_YEARS * 12


def test_the_monitor_rebuilds_the_same_market_from_a_saved_spec(archive):
    pool, _ = choose_pool(archive, 5, UniverseChoice())
    spec = {"plan": plan_to_spec(PLAN), "market": {"source": "market", "universe": pool, "max_weight": 0.30,
                                                   "stock_share": 0.40, "assumptions": {"outlook": 0.01}}}
    market, prepared = prepare_market(spec)
    funds, _ = split_pool(market.names)
    assert sorted(market.names) == sorted(pool) and prepared.n_months >= 120
    assert market.weights_frame().loc[funds].max().max() <= 0.30 + 1e-7 and market.meta["basket"]["min_share"] == 0.40
    again, _ = prepare_market(spec)
    assert np.allclose(again.weights, market.weights) and np.allclose(again.mu, market.mu)
    base, _ = prepare_market({**spec, "market": {**spec["market"], "assumptions": {}}})
    assert np.allclose(market.mu - base.mu, 0.01)


def test_the_monitor_works_with_specs_saved_before_the_universe_existed():
    spec = {"plan": plan_to_spec(PLAN), "market": {"source": "yahoo", "universe": DEFAULT_ETF_SELECTION}}
    market, _ = prepare_market(spec)
    assert sorted(market.names) == sorted(DEFAULT_ETF_SELECTION) and "basket" not in market.meta
