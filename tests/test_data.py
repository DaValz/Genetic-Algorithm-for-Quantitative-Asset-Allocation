"""Test della pulizia dati: nessun dato inventato, finestra comune, mese incompleto."""
import numpy as np
import pandas as pd
import pytest

from goalga.data import DataError, prepare_returns
from goalga.universe import clean_label, load_etf_universe, load_stock_universe


def _daily(start, end, drift, vol, seed):
    idx = pd.bdate_range(start, end)
    rng = np.random.default_rng(seed)
    return pd.Series(100 * np.exp(np.cumsum(rng.normal(drift, vol, len(idx)))), index=idx)


@pytest.fixture()
def prices():
    a = _daily("2012-01-02", "2026-10-23", 0.0003, 0.010, 1)
    b = _daily("2012-01-02", "2026-10-23", 0.0002, 0.008, 2)
    z = _daily("2012-01-02", "2026-10-23", 0.0004, 0.012, 9)
    return pd.DataFrame({"A": a, "B": b, "Z": z})


def test_incomplete_current_month_is_excluded(prices):
    out = prepare_returns(prices, as_of="2026-10-23")
    assert out.returns.index[-1] == pd.Timestamp("2026-09-30")
    out_full = prepare_returns(prices, as_of="2026-11-02")
    assert out_full.returns.index[-1] == pd.Timestamp("2026-10-31")


def test_no_fabricated_returns_for_short_history(prices):
    """Il vecchio codice riempiva con bfill: 5 anni di rendimenti identicamente 0."""
    prices["C"] = _daily("2021-10-04", "2026-10-23", 0.0008, 0.018, 3)
    out = prepare_returns(prices, min_years=3, as_of="2026-10-23")
    assert "C" in out.returns and out.returns.index[0] >= pd.Timestamp("2021-10-31")
    assert out.n_months <= 60
    assert (out.returns == 0.0).sum().sum() == 0
    long = prepare_returns(prices, min_years=8, as_of="2026-10-23")
    assert "C" not in long.returns and "storico" in long.dropped["C"]
    assert long.n_months > 150  # senza C si recupera tutta la finestra comune di A e B


def test_common_window_has_no_missing_values(prices):
    prices.loc["2018-03-01":"2018-09-30", "B"] = np.nan  # buco di 7 mesi
    out = prepare_returns(prices, min_years=5, as_of="2026-10-23")
    assert not out.returns.isna().any().any()
    assert "B" in out.dropped and "mancanti" in out.dropped["B"]


def test_short_gaps_are_forward_filled_only(prices):
    prices.loc["2018-03-05":"2018-04-20", "B"] = np.nan  # ~1,5 mesi
    out = prepare_returns(prices, min_years=5, as_of="2026-10-23")
    assert "B" in out.returns


def test_stale_assets_are_dropped(prices):
    prices.loc["2024-01-01":, "B"] = np.nan
    out = prepare_returns(prices, min_years=5, as_of="2026-10-23")
    assert "B" in out.dropped and "aggiornati" in out.dropped["B"]


def test_not_enough_assets_raises_readable_error(prices):
    with pytest.raises(DataError) as exc:
        prepare_returns(prices[["A"]], min_years=5, as_of="2026-10-23")
    assert "almeno 2 asset" in str(exc.value)
    with pytest.raises(DataError):
        prepare_returns(prices.iloc[:100], min_years=5, as_of="2026-10-23")


def test_coverage_table_reports_every_requested_asset(prices):
    prices["C"] = _daily("2025-01-02", "2026-10-23", 0.0, 0.01, 5)
    out = prepare_returns(prices, min_years=5, as_of="2026-10-23")
    cov = out.coverage.set_index("Ticker")
    assert set(cov.index) == {"A", "B", "Z", "C"}
    assert cov.loc["C", "Stato"] == "escluso" and cov.loc["A", "Stato"] == "incluso"


def test_extreme_returns_generate_a_warning(prices):
    prices.loc["2020-05-04":, "A"] *= 0.2  # crollo -80% (tipico errore di split)
    out = prepare_returns(prices, min_years=5, as_of="2026-10-23")
    assert any("50%" in w for w in out.warnings)
    quiet = prepare_returns(prices, min_years=5, as_of="2026-10-23", extreme_move=0.9)
    assert not quiet.warnings, "la soglia dell'avviso è configurabile (gli asset già valutati usano +100%)"


def test_the_window_can_be_capped_to_the_most_recent_years(prices):
    full = prepare_returns(prices, min_years=5, as_of="2026-10-23")
    capped = prepare_returns(prices, min_years=5, as_of="2026-10-23", max_years=10)
    assert full.n_months > 170 and capped.n_months == 120
    assert capped.returns.index[-1] == full.returns.index[-1] and capped.returns.index[0] > full.returns.index[0]
    assert np.allclose(capped.returns.to_numpy(), full.returns.iloc[-120:].to_numpy())
    floor = prepare_returns(prices, min_years=5, as_of="2026-10-23", max_years=3)
    assert floor.n_months == 60, "la finestra non scende mai sotto lo storico minimo richiesto"


# ------------------------------------------------------------------ universi
def test_universes_load():
    etf = load_etf_universe()
    assert etf.Ticker.is_unique and {"Ticker", "Nome", "Categoria", "Gruppo", "Valuta"} <= set(etf.columns)
    stocks = load_stock_universe()
    assert len(stocks) > 3000 and "Shell Companies" not in set(stocks.Industria)
    assert not stocks.Categoria.str.contains("💻|⚕|🏦").any()


def test_clean_label_strips_emoji():
    assert clean_label("💻 Settore Tech & Software") == "Settore Tech & Software"
    assert clean_label("⚕️ Salute & Farmaceutica") == "Salute & Farmaceutica"
