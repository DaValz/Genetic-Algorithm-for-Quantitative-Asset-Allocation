"""Aggiorna il database di azioni ``data/asset_universe.parquet`` con i dati di Yahoo Finance.

Il programma:

1. recupera i ticker dagli screener predefiniti di Yahoo Finance;
2. aggiunge al database solo i ticker nuovi (quelli già presenti non vengono toccati);
3. completa i metadati mancanti (tipo, settore, industria, exchange, paese, valuta, categoria);
4. salva progressivamente, così un'interruzione non fa perdere il lavoro già svolto.

Esempi::

    python scripts/update_ticker.py
    python scripts/update_ticker.py --screeners most_actives,day_gainers --max-results 500
    python scripts/update_ticker.py --skip-metadata          # solo nuovi ticker, senza chiamate .info
    python scripts/update_ticker.py --db altro.parquet --limit 50
"""
from __future__ import annotations

import argparse
import re
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "asset_universe.parquet"
DEFAULT_SCREENERS = [
    "most_actives", "day_gainers", "day_losers", "aggressive_small_caps",
    "growth_technology_stocks", "undervalued_growth_stocks", "small_cap_gainers",
]
COLUMNS = ["Ticker", "Nome", "Categoria", "Tipo", "Settore", "Industria", "Exchange", "Paese", "Valuta"]

SECTOR_MAP = {
    "Technology": "Settore Tech & Software",
    "Healthcare": "Salute & Farmaceutica",
    "Financial Services": "Finanza & Assicurazioni",
    "Basic Materials": "Materiali (Metallurgico, Minerario, Chimico)",
    "Energy": "Energia & Petrolio",
    "Consumer Cyclical": "Beni Ciclici & Lusso",
    "Consumer Defensive": "Beni di Prima Necessità",
    "Industrials": "Industria & Manifattura",
    "Real Estate": "Immobiliare (REITs)",
    "Utilities": "Utilities & Servizi Pubblici",
    "Communication Services": "Telecomunicazioni & Media",
}


def get_category(quote_type, sector=None, info=None) -> str:
    """Mappa tipo di strumento e settore Yahoo nella categoria mostrata dall'applicazione."""
    kind = str(quote_type or "").upper()
    if kind == "EQUITY":
        return SECTOR_MAP.get(sector, "Azionario (Altro)")
    if kind == "ETF":
        category = (info or {}).get("category")
        return f"ETF: {category}" if category else "ETF & Fondi"
    return {
        "CRYPTOCURRENCY": "Criptovalute", "MUTUALFUND": "Fondi Comuni", "INDEX": "Indici",
        "CURRENCY": "Valute", "FUTURE": "Futures",
    }.get(kind, "Altri Strumenti")


# ------------------------------------------------------------------ 1. screener
def screen_tickers(name: str, max_results: int, batch_size: int = 250, sleep: float = 0.3) -> list[dict]:
    import yfinance as yf

    print(f"\nScreener: {name}")
    rows: list[dict] = []
    seen: set[str] = set()
    offset = 0
    while offset < max_results:
        try:
            quotes = yf.screen(name, offset=offset, size=batch_size).get("quotes", [])
        except Exception as exc:  # rete, rate limit, screener inesistente
            print(f"   errore all'offset {offset}: {exc}")
            break
        fresh = [q for q in quotes if q.get("symbol") and q["symbol"] not in seen]
        if not fresh:  # fine dei risultati o screener che ignora 'offset'
            break
        seen.update(q["symbol"] for q in fresh)
        rows.extend(fresh)
        print(f"   recuperati {len(rows):,} strumenti")
        if len(quotes) < batch_size:
            break
        offset += batch_size
        time.sleep(sleep)
    return rows


def build_universe(screeners: list[str], max_results: int) -> pd.DataFrame:
    records = []
    for name in screeners:
        for q in screen_tickers(name, max_results):
            ticker = str(q["symbol"]).strip().upper()
            records.append({
                "Ticker": ticker, "Nome": q.get("longName") or q.get("shortName") or ticker, "Tipo": "EQUITY",
                "Settore": q.get("sector"), "Industria": q.get("industry"), "Exchange": q.get("exchange"),
                "Paese": q.get("region"), "Valuta": q.get("currency"),
            })
    if not records:
        return pd.DataFrame(columns=COLUMNS)
    return pd.DataFrame(records).drop_duplicates("Ticker").reset_index(drop=True)


# ------------------------------------------------------------------ 2. database
def load_db(path: Path) -> pd.DataFrame:
    if path.exists():
        df = pd.read_parquet(path)
        print(f"Database esistente: {path} ({len(df):,} ticker)")
    else:
        print(f"Database non trovato: verrà creato in {path}")
        df = pd.DataFrame(columns=COLUMNS)
    for col in COLUMNS:
        if col not in df:
            df[col] = None
    df["Ticker"] = df["Ticker"].astype(str).str.upper().str.strip()
    # le categorie storiche contenevano emoji: si uniformano a etichette testuali
    df["Categoria"] = df["Categoria"].map(lambda c: re.sub(r"^[^\w\u00C0-\u00FF]+", "", c).strip() if isinstance(c, str) else c)
    return df


def save_db(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path, engine="pyarrow", index=False)


def merge_new(existing: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    if new.empty:
        print("Nessun ticker recuperato.")
        return existing
    added = new[~new["Ticker"].isin(set(existing["Ticker"]))]
    print(f"Nuovi ticker: {len(added):,} | già presenti: {len(new) - len(added):,}")
    merged = pd.concat([existing, added], ignore_index=True) if len(added) else existing.copy()
    missing_cat = merged["Categoria"].isna()
    merged.loc[missing_cat, "Categoria"] = [
        get_category(t, s) for t, s in zip(merged.loc[missing_cat, "Tipo"], merged.loc[missing_cat, "Settore"], strict=True)
    ]
    return merged.drop_duplicates("Ticker").sort_values("Ticker").reset_index(drop=True)


def missing_metadata_mask(df: pd.DataFrame) -> pd.Series:
    kind = df["Tipo"].fillna("").astype(str).str.upper().str.strip()
    sector = df["Settore"].fillna("").astype(str).str.strip()
    category = df["Categoria"].fillna("").astype(str).str.strip()
    return ((kind == "EQUITY") & (sector == "")) | ((kind != "EQUITY") & ((kind == "") | (category == "")))


def complete_metadata(df: pd.DataFrame, path: Path, sleep: float, save_every: int, limit: int | None) -> pd.DataFrame:
    import yfinance as yf

    todo = df.index[missing_metadata_mask(df)]
    if limit is not None:
        todo = todo[:limit]
    print(f"\nTicker da completare: {len(todo):,}")
    errors = []
    for n, idx in enumerate(todo, start=1):
        ticker = df.at[idx, "Ticker"]
        try:
            info = yf.Ticker(ticker).info
            quote_type, sector = info.get("quoteType"), info.get("sector")
            df.at[idx, "Nome"] = info.get("longName") or info.get("shortName") or ticker
            df.at[idx, "Tipo"] = quote_type
            df.at[idx, "Settore"] = sector
            df.at[idx, "Industria"] = info.get("industry")
            df.at[idx, "Exchange"] = info.get("exchange")
            df.at[idx, "Paese"] = info.get("country") or info.get("region")
            df.at[idx, "Valuta"] = info.get("currency")
            df.at[idx, "Categoria"] = get_category(quote_type, sector, info)
            print(f"[{n}/{len(todo)}] {ticker}: {df.at[idx, 'Categoria']}")
        except Exception as exc:
            print(f"[{n}/{len(todo)}] {ticker}: errore {exc}")
            errors.append({"Ticker": ticker, "Errore": str(exc)})
        if n % save_every == 0:
            save_db(df, path)
        time.sleep(sleep)
    save_db(df, path)
    if errors:
        error_file = path.with_name(path.stem + "_errors.parquet")
        pd.DataFrame(errors).to_parquet(error_file, index=False)
        print(f"\nErrori: {len(errors)} (dettaglio in {error_file})")
    return df


def final_report(df: pd.DataFrame, path: Path) -> None:
    print("\n" + "=" * 70)
    print(f"Totale ticker: {len(df):,} | file: {path}")
    print("\nCategorie:\n" + df["Categoria"].value_counts(dropna=False).to_string())
    print("\nPrime 15 industrie:\n" + df["Industria"].value_counts(dropna=False).head(15).to_string())


# ------------------------------------------------------------------ ingresso
def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="file parquet del database")
    parser.add_argument("--screeners", default=",".join(DEFAULT_SCREENERS), help="screener Yahoo separati da virgola")
    parser.add_argument("--max-results", type=int, default=10_000, help="massimo di risultati per screener")
    parser.add_argument("--skip-metadata", action="store_true", help="non completare i metadati (.info)")
    parser.add_argument("--limit", type=int, default=None, help="completa al massimo N ticker")
    parser.add_argument("--info-sleep", type=float, default=0.15, help="pausa tra le chiamate .info (secondi)")
    parser.add_argument("--save-every", type=int, default=25, help="salvataggio progressivo ogni N ticker")
    args = parser.parse_args()

    print("=" * 70 + "\n  YAHOO FINANCE - ASSET UNIVERSE BUILDER\n" + "=" * 70)
    df = load_db(args.db)
    scraped = build_universe([s.strip() for s in args.screeners.split(",") if s.strip()], args.max_results)
    df = merge_new(df, scraped)
    save_db(df, args.db)
    if not args.skip_metadata:
        df = complete_metadata(df, args.db, args.info_sleep, args.save_every, args.limit)
    final_report(df, args.db)


if __name__ == "__main__":
    main()
