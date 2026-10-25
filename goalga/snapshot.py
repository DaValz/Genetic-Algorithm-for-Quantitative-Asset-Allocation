"""Archivio dei prezzi mensili dell'universo: scarico, conversione in euro e lettura.

L'applicazione non scarica nulla mentre l'utente la usa: i prezzi di tutti gli asset del catalogo sono in un unico
file (``data/prices_monthly.parquet``) rigenerato a intervalli regolari da ``scripts/update_prices.py`` (vedi il
workflow ``update-prices.yml``). Così:

* l'universo completo (migliaia di titoli) è disponibile subito, senza attese né limiti di richieste;
* tutti gli asset sono nella stessa valuta (euro): i rendimenti dei titoli in dollari includono il cambio EUR/USD,
  come li vivrebbe un investitore dell'area euro che non si copre dal rischio di cambio;
* i dati sono riproducibili: stesso file, stesso risultato.

Formato: indice mensile a fine mese, una colonna per ticker, prezzi aggiustati per dividendi e split (rendimento
totale), solo mesi completi.
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Callable, Mapping, Sequence

import pandas as pd

from .data import PriceData
from .i18n import Msg
from .universe import DATA_DIR

SNAPSHOT_FILE = DATA_DIR / "prices_monthly.parquet"
META_FILE = DATA_DIR / "prices_monthly.json"
ENV_FILE = "GOALGA_PRICES_FILE"          # file alternativo (test, sviluppo, distribuzioni con dati propri)
FX_TICKER = "EURUSD=X"                   # dollari per un euro
DEFAULT_YEARS = 20


def month_end_index(index: pd.Index) -> pd.DatetimeIndex:
    """Date delle barre mensili riportate alla fine del mese (le barre di Yahoo sono datate il primo del mese)."""
    stamps = pd.DatetimeIndex(index)
    if stamps.tz is not None:
        stamps = stamps.tz_localize(None)
    return stamps.to_period("M").to_timestamp("M").normalize()


def complete_months(frame: pd.DataFrame, today: pd.Timestamp | None = None) -> pd.DataFrame:
    """Barre mensili riportate a fine mese, senza il mese in corso (incompleto) né date duplicate."""
    out = frame.copy()
    out.index = month_end_index(out.index)
    out = out[~out.index.duplicated(keep="last")].sort_index()
    today = (today or pd.Timestamp.today()).normalize()
    return out[out.index < today]


def _yahoo_monthly(tickers: Sequence[str], start: str) -> pd.DataFrame:
    import yfinance as yf

    raw = yf.download(list(tickers), start=start, interval="1mo", auto_adjust=True, progress=False,
                      threads=len(tickers) > 1)
    if raw is None or raw.empty:
        return pd.DataFrame()
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw.xs("Close", axis=1, level=1)
    else:
        close = raw[["Close"]].copy()
        close.columns = [tickers[0]]
    return close.dropna(axis=1, how="all")


def download_monthly(tickers: Sequence[str], start: str, *, batch: int = 100, retries: int = 3,
                     downloader: Callable[[Sequence[str], str], pd.DataFrame] | None = None,
                     progress: Callable[[int, int], None] | None = None,
                     pause: float = 0.5) -> tuple[pd.DataFrame, list[str]]:
    """Prezzi mensili aggiustati nella valuta di quotazione, a blocchi con nuovi tentativi.

    Restituisce ``(prezzi, ticker senza dati)``: i ticker che dopo i tentativi in blocco restano senza dati
    vengono richiesti uno alla volta prima di essere dichiarati mancanti.
    """
    get = downloader or _yahoo_monthly
    names = list(dict.fromkeys(str(t) for t in tickers))
    frames: list[pd.DataFrame] = []
    missing: list[str] = []
    for i in range(0, len(names), batch):
        pending = names[i:i + batch]
        for attempt in range(retries):
            try:
                close = get(pending, start)
            except Exception:                       # rete, limiti di richieste, risposta non valida
                close = pd.DataFrame()
            if not close.empty:
                frames.append(close)
                pending = [t for t in pending if t not in close.columns]
            if not pending:
                break
            time.sleep(pause * (attempt + 1))
        missing.extend(pending)
        if progress:
            progress(min(i + batch, len(names)), len(names))
    # secondo giro, un ticker per volta, per quelli che il blocco ha perso
    still: list[str] = []
    for ticker in missing:
        try:
            close = get([ticker], start)
        except Exception:
            close = pd.DataFrame()
        if close.empty or ticker not in close.columns:
            still.append(ticker)
        else:
            frames.append(close[[ticker]])
    if not frames:
        return pd.DataFrame(), names
    prices = pd.concat(frames, axis=1)
    return prices.loc[:, ~prices.columns.duplicated()], still


def to_base_currency(prices: pd.DataFrame, currencies: Mapping[str, str], fx: pd.Series) -> pd.DataFrame:
    """Converte in euro i prezzi in dollari (cambio di fine mese); gli altri asset in euro restano invariati.

    Le colonne in una valuta diversa da euro e dollaro vengono scartate: non c'è un cambio con cui convertirle.
    """
    rate = fx.reindex(prices.index).ffill()
    out = {}
    for ticker in prices.columns:
        currency = str(currencies.get(ticker, "USD")).upper()
        if currency == "EUR":
            out[ticker] = prices[ticker]
        elif currency == "USD":
            out[ticker] = prices[ticker] / rate
    return pd.DataFrame(out, index=prices.index)


def build_snapshot(currencies: Mapping[str, str], *, years: int = DEFAULT_YEARS, batch: int = 100, retries: int = 3,
                   downloader: Callable[[Sequence[str], str], pd.DataFrame] | None = None,
                   progress: Callable[[int, int], None] | None = None,
                   today: pd.Timestamp | None = None) -> tuple[pd.DataFrame, dict]:
    """Prezzi mensili in euro di tutti i ticker in ``currencies`` (ticker -> valuta di quotazione) e metadati."""
    today = (today or pd.Timestamp.today()).normalize()
    start = (today - pd.DateOffset(years=int(years) + 1)).date().isoformat()
    get = downloader or _yahoo_monthly
    raw, failed = download_monthly(list(currencies), start, batch=batch, retries=retries, downloader=get,
                                   progress=progress)
    if raw.empty:
        raise RuntimeError("nessun prezzo scaricato")
    fx_raw, _ = download_monthly([FX_TICKER], start, batch=1, retries=retries, downloader=get)
    if fx_raw.empty:
        raise RuntimeError(f"cambio {FX_TICKER} non disponibile")
    raw = complete_months(raw, today)
    fx = complete_months(fx_raw, today)[FX_TICKER]
    prices = to_base_currency(raw, currencies, fx)
    prices = prices.where(prices > 0).dropna(axis=1, how="all")
    cutoff = today - pd.DateOffset(years=int(years))
    prices = prices[prices.index >= cutoff.to_period("M").to_timestamp("M")]
    prices = prices.dropna(axis=1, how="all")
    dropped = sorted(set(currencies) - set(prices.columns) - set(failed))
    meta = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "currency": "EUR", "fx": FX_TICKER, "frequency": "monthly", "adjusted": True,
        "years": int(years), "first": f"{prices.index[0]:%Y-%m}", "last": f"{prices.index[-1]:%Y-%m}",
        "n_assets": int(prices.shape[1]), "n_months": int(prices.shape[0]),
        "requested": len(currencies), "failed": sorted(failed), "dropped": dropped,
    }
    return prices.astype("float32"), meta


def save_snapshot(prices: pd.DataFrame, meta: dict, path: Path | None = None) -> Path:
    """Scrive archivio e metadati in modo atomico (un file a metà non viene mai letto dall'applicazione)."""
    path = Path(path or SNAPSHOT_FILE)
    meta_path = path.with_suffix(".json")
    tmp = path.with_name(path.name + ".tmp")
    prices.astype("float32").to_parquet(tmp, compression="zstd", index=True)
    os.replace(tmp, path)
    tmp_meta = meta_path.with_name(meta_path.name + ".tmp")
    tmp_meta.write_text(json.dumps(meta, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp_meta, meta_path)
    clear_cache()
    return path


def snapshot_path(path: Path | str | None = None) -> Path:
    """Percorso dell'archivio: argomento, poi variabile d'ambiente ``GOALGA_PRICES_FILE``, poi il file del progetto."""
    return Path(path or os.environ.get(ENV_FILE) or SNAPSHOT_FILE)


def available(path: Path | str | None = None) -> bool:
    return snapshot_path(path).exists()


@lru_cache(maxsize=4)
def _read(path: str, mtime_ns: int, size: int) -> pd.DataFrame:
    frame = pd.read_parquet(path)
    frame.index = pd.DatetimeIndex(frame.index).normalize()
    frame.columns = [str(c) for c in frame.columns]
    return frame.astype("float64").sort_index()


def clear_cache() -> None:
    _read.cache_clear()
    _meta.cache_clear()


def load_prices(path: Path | str | None = None) -> pd.DataFrame:
    """Prezzi mensili in euro di tutto l'universo (condivisi tra le sessioni: da trattare come sola lettura)."""
    target = snapshot_path(path)
    if not target.exists():
        raise FileNotFoundError(f"archivio dei prezzi non trovato: {target} (vedi scripts/update_prices.py)")
    stat = target.stat()
    return _read(str(target), stat.st_mtime_ns, stat.st_size)


@lru_cache(maxsize=4)
def _meta(path: str, mtime_ns: int) -> dict:
    sidecar = Path(path).with_suffix(".json")
    if sidecar.exists():
        try:
            return json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
    return {}


def load_meta(path: Path | str | None = None) -> dict:
    """Metadati dell'archivio (data di creazione, periodo, numero di asset); vuoti se mancano."""
    target = snapshot_path(path)
    return _meta(str(target), target.stat().st_mtime_ns) if target.exists() else {}


def snapshot_loader(tickers: Sequence[str], years: int | None = None, *, path: Path | str | None = None) -> PriceData:
    """Prezzi dei ticker richiesti dall'archivio (stessa interfaccia dello scarico: ``(ticker, anni) -> PriceData``)."""
    prices = load_prices(path)
    wanted = list(dict.fromkeys(str(t).upper() for t in tickers))
    present = [t for t in wanted if t in prices.columns]
    failed = {t: Msg("core.data.no_data_returned") for t in wanted if t not in prices.columns}
    frame = prices[present]
    if years:
        frame = frame[frame.index >= frame.index[-1] - pd.DateOffset(years=int(years))]
    return PriceData(frame.dropna(axis=1, how="all"), failed)


def evaluated_count(path: Path | str | None = None) -> int | None:
    """Numero di asset con prezzi nell'archivio (None se l'archivio non c'è)."""
    if not available(path):
        return None
    return int(load_prices(path).notna().any().sum())


def describe(path: Path | str | None = None) -> dict:
    """Riepilogo leggibile dell'archivio: periodo, numero di asset e data di aggiornamento."""
    if not available(path):
        return {}
    prices = load_prices(path)
    meta = dict(load_meta(path))
    meta.setdefault("first", f"{prices.index[0]:%Y-%m}")
    meta.setdefault("last", f"{prices.index[-1]:%Y-%m}")
    meta.setdefault("n_assets", int(prices.shape[1]))
    meta.setdefault("n_months", int(prices.shape[0]))
    return meta
