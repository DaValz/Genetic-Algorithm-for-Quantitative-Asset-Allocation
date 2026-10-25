"""Pulizia dei dati di mercato: dai prezzi mensili ai rendimenti sulla finestra comune.

I prezzi arrivano dall'archivio dell'universo (``goalga.snapshot``). Regole della pulizia:

* nessun ``bfill`` né ``fillna(0)``: lo storico mancante non viene mai inventato;
* si lavora su rendimenti **mensili** a fine mese (centinaia di osservazioni invece di ~10 annuali);
* si usa la finestra storica **comune** a tutti gli asset; gli asset con storico insufficiente
  vengono esclusi e il motivo viene riportato all'utente;
* il mese in corso (incompleto) non entra mai nei rendimenti;
* i prezzi sono aggiustati per dividendi e split (rendimento totale).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .i18n import LocalizedError, Msg


class DataError(LocalizedError):
    """Errore di dati con messaggio già leggibile dall'utente (traducibile: vedi ``goalga.i18n``)."""


@dataclass
class PriceData:
    prices: pd.DataFrame
    failed: dict[str, str] = field(default_factory=dict)


@dataclass
class PreparedReturns:
    returns: pd.DataFrame                     # rendimenti mensili, finestra comune, senza NaN
    coverage: pd.DataFrame                    # una riga per asset richiesto (stato e motivo)
    dropped: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def n_months(self) -> int:
        return int(self.returns.shape[0])

    @property
    def window(self) -> tuple[pd.Timestamp, pd.Timestamp]:
        return self.returns.index[0], self.returns.index[-1]


# --------------------------------------------------------------------------------------
# Pulizia -> rendimenti mensili
# --------------------------------------------------------------------------------------
def prepare_returns(
    prices: pd.DataFrame,
    *,
    min_years: float = 5.0,
    as_of: pd.Timestamp | str | None = None,
    max_gap_months: int = 2,
    stale_months: int = 3,
    extreme_move: float = 0.5,
    max_years: float | None = None,
) -> PreparedReturns:
    """Trasforma i prezzi in rendimenti mensili sulla finestra comune a tutti gli asset utilizzabili.

    ``extreme_move``: variazione mensile (in valore assoluto) oltre la quale si segnala un possibile errore di dati.
    ``max_years``: se indicato, della finestra comune si usano solo gli ultimi ``max_years`` anni (mai meno di
    ``min_years``): i prezzi dei primi anni di vita di alcuni ETF contengono errori.
    """
    if prices.empty:
        raise DataError("core.data.no_prices")
    min_months = int(round(min_years * 12))
    as_of_ts = pd.Timestamp(as_of).normalize() if as_of is not None else pd.Timestamp.today().normalize()

    px = prices.where(prices > 0)
    monthly = px.resample("ME").last()
    monthly = monthly[monthly.index <= as_of_ts]  # solo mesi completi
    if monthly.empty:
        raise DataError("core.data.no_month")

    first_valid = {c: monthly[c].first_valid_index() for c in monthly}
    last_valid = {c: monthly[c].last_valid_index() for c in monthly}
    filled = monthly.ffill(limit=max_gap_months)
    for c in filled:  # niente estensione artificiale oltre l'ultimo dato reale
        if last_valid[c] is not None:
            filled.loc[filled.index > last_valid[c], c] = np.nan
    rets = filled.pct_change(fill_method=None)

    rows = []
    dropped: dict[str, str] = {}
    candidates = [c for c in rets if first_valid[c] is not None]
    for c in rets:
        if first_valid[c] is None:
            dropped[c] = Msg("core.data.reason_none")
    global_last = max(last_valid[c] for c in candidates) if candidates else None

    for c in list(candidates):
        n_valid = int(rets[c].notna().sum())
        if n_valid < min_months:
            dropped[c] = Msg("core.data.reason_short", years=f"{n_valid / 12:.1f}", minimum=f"{min_years:g}")
            candidates.remove(c)
        elif last_valid[c] < global_last - pd.DateOffset(months=stale_months):
            dropped[c] = Msg("core.data.reason_stale", last=f"{last_valid[c]:%m/%Y}")
            candidates.remove(c)

    keep = list(candidates)
    while True:
        if len(keep) < 2:
            break
        starts = {c: rets[c].first_valid_index() for c in keep}
        start, end = max(starts.values()), min(last_valid[c] for c in keep)
        window = rets.loc[start:end, keep]
        holes = [c for c in keep if window[c].isna().any()]
        if holes:
            for c in holes:
                dropped[c] = Msg("core.data.reason_holes")
                keep.remove(c)
            continue
        if len(window) < min_months:
            limiting = max(keep, key=lambda c: starts[c])
            dropped[limiting] = Msg("core.data.reason_window", start=f"{starts[limiting]:%m/%Y}")
            keep.remove(limiting)
            continue
        break

    if len(keep) < 2:
        raise DataError("core.data.insufficient", years=f"{min_years:g}",
                        reasons="; ".join(f"{k}: {v}" for k, v in dropped.items()))

    result = rets.loc[start:end, keep].astype(float)
    if max_years is not None:
        result = result.iloc[-max(min_months, int(round(float(max_years) * 12))):]
    notes: list[str] = []
    extreme = result.abs().stack()
    extreme = extreme[extreme > extreme_move]
    if not extreme.empty:
        sample = ", ".join(f"{t} ({d:%m/%Y}: {result.loc[d, t]:+.0%})" for (d, t) in extreme.index[:4])
        notes.append(Msg("core.data.extreme", sample=sample))

    for c in prices.columns:
        status = Msg("core.data.status_in") if c in keep else Msg("core.data.status_out")
        rows.append({
            "Ticker": c,
            "Primo dato": first_valid.get(c),
            "Ultimo dato": last_valid.get(c),
            "Stato": status,
            "Motivo": dropped.get(c, ""),
        })
    coverage = pd.DataFrame(rows)
    return PreparedReturns(result, coverage, dropped, notes)
