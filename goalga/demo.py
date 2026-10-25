"""Serie mensili sintetiche per i test automatici e gli esempi di codice (l'app non usa dati simulati).

Struttura a fattori e innovazioni di Student-t, calibrate sulle 12 asset class dell'esempio del paper
(rendimenti attesi dell'Exhibit 6). **Non** vanno usate per decisioni di investimento.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# nome, descrizione, rendimento atteso annuo (Exhibit 6 del paper), volatilità annua,
# carichi sui fattori [tassi, credito, azionario, materie prime]
_CLASSES = [
    ("CASH", "Liquidità", 0.020, 0.005, (0.00, 0.00, 0.00, 0.00)),
    ("EUR_BT", "Obbligazionario euro breve termine", 0.029, 0.015, (0.80, 0.05, 0.00, 0.00)),
    ("EUR_GOV", "Obbligazionario governativo euro", 0.039, 0.050, (0.95, 0.10, 0.05, 0.00)),
    ("EUR_CORP", "Obbligazionario corporate euro", 0.042, 0.045, (0.75, 0.55, 0.15, 0.00)),
    ("GLOB_BOND", "Obbligazionario globale", 0.039, 0.050, (0.85, 0.20, 0.10, 0.00)),
    ("EM_BOND", "Obbligazionario mercati emergenti", 0.059, 0.080, (0.35, 0.65, 0.45, 0.05)),
    ("HY", "Obbligazionario high yield", 0.075, 0.090, (0.10, 0.75, 0.60, 0.05)),
    ("EQ_EUR", "Azionario Europa", 0.072, 0.170, (-0.05, 0.25, 0.95, 0.10)),
    ("EQ_USA", "Azionario USA", 0.078, 0.160, (-0.05, 0.20, 0.95, 0.05)),
    ("EQ_PAC", "Azionario Pacifico", 0.070, 0.160, (-0.05, 0.20, 0.85, 0.10)),
    ("EQ_EM", "Azionario mercati emergenti", 0.085, 0.190, (-0.05, 0.25, 0.85, 0.20)),
    ("COMM", "Materie prime", 0.039, 0.160, (-0.10, 0.10, 0.40, 0.90)),
]


def synthetic_monthly_returns(
    n_months: int = 240, seed: int = 7, end: str = "2026-09-30", df: float = 5.0
) -> pd.DataFrame:
    """Rendimenti mensili sintetici con code grasse e correlazioni plausibili."""
    rng = np.random.default_rng(seed)
    loadings = np.array([c[4] for c in _CLASSES])
    n = len(_CLASSES)

    def t_noise(size: tuple[int, ...]) -> np.ndarray:
        return rng.standard_t(df, size=size) / np.sqrt(df / (df - 2.0))

    factors = t_noise((n_months, loadings.shape[1]))
    # lieve dipendenza di coda comune: un fattore di "panico" amplifica le perdite azionarie
    panic = (rng.random(n_months) < 0.04) * rng.uniform(1.0, 2.5, n_months)
    factors[:, 2] -= panic
    systematic = factors @ loadings.T
    resid_var = np.clip(1.0 - np.sum(loadings**2, axis=1), 0.05, None)
    raw = systematic + t_noise((n_months, n)) * np.sqrt(resid_var)
    raw = (raw - raw.mean(axis=0)) / raw.std(axis=0, ddof=0)

    out = np.empty_like(raw)
    for j, (_, _, mu, vol, _) in enumerate(_CLASSES):
        monthly_mean = (1.0 + mu) ** (1.0 / 12.0) - 1.0
        out[:, j] = monthly_mean + raw[:, j] * vol / np.sqrt(12.0)
    index = pd.date_range(end=pd.Timestamp(end), periods=n_months, freq="ME")
    return pd.DataFrame(out, index=index, columns=[c[0] for c in _CLASSES])
