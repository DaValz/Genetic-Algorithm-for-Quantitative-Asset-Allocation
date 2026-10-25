"""Universo investibile: catalogo di fondi (ETF) e azioni con categorie, esclusioni e ipotesi di rendimento.

Il catalogo unisce due file di dati:

* ``data/etf_universe.csv``: ETF curati per asset class, con il rendimento atteso di lungo periodo (``CMA``);
* ``data/asset_universe.parquet``: azioni, con settore (categoria) e industria.

Ogni asset ha una **categoria** stabile (``technology``, ``govt_bond``...) che l'interfaccia mostra e traduce; gli
strumenti che non sono azioni ordinarie (azioni privilegiate, fondi chiusi, warrant, unit, criptovalute...) restano nel
catalogo, ma con un motivo di esclusione (colonna ``Skip``): vengono *valutati* come tutti gli altri e poi scartati.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ETF_FILE = DATA_DIR / "etf_universe.csv"
STOCK_FILE = DATA_DIR / "asset_universe.parquet"

# selezione di fondi con storico lungo (>= 14 anni) e copertura delle asset class dell'esempio del paper:
# resta il nucleo "difensivo + azionario" per i test e per le specifiche salvate dalle versioni precedenti
DEFAULT_ETF_SELECTION = [
    "XEON.MI", "IBGS.MI", "EUNH.DE", "IEAC.MI", "IHYG.MI", "IEMB.MI",
    "IMEU.AS", "SXR8.DE", "EUNJ.DE", "IEMA.AS",
]

# categorie dei fondi (asset class): etichetta del file CSV -> chiave stabile
FUND_CLASSES: dict[str, str] = {
    "Liquidità": "cash",
    "Obbligazionario governativo": "govt_bond",
    "Obbligazionario corporate": "corp_bond",
    "Obbligazionario high yield": "hy_bond",
    "Obbligazionario emergenti": "em_bond",
    "Azionario sviluppato": "dev_equity",
    "Azionario emergente": "em_equity",
    "Oro e materie prime": "commodities",
    "Immobiliare": "real_estate_fund",
}
# categorie delle azioni (settori): etichetta del database (senza emoji) -> chiave stabile
STOCK_SECTORS: dict[str, str] = {
    "Finanza & Assicurazioni": "financials",
    "Settore Tech & Software": "technology",
    "Salute & Farmaceutica": "healthcare",
    "Industria & Manifattura": "industrials",
    "Beni Ciclici & Lusso": "consumer_cyclical",
    "Immobiliare (REITs)": "real_estate",
    "Energia & Petrolio": "energy",
    "Telecomunicazioni & Media": "communication",
    "Materiali (Metallurgico, Minerario, Chimico)": "materials",
    "Beni di Prima Necessità": "staples",
    "Utilities & Servizi Pubblici": "utilities",
}
FUND_CATEGORIES = tuple(FUND_CLASSES.values())
SECTOR_CATEGORIES = tuple(STOCK_SECTORS.values())
CATEGORIES = FUND_CATEGORIES + SECTOR_CATEGORIES
CATEGORY_KIND = {**{c: "fund" for c in FUND_CATEGORIES}, **{c: "stock" for c in SECTOR_CATEGORIES}}

# motivi per cui uno strumento del database non viene usato (azioni ordinarie soltanto)
SKIP_REASONS = ("preferred", "fund", "warrant", "misc", "crypto")

_LEADING_SYMBOLS = re.compile(r"^[^\wÀ-ÿ]+")
_PREFERRED = re.compile(r"-P[A-Z]{0,2}$")                   # azioni privilegiate (ABR-PD)
_WARRANT_UNIT = re.compile(r"-(?:W[A-Z]{0,2}|U[N]?|R[T]?)$")  # warrant, unit e diritti con suffisso
_SHORT_SUFFIX = re.compile(r"^[A-Z]{4}[WRU]$")              # warrant, diritti e unit del Nasdaq (5 lettere)
# fondi chiusi: i listini li classificano come azioni di «Asset Management» ma sono fondi (obbligazionari municipali,
# a reddito, buy-write...); «Trust» seguito da Corporation/Company è invece una società operativa (Northern Trust)
_FUND_NAME = re.compile(r"\b(?:Funds?|Trusts?)\b|\bMuni\w*", re.I)
_OPERATING_TRUST = re.compile(r"\bTrust\b\W*(?:Corporation|Corp|Company|Co)\b", re.I)


def clean_label(text: object) -> str:
    """Rimuove emoji/simboli iniziali dalle etichette di categoria."""
    return _LEADING_SYMBOLS.sub("", str(text)).strip()


def load_etf_universe(path: Path = ETF_FILE) -> pd.DataFrame:
    """Universo curato di ETF per asset class; ``CMA`` è il rendimento atteso di lungo periodo."""
    df = pd.read_csv(path, dtype=str).fillna("")
    df["Ticker"] = df["Ticker"].str.strip().str.upper()
    df["CMA"] = pd.to_numeric(df["CMA"], errors="coerce")
    return df.drop_duplicates("Ticker").reset_index(drop=True)


def load_stock_universe(path: Path = STOCK_FILE) -> pd.DataFrame:
    """Carica il database di azioni; restituisce un DataFrame vuoto se il file non esiste."""
    columns = ["Ticker", "Nome", "Categoria", "Tipo", "Settore", "Industria", "Exchange", "Paese", "Valuta"]
    if not Path(path).exists():
        return pd.DataFrame(columns=columns)
    df = pd.read_parquet(path)
    for col in columns:
        if col not in df:
            df[col] = ""
    df = df[columns].fillna("")
    df["Ticker"] = df["Ticker"].astype(str).str.strip().str.upper()
    df["Categoria"] = df["Categoria"].map(clean_label)
    # le società "shell" (SPAC) non sono investibili in modo significativo
    df = df[df["Industria"] != "Shell Companies"]
    return df.drop_duplicates("Ticker").sort_values("Ticker").reset_index(drop=True)


def _is_closed_end_fund(name: object, industry: object) -> bool:
    """True per i fondi chiusi (e i trust di investimento) che i listini classificano come azioni di gestione patrimoniale."""
    text = str(name)
    return industry == "Asset Management" and bool(_FUND_NAME.search(text)) and not _OPERATING_TRUST.search(text)


def _skip_reason(row) -> str:
    """Motivo per cui un'azione del database non è investibile come azione ordinaria ('' se lo è)."""
    ticker = row.Ticker
    if row.Tipo == "CRYPTOCURRENCY":
        return "crypto"
    if row.Tipo != "EQUITY" or row.Categoria not in STOCK_SECTORS:
        return "misc"                                       # ETF isolati, "Azionario (Altro)": privilegiate e warrant non classificati
    if _PREFERRED.search(ticker):
        return "preferred"
    if _is_closed_end_fund(getattr(row, "Nome", ""), getattr(row, "Industria", "")):
        return "fund"
    if _WARRANT_UNIT.search(ticker) or _SHORT_SUFFIX.match(ticker):
        return "warrant"
    return ""


@lru_cache(maxsize=1)
def catalog() -> pd.DataFrame:
    """Catalogo completo (indice ``Ticker``): fondi e azioni con categoria, valuta e motivo di esclusione.

    Colonne: ``Nome``, ``Tipo`` (``fund``/``stock``), ``Categoria`` (chiave stabile), ``Gruppo`` (solo fondi),
    ``Industria``, ``Paese``, ``Valuta``, ``CMA`` (solo fondi) e ``Skip`` (motivo di esclusione o stringa vuota).
    Da trattare come sola lettura: è condiviso.
    """
    etf = load_etf_universe()
    funds = pd.DataFrame({
        "Ticker": etf["Ticker"], "Nome": etf["Nome"], "Tipo": "fund",
        "Categoria": etf["Categoria"].map(FUND_CLASSES).fillna("other"), "Gruppo": etf["Gruppo"],
        "Industria": "", "Paese": "", "Valuta": etf["Valuta"].replace("", "EUR"), "CMA": etf["CMA"], "Skip": "",
    })
    stocks = load_stock_universe()
    stocks = stocks[~stocks["Ticker"].isin(funds["Ticker"])]            # SPY compare in entrambi i file: vale il fondo curato
    rows = pd.DataFrame({
        "Ticker": stocks["Ticker"], "Nome": stocks["Nome"], "Tipo": "stock",
        "Categoria": stocks["Categoria"].map(STOCK_SECTORS).fillna("other"), "Gruppo": "",
        "Industria": stocks["Industria"], "Paese": stocks["Paese"], "Valuta": stocks["Valuta"].replace("", "USD"),
        "CMA": np.nan, "Skip": [_skip_reason(r) for r in stocks.itertuples()],
    })
    table = pd.concat([funds, rows], ignore_index=True)
    return table.set_index("Ticker")


def investable_tickers() -> list[str]:
    """Ticker degli strumenti investibili (fondi e azioni ordinarie): quelli di cui servono i prezzi."""
    table = catalog()
    return table.index[table["Skip"] == ""].tolist()


def universe_cmas(tickers) -> dict[str, float]:
    """Rendimenti attesi di lungo periodo (ipotesi di default) disponibili per i ticker dati."""
    cma = catalog()["CMA"]
    return {t: float(cma[t]) for t in tickers if t in cma.index and pd.notna(cma[t])}


def universe_names(tickers) -> dict[str, str]:
    """Nomi leggibili di ETF e azioni del database (il ticker stesso se sconosciuto)."""
    names = catalog()["Nome"]
    return {t: (str(names[t]) if t in names.index else t) for t in tickers}


def universe_size() -> int:
    """Numero di asset a disposizione nel database (ETF curati + azioni): tutti vengono valutati."""
    return len(catalog())


def class_defaults() -> dict[str, float]:
    """Rendimento atteso di lungo periodo medio di ciascuna classe di fondi (ipotesi di partenza)."""
    table = catalog()
    funds = table[(table["Tipo"] == "fund") & table["CMA"].notna()]
    return {k: float(v) for k, v in funds.groupby("Categoria")["CMA"].mean().items()}


RISK_FREE_FALLBACK = 0.020
EQUITY_PREMIUM_FALLBACK = 0.058
EQUITY_ANCHOR = "SXR8.DE"        # S&P 500: ancora del premio per il rischio azionario


def risk_free_default() -> float:
    """Tasso privo di rischio di partenza: ipotesi di lungo periodo della liquidità."""
    return float(class_defaults().get("cash", RISK_FREE_FALLBACK))


def equity_premium_default() -> float:
    """Premio per il rischio azionario di partenza: ipotesi dell'S&P 500 meno il tasso privo di rischio."""
    table = catalog()
    if EQUITY_ANCHOR in table.index and pd.notna(table.at[EQUITY_ANCHOR, "CMA"]):
        return float(table.at[EQUITY_ANCHOR, "CMA"]) - risk_free_default()
    return EQUITY_PREMIUM_FALLBACK
