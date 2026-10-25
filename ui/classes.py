"""Asset class "macro" per presentare in modo semplice la composizione del portafoglio."""
from __future__ import annotations

import pandas as pd

from goalga.i18n import t
from goalga.universe import catalog

# chiavi stabili (indipendenti dalla lingua); i nomi mostrati sono nel catalogo («class.<chiave>»)
MACRO_ORDER = ["cash", "bonds", "equity", "commodities", "realestate", "other"]
MACRO_COLORS = {
    "cash": "#94A3B8", "bonds": "#38BDF8", "equity": "#A78BFA",
    "commodities": "#FBBF24", "realestate": "#FB7185", "other": "#64748B",
}
# categoria del catalogo -> macro asset class (le azioni singole, di qualunque settore, sono azionario)
_FUND_MACRO = {
    "cash": "cash", "govt_bond": "bonds", "corp_bond": "bonds", "hy_bond": "bonds", "em_bond": "bonds",
    "dev_equity": "equity", "em_equity": "equity", "commodities": "commodities", "real_estate_fund": "realestate",
}


def label(key: str) -> str:
    return t(f"class.{key}")


def category_key(ticker: str) -> str:
    """Categoria di presentazione: classe del fondo, ``stocks`` per le azioni singole, ``other`` se sconosciuto."""
    table = catalog()
    if ticker not in table.index:
        return "other"
    return "stocks" if table.at[ticker, "Tipo"] == "stock" else str(table.at[ticker, "Categoria"])


def category_label(ticker: str) -> str:
    """Nome della categoria di un asset: classe del fondo oppure settore dell'azione (altrimenti la macro asset class)."""
    table = catalog()
    if ticker in table.index:
        return t(f"cat.{table.at[ticker, 'Categoria']}")
    return label(asset_class_map([ticker]).get(ticker, "other"))


def asset_class_map(tickers: list[str]) -> dict[str, str]:
    """Macro asset class di ciascun ticker del catalogo (fondi e azioni singole); gli sconosciuti sono «other»."""
    table = catalog()
    out: dict[str, str] = {}
    for ticker in tickers:
        if ticker in table.index:
            row = table.loc[ticker]
            out[ticker] = "equity" if row["Tipo"] == "stock" else _FUND_MACRO.get(str(row["Categoria"]), "other")
        else:
            out[ticker] = "other"
    return out


def macro_composition(composition: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    """Pesi per macro asset class (anni x classi), solo le classi presenti, nell'ordine standard."""
    grouped = composition.T.groupby(lambda ticker: mapping.get(ticker, "other")).sum().T
    cols = [c for c in MACRO_ORDER if c in grouped.columns]
    return grouped[cols]
