"""Test del catalogo: fondi e azioni con categorie, motivi di esclusione e ipotesi di rendimento di partenza."""
from collections import namedtuple

import pandas as pd
import pytest

from goalga import universe as uni
from goalga.universe import (
    CATEGORIES,
    CATEGORY_KIND,
    FUND_CATEGORIES,
    SECTOR_CATEGORIES,
    SKIP_REASONS,
    catalog,
    class_defaults,
    clean_label,
    equity_premium_default,
    investable_tickers,
    risk_free_default,
    universe_cmas,
    universe_names,
    universe_size,
)

Row = namedtuple("Row", "Ticker Tipo Categoria Nome Industria", defaults=("", ""))
AM = "Asset Management"


def test_catalog_has_unique_tickers_and_the_documented_columns():
    table = catalog()
    assert table.index.is_unique and table.index.name == "Ticker"
    assert {"Nome", "Tipo", "Categoria", "Gruppo", "Industria", "Paese", "Valuta", "CMA", "Skip"} <= set(table.columns)
    assert set(table["Tipo"]) == {"fund", "stock"}
    assert set(table["Skip"]) <= {"", *SKIP_REASONS}
    assert universe_size() == len(table) >= 3400, "migliaia di asset a disposizione dell'algoritmo"


def test_every_fund_has_a_category_a_currency_and_a_long_term_return_assumption():
    funds = catalog().query("Tipo == 'fund'")
    assert len(funds) >= 39 and set(funds["Categoria"]) == set(FUND_CATEGORIES), "tutte le asset class sono coperte"
    assert funds["CMA"].notna().all() and funds["CMA"].between(0.0, 0.12).all()
    assert set(funds["Valuta"]) <= {"EUR", "USD"} and (funds["Skip"] == "").all()


def test_ordinary_stocks_belong_to_one_of_the_eleven_sectors():
    stocks = catalog().query("Tipo == 'stock' and Skip == ''")
    assert len(stocks) > 2500 and set(stocks["Categoria"]) == set(SECTOR_CATEGORIES)
    assert stocks["CMA"].isna().all(), "per le azioni il rendimento atteso si stima (CAPM), non si assume"


def test_categories_are_stable_keys_with_a_kind():
    assert len(FUND_CATEGORIES) == 9 and len(SECTOR_CATEGORIES) == 11 and len(set(CATEGORIES)) == 20
    assert all(CATEGORY_KIND[c] == "fund" for c in FUND_CATEGORIES) and all(CATEGORY_KIND[c] == "stock" for c in SECTOR_CATEGORIES)


def test_instruments_that_are_not_ordinary_shares_are_kept_but_flagged():
    table = catalog()
    for reason in SKIP_REASONS:
        assert (table["Skip"] == reason).any(), reason
    assert table.at["BTC-USD", "Skip"] == "crypto" and table.at["ABR-PD", "Skip"] == "preferred"
    assert table.at["BTSGU", "Skip"] == "warrant"
    investable = investable_tickers()
    assert "AAPL" in investable and "XEON.MI" in investable and "ABR-PD" not in investable and "BTC-USD" not in investable
    assert len(investable) == int((table["Skip"] == "").sum())


def test_closed_end_funds_are_not_counted_as_financial_stocks():
    """Metà dei titoli «finanziari» dei listini sono fondi chiusi (municipali, a reddito, buy-write): non sono azioni."""
    table = catalog()
    assert (table["Skip"] == "fund").sum() > 200
    for ticker in ("BBN", "BHK", "GAB", "VKQ", "ETB"):                 # BlackRock, Gabelli, Invesco, Eaton Vance
        assert table.at[ticker, "Skip"] == "fund", ticker
    for ticker in ("BLK", "TROW", "NTRSO", "ARCC", "APO", "AMP"):      # gestori e società operative restano azioni
        assert table.at[ticker, "Skip"] == "", ticker
    financials = table[(table["Tipo"] == "stock") & (table["Categoria"] == "financials") & (table["Skip"] == "")]
    assert not financials["Nome"].str.contains(r"\bMunicipal\b|\bFund\b", regex=True).any()


@pytest.mark.parametrize("ticker, kind, category, name, industry, expected", [
    ("AAPL", "EQUITY", "Settore Tech & Software", "Apple Inc.", "Consumer Electronics", ""),
    ("ABR-PD", "EQUITY", "Finanza & Assicurazioni", "Arbor Realty Trust", "REIT - Mortgage", "preferred"),
    ("XYZ-PRA", "EQUITY", "Finanza & Assicurazioni", "", "", "preferred"),
    ("ABCD-WT", "EQUITY", "Settore Tech & Software", "", "", "warrant"),
    ("ABC-U", "EQUITY", "Settore Tech & Software", "", "", "warrant"),
    ("ABC-UN", "EQUITY", "Settore Tech & Software", "", "", "warrant"),
    ("ABCDW", "EQUITY", "Settore Tech & Software", "", "", "warrant"),
    ("BRK-B", "EQUITY", "Finanza & Assicurazioni", "Berkshire Hathaway Inc.", "Insurance - Diversified", ""),
    ("BTC-USD", "CRYPTOCURRENCY", "Altro", "", "", "crypto"),
    ("QQQ", "ETF", "Azionario (Altro)", "", "", "misc"),
    ("ZZZ", "EQUITY", "Azionario (Altro)", "", "", "misc"),
    ("BHK", "EQUITY", "Finanza & Assicurazioni", "BlackRock Core Bond Trust", AM, "fund"),
    ("ETB", "EQUITY", "Finanza & Assicurazioni", "Eaton Vance Tax-Managed Buy-Write Income Fund", AM, "fund"),
    ("RMT", "EQUITY", "Finanza & Assicurazioni", "Royce Micro-Cap Trust, Inc.", AM, "fund"),
    ("LEO", "EQUITY", "Finanza & Assicurazioni", "BNY Mellon Strategic Municipals, Inc.", AM, "fund"),
    ("NTRSO", "EQUITY", "Finanza & Assicurazioni", "Northern Trust Corporation", AM, ""),
    ("BLK", "EQUITY", "Finanza & Assicurazioni", "BlackRock, Inc.", AM, ""),
    ("AAT", "EQUITY", "Immobiliare (REITs)", "American Assets Trust, Inc.", "REIT - Diversified", ""),
    ("PBT", "EQUITY", "Energia & Petrolio", "Permian Basin Royalty Trust", "Oil & Gas E&P", ""),
])
def test_skip_reasons(ticker, kind, category, name, industry, expected):
    assert uni._skip_reason(Row(ticker, kind, category, name, industry)) == expected


def test_labels_lose_their_leading_emoji():
    assert clean_label("💊 Salute & Farmaceutica") == "Salute & Farmaceutica"
    assert clean_label("Liquidità") == "Liquidità" and clean_label("  ⚡ Energia & Petrolio ") == "Energia & Petrolio"


def test_default_assumptions_per_class_are_the_mean_of_the_curated_funds():
    defaults = class_defaults()
    assert set(defaults) == set(FUND_CATEGORIES)
    assert defaults["cash"] < defaults["govt_bond"] < defaults["dev_equity"] < defaults["em_equity"]
    assert risk_free_default() == pytest.approx(defaults["cash"])
    table = catalog()
    mean = table[(table["Tipo"] == "fund") & (table["Categoria"] == "dev_equity")]["CMA"].mean()
    assert defaults["dev_equity"] == pytest.approx(mean)


def test_equity_premium_is_the_sp500_assumption_over_the_risk_free_rate():
    premium = equity_premium_default()
    assert 0.04 < premium < 0.07
    assert premium == pytest.approx(catalog().at[uni.EQUITY_ANCHOR, "CMA"] - risk_free_default())


def test_names_and_assumptions_lookup_ignore_unknown_tickers():
    names = universe_names(["AAPL", "XEON.MI", "NOPE"])
    assert names["AAPL"] == "Apple Inc." and names["XEON.MI"].startswith("Xtrackers") and names["NOPE"] == "NOPE"
    cma = universe_cmas(["XEON.MI", "AAPL", "NOPE"])
    assert set(cma) == {"XEON.MI"} and cma["XEON.MI"] == pytest.approx(0.02), "le azioni non hanno un'ipotesi curata"


def test_spy_appears_once_and_as_the_curated_fund():
    table = catalog()
    assert table.index.tolist().count("SPY") == 1 and table.at["SPY", "Tipo"] == "fund"
    assert table.at["SPY", "Categoria"] == "dev_equity"


def test_missing_stock_database_leaves_the_curated_funds(tmp_path):
    empty = uni.load_stock_universe(tmp_path / "missing.parquet")
    assert isinstance(empty, pd.DataFrame) and empty.empty and "Ticker" in empty.columns
