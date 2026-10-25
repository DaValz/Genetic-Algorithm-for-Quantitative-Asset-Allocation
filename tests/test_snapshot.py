"""Test dell'archivio mensile dei prezzi: scarico a blocchi, conversione in euro, scrittura atomica e lettura."""
import numpy as np
import pandas as pd
import pytest

from goalga import snapshot
from goalga.i18n import render

TODAY = pd.Timestamp("2026-10-24")


def bars(tickers, start="2025-01-01", months=22, seed=0):
    """Barre mensili datate il primo del mese (come le restituisce il fornitore dei dati)."""
    index = pd.date_range(start, periods=months, freq="MS")
    rng = np.random.default_rng(seed)
    return pd.DataFrame({t: 100.0 * np.cumprod(1 + rng.normal(0.008, 0.02, months)) for t in tickers}, index=index)


class Feed:
    """Fornitore dati finto: restituisce le colonne richieste che possiede, con guasti e ritardi programmabili."""

    def __init__(self, frame, *, flaky_first=False, late=None):
        self.frame, self.flaky_first, self.late = frame, flaky_first, dict(late or {})
        self.calls: list[list[str]] = []

    def __call__(self, tickers, start):
        self.calls.append(list(tickers))
        if self.flaky_first and len(self.calls) == 1:
            raise ConnectionError("rete assente")
        cols = [t for t in tickers if t in self.frame.columns and len(self.calls) > self.late.get(t, 0)]
        return self.frame[cols]


# ------------------------------------------------------------------ date
def test_monthly_bars_are_moved_to_the_end_of_the_month():
    index = pd.DatetimeIndex(["2026-01-01", "2026-02-01"], tz="UTC")
    assert list(snapshot.month_end_index(index)) == [pd.Timestamp("2026-01-31"), pd.Timestamp("2026-02-28")]
    assert snapshot.month_end_index(pd.DatetimeIndex(["2026-03-01"])).tz is None


def test_the_current_month_and_duplicate_bars_are_dropped():
    frame = bars(["A"], start="2026-07-01", months=4)                 # luglio, agosto, settembre, ottobre (in corso)
    extra = pd.DataFrame({"A": [999.0]}, index=pd.DatetimeIndex(["2026-09-15"]))   # seconda barra di settembre
    out = snapshot.complete_months(pd.concat([frame, extra]).sort_index(), TODAY)
    assert list(out.index) == [pd.Timestamp("2026-07-31"), pd.Timestamp("2026-08-31"), pd.Timestamp("2026-09-30")]
    assert out.loc["2026-09-30", "A"] == 999.0, "di due barre dello stesso mese resta l'ultima"


# ------------------------------------------------------------------ scarico
def test_download_goes_in_blocks_and_reports_the_tickers_without_data():
    feed = Feed(bars(["A", "B", "C", "D"]))
    prices, failed = snapshot.download_monthly(["A", "B", "C", "D", "BAD"], "2024-01-01", batch=2, retries=2,
                                               downloader=feed, pause=0)
    assert list(prices.columns) == ["A", "B", "C", "D"] and failed == ["BAD"]
    assert all(len(call) <= 2 for call in feed.calls)


def test_a_transient_failure_is_retried():
    feed = Feed(bars(["A", "B"]), flaky_first=True)
    prices, failed = snapshot.download_monthly(["A", "B"], "2024-01-01", batch=10, retries=3, downloader=feed, pause=0)
    assert list(prices.columns) == ["A", "B"] and failed == [] and len(feed.calls) == 2


def test_tickers_lost_by_the_block_are_asked_again_one_by_one():
    feed = Feed(bars(["A", "SLOW"]), late={"SLOW": 3})                 # risponde solo dalla quarta richiesta
    prices, failed = snapshot.download_monthly(["A", "SLOW"], "2024-01-01", batch=5, retries=3, downloader=feed, pause=0)
    assert set(prices.columns) == {"A", "SLOW"} and failed == []
    assert feed.calls[-1] == ["SLOW"], "l'ultimo giro è un ticker per volta"


def test_progress_is_reported_per_block():
    seen = []
    snapshot.download_monthly(["A", "B", "C"], "2024-01-01", batch=2, downloader=Feed(bars(["A", "B", "C"])), pause=0,
                              progress=lambda done, total: seen.append((done, total)))
    assert seen == [(2, 3), (3, 3)]


def test_nothing_downloaded_is_reported_as_all_failed():
    prices, failed = snapshot.download_monthly(["X", "Y"], "2024-01-01", downloader=Feed(bars(["A"])), retries=1, pause=0)
    assert prices.empty and failed == ["X", "Y"]


# ------------------------------------------------------------------ valuta
def test_dollar_prices_are_converted_to_euro_and_unknown_currencies_are_dropped():
    index = pd.date_range("2026-01-31", periods=3, freq="ME")
    prices = pd.DataFrame({"EUR1": [10.0, 11.0, 12.0], "US1": [110.0, 121.0, 132.0], "GBP1": [1.0, 2.0, 3.0]}, index=index)
    fx = pd.Series([1.10, 1.10, 1.20], index=index)                     # dollari per un euro
    out = snapshot.to_base_currency(prices, {"EUR1": "EUR", "US1": "USD", "GBP1": "GBP"}, fx)
    assert list(out.columns) == ["EUR1", "US1"]
    assert out["EUR1"].tolist() == [10.0, 11.0, 12.0]
    assert out["US1"].tolist() == pytest.approx([100.0, 110.0, 110.0])


def test_a_missing_fx_month_uses_the_previous_rate():
    index = pd.date_range("2026-01-31", periods=3, freq="ME")
    prices = pd.DataFrame({"US1": [110.0, 110.0, 110.0]}, index=index)
    fx = pd.Series([1.10, np.nan, 1.10], index=index)
    assert snapshot.to_base_currency(prices, {"US1": "USD"}, fx)["US1"].tolist() == pytest.approx([100.0] * 3)


# ------------------------------------------------------------------ costruzione
def test_build_snapshot_converts_to_euro_and_documents_what_was_lost():
    frame = bars(["EUR1", "US1", "GBP1"])
    frame[snapshot.FX_TICKER] = np.linspace(1.05, 1.15, len(frame))
    prices, meta = snapshot.build_snapshot({"EUR1": "EUR", "US1": "USD", "GBP1": "GBP", "BAD": "USD"}, years=5,
                                           downloader=Feed(frame), today=TODAY)
    assert prices.dtypes.eq("float32").all() and list(prices.columns) == ["EUR1", "US1"]
    assert prices.index[-1] == pd.Timestamp("2026-09-30"), "il mese in corso non entra"
    assert prices.loc["2025-01-31", "US1"] == pytest.approx(frame.loc["2025-01-01", "US1"] / frame.loc["2025-01-01", snapshot.FX_TICKER],
                                                            rel=1e-5)
    assert meta["currency"] == "EUR" and meta["n_assets"] == 2 and meta["requested"] == 4
    assert meta["failed"] == ["BAD"] and meta["dropped"] == ["GBP1"]
    assert meta["first"] == "2025-01" and meta["last"] == "2026-09" and meta["n_months"] == len(prices)


def test_build_snapshot_keeps_only_the_requested_years():
    frame = bars(["EUR1"], start="2020-01-01", months=82)              # da gennaio 2020 a ottobre 2026 (in corso)
    frame[snapshot.FX_TICKER] = 1.1
    prices, _ = snapshot.build_snapshot({"EUR1": "EUR"}, years=2, downloader=Feed(frame), today=TODAY)
    assert prices.index[0] >= pd.Timestamp("2024-10-31") and prices.index[-1] == pd.Timestamp("2026-09-30")


def test_build_snapshot_fails_loudly_without_prices_or_without_the_exchange_rate():
    with pytest.raises(RuntimeError):
        snapshot.build_snapshot({"A": "EUR"}, downloader=Feed(bars(["B"])), today=TODAY, retries=1)
    with pytest.raises(RuntimeError, match=snapshot.FX_TICKER):
        snapshot.build_snapshot({"A": "EUR"}, downloader=Feed(bars(["A"])), today=TODAY, retries=1)


# ------------------------------------------------------------------ file
@pytest.fixture()
def saved(tmp_path):
    index = pd.date_range("2024-01-31", periods=36, freq="ME")
    prices = pd.DataFrame({"AAA": np.linspace(100, 150, 36), "BBB": np.linspace(50, 40, 36)}, index=index)
    path = snapshot.save_snapshot(prices, {"built_at": "2026-10-24T00:00:00+00:00", "n_assets": 2}, tmp_path / "p.parquet")
    return path, prices


def test_the_archive_round_trips_without_leaving_temporary_files(saved):
    path, prices = saved
    assert path.exists() and path.with_suffix(".json").exists()
    assert not list(path.parent.glob("*.tmp")), "scrittura atomica: nessun file a metà"
    loaded = snapshot.load_prices(path)
    assert loaded.shape == prices.shape and list(loaded.columns) == ["AAA", "BBB"]
    assert np.allclose(loaded.to_numpy(), prices.to_numpy(), rtol=1e-6) and loaded.dtypes.eq("float64").all()
    assert snapshot.load_meta(path)["built_at"].startswith("2026-10-24") and snapshot.evaluated_count(path) == 2


def test_a_new_archive_at_the_same_path_replaces_the_cached_one(saved):
    path, prices = saved
    assert snapshot.load_prices(path)["AAA"].iloc[-1] == pytest.approx(150.0)
    snapshot.save_snapshot(prices * 2, {"n_assets": 2}, path)
    assert snapshot.load_prices(path)["AAA"].iloc[-1] == pytest.approx(300.0)


def test_the_archive_is_shared_read_only_data_loaded_once(saved):
    path, _ = saved
    assert snapshot.load_prices(path) is snapshot.load_prices(path)


def test_missing_archive_is_reported_clearly(tmp_path):
    missing = tmp_path / "nope.parquet"
    assert not snapshot.available(missing) and snapshot.describe(missing) == {} and snapshot.evaluated_count(missing) is None
    with pytest.raises(FileNotFoundError, match="update_prices"):
        snapshot.load_prices(missing)


def test_the_archive_location_can_be_overridden_with_an_environment_variable(saved, monkeypatch, tmp_path):
    path, _ = saved
    monkeypatch.setenv(snapshot.ENV_FILE, str(path))
    assert snapshot.snapshot_path() == path and snapshot.available()
    other = tmp_path / "other.parquet"
    assert snapshot.snapshot_path(other) == other, "l'argomento ha la precedenza"
    monkeypatch.delenv(snapshot.ENV_FILE)
    assert snapshot.snapshot_path() == snapshot.SNAPSHOT_FILE


def test_describe_completes_the_metadata_from_the_data(saved, tmp_path):
    path, prices = saved
    bare = snapshot.save_snapshot(prices, {}, tmp_path / "bare.parquet")
    info = snapshot.describe(bare)
    assert info["first"] == "2024-01" and info["last"] == "2026-12" and info["n_assets"] == 2 and info["n_months"] == 36


def test_loader_returns_the_requested_tickers_and_reports_the_missing_ones(saved):
    path, _ = saved
    data = snapshot.snapshot_loader(["aaa", "ZZZ"], path=path)
    assert list(data.prices.columns) == ["AAA"] and set(data.failed) == {"ZZZ"}
    assert render(data.failed["ZZZ"])


def test_loader_keeps_only_the_last_years(saved):
    path, _ = saved
    frame = snapshot.snapshot_loader(["AAA"], years=1, path=path).prices
    assert len(frame) == 13 and frame.index[-1] == pd.Timestamp("2026-12-31")


def test_the_real_archive_of_the_project_is_in_euro_and_covers_the_catalog():
    from goalga.universe import catalog
    if not snapshot.SNAPSHOT_FILE.exists():
        pytest.skip("archivio dei prezzi non generato")
    info = snapshot.describe(snapshot.SNAPSHOT_FILE)
    assert info["currency"] == "EUR" and info["n_assets"] > 2500 and info["n_months"] >= 120
    prices = snapshot.load_prices(snapshot.SNAPSHOT_FILE)
    assert set(prices.columns) <= set(catalog().index), "ogni colonna è un asset del catalogo"
    assert {"SPY", "XEON.MI", "AAPL"} <= set(prices.columns)
