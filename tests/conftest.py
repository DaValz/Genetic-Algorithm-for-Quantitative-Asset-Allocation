"""Fixture condivise dai test."""
import os
import sys
from pathlib import Path

for _var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_var, "1")      # BLAS a un solo thread (come nel Dockerfile): più veloce e senza i crash sporadici
                                          # di OpenBLAS visti su Windows con gli script Streamlit eseguiti in thread

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import pytest  # noqa: E402

os.environ["GOALGA_DEFAULT_LANG"] = "it"      # i test verificano i testi italiani; le altre lingue si attivano in modo esplicito

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from goalga import GoalProblem, build_flows, build_market  # noqa: E402
from goalga.demo import synthetic_monthly_returns  # noqa: E402

PAPER_GOALS = {**{y: 32_000 for y in (10, 11, 12, 13)}, **{y: 40_000 for y in (20, 21, 22, 23)}, 50: 1_900_000}

# (rendimento annuo atteso, volatilità annua, beta sul mercato) di ciascuna classe di fondi dell'archivio sintetico
_FUND_PROFILE = {
    "cash": (0.02, 0.004, 0.0), "govt_bond": (0.035, 0.045, -0.1), "corp_bond": (0.04, 0.055, 0.25),
    "hy_bond": (0.07, 0.085, 0.55), "em_bond": (0.06, 0.08, 0.5), "dev_equity": (0.08, 0.15, 1.0),
    "em_equity": (0.085, 0.18, 1.05), "commodities": (0.03, 0.15, 0.3), "real_estate_fund": (0.065, 0.17, 0.8),
}
_SECTOR_BETA = {"utilities": 0.5, "staples": 0.6, "healthcare": 0.8, "financials": 0.9, "communication": 0.9,
                "real_estate": 1.0, "energy": 1.0, "materials": 1.05, "industrials": 1.15, "technology": 1.25,
                "consumer_cyclical": 1.25}


def build_test_snapshot(path: Path, *, per_sector: int = 24, months: int = 240, end: str = "2026-09-30",
                        seed: int = 5) -> Path:
    """Archivio mensile sintetico con i ticker veri del catalogo: tutti i fondi e alcune azioni per settore.

    Alcuni titoli sono costruiti per provocare i motivi di esclusione (storico breve, dati vecchi, salto anomalo).
    """
    from goalga import snapshot
    from goalga.universe import SECTOR_CATEGORIES, catalog

    table = catalog()
    rng = np.random.default_rng(seed)
    index = pd.date_range(end=end, periods=months, freq="ME")
    market = rng.standard_t(5, months) / np.sqrt(5 / 3) * 0.042 + 0.0058
    market -= market.mean() - 0.0058

    funds = list(table.index[(table["Tipo"] == "fund")])
    eligible = table[(table["Tipo"] == "stock") & (table["Skip"] == "")]
    stocks: list[str] = []
    for sector in SECTOR_CATEGORIES:
        pool = list(eligible.index[eligible["Categoria"] == sector])
        stocks += list(rng.choice(pool, min(len(pool), per_sector), replace=False))
    returns: dict[str, np.ndarray] = {}
    for ticker in funds:
        mu, vol, beta = _FUND_PROFILE.get(str(table.at[ticker, "Categoria"]), (0.05, 0.1, 0.5))
        monthly_vol, mu_m = vol / np.sqrt(12), mu / 12
        idio = np.sqrt(max(monthly_vol**2 - (beta * 0.042) ** 2, (0.2 * monthly_vol) ** 2))
        returns[ticker] = mu_m + beta * (market - market.mean()) + rng.standard_t(6, months) / np.sqrt(2) * idio
    for ticker in stocks:
        beta = _SECTOR_BETA.get(str(table.at[ticker, "Categoria"]), 1.0) * rng.uniform(0.7, 1.3)
        returns[ticker] = 0.006 + beta * (market - market.mean()) + rng.standard_t(6, months) / np.sqrt(2) * 0.06
    frame = pd.DataFrame(returns, index=index).clip(lower=-0.6, upper=0.9)
    prices = 100.0 * (1.0 + frame).cumprod()

    short, stale, jump = stocks[0], stocks[1], stocks[2]       # motivi di esclusione dimostrativi
    prices.loc[prices.index[:months - 72], short] = np.nan     # solo 6 anni di storico
    prices.loc[prices.index[-8:], stale] = np.nan               # ultimo prezzo di 8 mesi fa
    prices.loc[prices.index[-40]:, jump] *= 4.0                 # +300% in un mese
    meta = {"built_at": "2026-10-24T00:00:00+00:00", "currency": "EUR", "n_assets": prices.shape[1]}
    snapshot.save_snapshot(prices, meta, path)
    return path


@pytest.fixture(scope="session")
def snapshot_file(tmp_path_factory):
    return build_test_snapshot(tmp_path_factory.mktemp("prices") / "prices_monthly.parquet")


@pytest.fixture(autouse=True)
def prices_env(monkeypatch, snapshot_file):
    """Tutti i test leggono l'archivio sintetico: nessun accesso alla rete né ai dati reali del progetto."""
    monkeypatch.setenv("GOALGA_PRICES_FILE", str(snapshot_file))
    yield


@pytest.fixture(scope="session")
def monthly_returns():
    return synthetic_monthly_returns(240, seed=7)


@pytest.fixture(scope="session")
def market(monthly_returns):
    return build_market(monthly_returns, max_weight=1.0)


@pytest.fixture()
def small_problem(market):
    """Problema piccolo (T=10, 4 portafogli) con soluzione ottima non banale."""
    sub = market.history[:, [0, 2, 5, 8]]
    rng = np.random.default_rng(3)
    scenarios = sub[rng.integers(0, sub.shape[0], size=(1000, 10))]
    flows = build_flows(20_000, 10, 4_000, last_contribution_year=9, goals={5: 15_000, 10: 60_000})
    return GoalProblem(flows, scenarios, pr_target=0.90, alpha=0.05)
