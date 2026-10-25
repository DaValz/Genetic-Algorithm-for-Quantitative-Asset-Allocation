"""Selezione dell'universo: dall'universo completo (migliaia di asset) al mercato su cui lavora l'algoritmo genetico.

1. **Valutazione** (``screen_universe``): ogni asset del catalogo viene valutato (storico, dati mancanti, movimenti
   anomali, volatilità, beta e quota di rischio remunerata) e risulta idoneo oppure no, con il motivo dell'esclusione.
2. **Pool** (``draw_pool``): tutti i fondi idonei e, per le azioni, un insieme diversificato estratto in modo
   riproducibile dal seed (alcuni titoli per ogni settore, con più probabilità per quelli con più rischio remunerato).
   Cambiando seed cambia il pool: nel tempo ogni titolo idoneo ha la sua possibilità.
3. **Mercato** (``build_pool_market``): rendimenti attesi (fondi: ipotesi di lungo periodo; azioni: CAPM con il beta
   misurato sui dati) e portafogli efficienti P1-P9, con i titoli riuniti in una cesta diversificata (vedi
   ``goalga.market.Basket``).
"""
from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from typing import Mapping, Sequence

import numpy as np
import pandas as pd

from .market import Basket, Market, build_market
from .scenarios import expected_annual_return
from .universe import (
    CATEGORIES,
    FUND_CATEGORIES,
    SECTOR_CATEGORIES,
    SKIP_REASONS,
    catalog,
    equity_premium_default,
    risk_free_default,
)

PROXY = "SPY"                                 # indice di riferimento per il beta dei titoli (S&P 500, in euro)
EQUITY_FUNDS = ("dev_equity", "em_equity")    # classi di fondi che contano come esposizione azionaria
DATA_REASONS = ("no_data", "stale", "short", "gaps", "extreme", "volatile")
REASONS = SKIP_REASONS + DATA_REASONS
DEFAULT_STOCKS = 33                           # titoli nella cesta
MIN_POSITION = 0.01                           # nessuna posizione sotto l'1% del portafoglio (fondi e titoli scelti a mano)
MIN_STOCK_POSITION = 0.005                    # nessun titolo della cesta sotto lo 0,5%: la cesta compare solo se vale n x 0,5%
MAX_WINDOW_YEARS = 14                         # finestra di stima: al massimo gli ultimi 14 anni (e storico minimo massimo). I
                                              # prezzi dei primi anni di vita di alcuni ETF (prima del 2012) hanno mesi errati
RANK_FLOOR = 0.25                             # probabilità minima relativa di estrazione (il peggiore vale 0,25 + 0)
BLUME = (0.67, 0.33)                          # correzione del beta verso 1


# --------------------------------------------------------------------------------------
# Valutazione di tutto l'universo
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Screen:
    """Esito della valutazione: una riga per asset del catalogo (colonna ``Reason`` vuota se idoneo)."""

    table: pd.DataFrame
    start: pd.Timestamp
    end: pd.Timestamp
    min_years: float

    @property
    def n_evaluated(self) -> int:
        return int(len(self.table))

    @property
    def n_eligible(self) -> int:
        return int(self.table["Eligible"].sum())

    def eligible(self) -> pd.DataFrame:
        return self.table[self.table["Eligible"]]

    def reason_counts(self) -> dict[str, int]:
        """Quanti asset sono esclusi per ciascun motivo (solo i motivi presenti, nell'ordine standard)."""
        counts = self.table.loc[~self.table["Eligible"], "Reason"].value_counts()
        return {r: int(counts[r]) for r in REASONS if r in counts.index}

    def category_counts(self) -> dict[str, int]:
        """Asset idonei per categoria (anche zero), nell'ordine standard delle categorie."""
        counts = self.eligible()["Categoria"].value_counts()
        return {c: int(counts.get(c, 0)) for c in CATEGORIES}


def screen_universe(prices: pd.DataFrame, *, min_years: float = 10.0, max_gap: int = 2, stale_months: int = 3,
                    up_limit: float = 1.0, down_limit: float = -0.6, vol_limit: float = 0.8) -> Screen:
    """Valuta tutti gli asset del catalogo sull'ultima finestra di ``min_years`` anni di prezzi mensili.

    Esclusi gli strumenti che non sono azioni ordinarie, gli asset senza dati o con dati vecchi, con storico più
    breve della finestra o con buchi e, per le azioni, quelle con movimenti mensili anomali (oltre +100% o sotto
    -60%: tipici di split inversi, fallimenti e titoli speculativi) o volatilità annua oltre l'80%.
    """
    table = catalog()
    months = max(12, int(round(float(min_years) * 12)))
    present = [c for c in table.index if c in prices.columns]
    px = prices[present]
    n_rows = px.shape[0]
    raw = px.to_numpy(dtype=float)
    valid = ~np.isnan(raw)
    filled = px.ffill(limit=max_gap).to_numpy(dtype=float)
    any_valid = valid.any(axis=0)
    first = np.where(any_valid, valid.argmax(axis=0), n_rows)
    last = np.where(any_valid, n_rows - 1 - valid[::-1].argmax(axis=0), -1)
    enough = n_rows >= months + 1
    window = filled[-(months + 1):] if enough else filled
    full = (~np.isnan(window)).all(axis=0) if enough else np.zeros(len(present), dtype=bool)

    reason = np.full(len(present), "", dtype=object)
    skip = table["Skip"].reindex(present).to_numpy(dtype=object)
    reason[skip != ""] = skip[skip != ""]
    for code, mask in (("no_data", ~any_valid), ("stale", last < n_rows - 1 - stale_months),
                       ("short", (n_rows - first) < months + 1), ("gaps", ~full)):
        reason[(reason == "") & mask] = code

    vol = np.full(len(present), np.nan)
    beta = np.full(len(present), np.nan)
    r2 = np.full(len(present), np.nan)
    score = np.full(len(present), np.nan)
    ok = np.flatnonzero(reason == "")
    if ok.size:
        w = window[:, ok]
        r = w[1:] / w[:-1] - 1.0
        is_stock = (table["Tipo"].reindex(present).to_numpy()[ok] == "stock")
        sigma = r.std(axis=0, ddof=1) * np.sqrt(12.0)
        bad = is_stock & ((r.max(axis=0) > up_limit) | (r.min(axis=0) < down_limit))
        loud = is_stock & ~bad & (sigma > vol_limit)
        names_ok = np.array(present, dtype=object)[ok]
        spy = np.flatnonzero(names_ok == PROXY)
        if spy.size:
            proxy = r[:, spy[0]]
        else:
            base = r[:, is_stock & ~bad & ~loud]
            proxy = base.mean(axis=1) if base.shape[1] else r.mean(axis=1)
        pc = proxy - proxy.mean()
        rc = r - r.mean(axis=0)
        cov_ip = (rc * pc[:, None]).mean(axis=0)
        var_p = float((pc**2).mean()) or 1.0
        b = cov_ip / var_p
        adjusted = np.clip(BLUME[0] * b + BLUME[1], 0.3, 1.8)
        vol[ok], beta[ok] = sigma, b
        r2[ok] = cov_ip**2 / (var_p * np.maximum((rc**2).mean(axis=0), 1e-18))
        score[ok] = adjusted / np.maximum(sigma, 1e-9)
        reason[ok[bad]] = "extreme"
        reason[ok[loud]] = "volatile"

    out = pd.DataFrame(index=table.index)
    out["Nome"], out["Tipo"], out["Categoria"] = table["Nome"], table["Tipo"], table["Categoria"]
    out["Reason"] = table["Skip"].where(table["Skip"] != "", "no_data")
    out.loc[present, "Reason"] = reason
    out["Months"] = 0
    out.loc[present, "Months"] = valid.sum(axis=0)
    for name, values in (("Vol", vol), ("Beta", beta), ("R2", r2), ("Score", score)):
        out[name] = np.nan
        out.loc[present, name] = values
    out["Eligible"] = out["Reason"] == ""
    ranked = out.loc[out["Eligible"]].groupby(["Tipo", "Categoria"])["Score"].rank(pct=True)
    out["Rank"] = ranked.reindex(out.index).fillna(0.0)
    start = px.index[-(months + 1)] if enough and n_rows else (px.index[0] if n_rows else pd.NaT)
    return Screen(out, start, px.index[-1] if n_rows else pd.NaT, float(min_years))


_SCREENS: dict[tuple, Screen] = {}
_SCREENS_LOCK = threading.Lock()


def fingerprint(prices: pd.DataFrame) -> tuple:
    """Impronta economica di un archivio di prezzi (serve a riusare la valutazione se i dati non cambiano)."""
    last = prices.iloc[-1].to_numpy(dtype=float) if len(prices) else np.array([])
    mid = prices.iloc[len(prices) // 2].to_numpy(dtype=float) if len(prices) else np.array([])
    return (prices.shape, str(prices.index[0]) if len(prices) else "", str(prices.index[-1]) if len(prices) else "",
            round(float(np.nansum(last)), 4), round(float(np.nansum(mid)), 4))


def get_screen(prices: pd.DataFrame, min_years: float = 10.0) -> Screen:
    """Valutazione dell'universo con cache: dipende solo dai prezzi e dalla storia minima richiesta.

    La cache è condivisa tra le sessioni (thread) dello stesso processo: l'accesso è protetto da un blocco, così due
    sessioni che chiedono la stessa valutazione non la calcolano due volte né si contendono lo svuotamento della cache.
    """
    key = (fingerprint(prices), float(min_years))
    with _SCREENS_LOCK:
        screen = _SCREENS.get(key)
        if screen is None:
            if len(_SCREENS) >= 6:
                _SCREENS.pop(next(iter(_SCREENS)))
            screen = _SCREENS[key] = screen_universe(prices, min_years=min_years)
    return screen


# --------------------------------------------------------------------------------------
# Pool diversificato
# --------------------------------------------------------------------------------------
def quotas(counts: Mapping[str, int], total: int) -> dict[str, int]:
    """Titoli da estrarre per settore: proporzionali alla radice della numerosità (almeno uno, se possibile)."""
    live = {c: int(n) for c, n in counts.items() if n > 0}
    out = {c: 0 for c in counts}
    total = min(int(total), sum(live.values()))
    if not live or total <= 0:
        return out
    weight = {c: np.sqrt(n) for c, n in live.items()}
    norm = sum(weight.values())
    raw = {c: total * w / norm for c, w in weight.items()}
    floor_min = 1 if total >= len(live) else 0
    q = {c: min(live[c], max(floor_min, int(np.floor(raw[c])))) for c in live}
    while sum(q.values()) < total:
        open_ = [c for c in live if q[c] < live[c]]
        if not open_:
            break
        q[max(open_, key=lambda c: raw[c] - q[c])] += 1
    while sum(q.values()) > total:
        open_ = [c for c in live if q[c] > floor_min]
        if not open_:
            break
        q[min(open_, key=lambda c: raw[c] - q[c])] -= 1
    out.update(q)
    return out


def draw_pool(screen: Screen, seed: int, *, categories: Sequence[str] | None = None, excluded: Sequence[str] = (),
              stocks: int = DEFAULT_STOCKS) -> list[str]:
    """Pool: tutti i fondi idonei delle categorie scelte e ``stocks`` azioni estratte (riproducibili dal ``seed``).

    Le azioni sono distribuite tra i settori scelti in proporzione alla radice della loro numerosità e, dentro il
    settore, estratte con probabilità crescente con la quota di rischio remunerata (rango del Sharpe atteso dal CAPM).
    """
    chosen = set(CATEGORIES if categories is None else categories)
    skip = {str(t).upper() for t in excluded}
    pool = screen.eligible()
    pool = pool[~pool.index.isin(skip)]
    rng = np.random.default_rng(np.random.SeedSequence([int(seed) & 0x7FFFFFFF, 202]))

    funds = [t for c in FUND_CATEGORIES if c in chosen
             for t in sorted(pool.index[(pool["Tipo"] == "fund") & (pool["Categoria"] == c)])]
    members = pool[(pool["Tipo"] == "stock") & pool["Categoria"].isin(chosen)]
    counts = {c: int((members["Categoria"] == c).sum()) for c in SECTOR_CATEGORIES if c in chosen}
    picked: list[str] = []
    for sector, take in quotas(counts, stocks).items():
        if take <= 0:
            continue
        candidates = members[members["Categoria"] == sector].sort_index()
        weight = RANK_FLOOR + candidates["Rank"].to_numpy(dtype=float)
        idx = rng.choice(len(candidates), size=take, replace=False, p=weight / weight.sum())
        picked += list(candidates.index[idx])
    return funds + sorted(picked)


# --------------------------------------------------------------------------------------
# Rendimenti attesi e mercato del pool
# --------------------------------------------------------------------------------------
@dataclass
class Assumptions:
    """Ipotesi di rendimento: da dove partono e di quanto l'utente le sposta."""

    source: str = "long_term"                                      # long_term | historical
    outlook: float = 0.0                                            # scostamento annuo applicato a tutti gli asset
    class_shift: dict[str, float] = field(default_factory=dict)     # per classe di fondi e «stocks» (premio azionario)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping | None) -> "Assumptions":
        data = data or {}
        return cls(source=str(data.get("source", "long_term")), outlook=float(data.get("outlook", 0.0)),
                   class_shift={str(k): float(v) for k, v in (data.get("class_shift") or {}).items()})

    @property
    def is_default(self) -> bool:
        return self.source == "long_term" and abs(self.outlook) < 1e-12 and not any(abs(v) > 1e-12 for v in self.class_shift.values())


def estimate_betas(returns: pd.DataFrame, proxy: pd.Series | None) -> dict[str, float]:
    """Beta (corretto verso 1) di ciascuna colonna rispetto all'indice di riferimento, sulla finestra dei rendimenti."""
    if proxy is None:
        return {}
    aligned = proxy.reindex(returns.index)
    if aligned.isna().any() or len(aligned) < 12:
        return {}
    pc = aligned - aligned.mean()
    var = float((pc**2).mean())
    if var <= 0:
        return {}
    raw = (returns - returns.mean()).mul(pc, axis=0).mean() / var
    return {str(t): float(np.clip(BLUME[0] * b + BLUME[1], 0.3, 1.8)) for t, b in raw.items()}


def class_of(ticker: str) -> str:
    table = catalog()
    return str(table.at[ticker, "Categoria"]) if ticker in table.index else ""


def expected_returns(returns: pd.DataFrame, assumptions: Assumptions | None = None,
                     proxy: pd.Series | None = None) -> dict[str, float]:
    """Rendimento annuo atteso di ciascuna colonna.

    * fondi con ipotesi curata: l'ipotesi di lungo periodo della classe (più l'eventuale scostamento dell'utente);
    * azioni (e fondi senza ipotesi): CAPM, ``tasso privo di rischio + beta x premio per il rischio azionario``;
    * asset sconosciuti al catalogo: media storica;
    * con fonte «storica»: la media storica di tutti.
    In ogni caso si somma l'eventuale prospettiva (``outlook``) e il risultato resta in un intervallo ragionevole.
    """
    a = assumptions or Assumptions()
    table = catalog()
    hist = dict(zip(returns.columns, expected_annual_return(returns.to_numpy(dtype=float))))
    out: dict[str, float] = {}
    if a.source == "historical":
        return {str(t): float(np.clip(h + a.outlook, -0.05, 0.60)) for t, h in hist.items()}
    rf = risk_free_default() + a.class_shift.get("cash", 0.0)
    premium = equity_premium_default() + a.class_shift.get("stocks", 0.0)
    betas = estimate_betas(returns, proxy)
    for t in returns.columns:
        if t not in table.index:
            base = hist[t]
        else:
            row = table.loc[t]
            if row["Tipo"] == "fund" and pd.notna(row["CMA"]):
                base = float(row["CMA"]) + a.class_shift.get(str(row["Categoria"]), 0.0)
            else:
                base = rf + betas.get(str(t), 1.0) * premium
        out[str(t)] = float(np.clip(base + a.outlook, -0.05, 0.60))
    return out


@dataclass
class PoolSettings:
    """Come si costruiscono i portafogli a partire dal pool."""

    max_weight: float = 0.40          # tetto per asset e, con ``class_caps``, per asset class (somma dei suoi fondi)
    stock_share: float = 0.30         # quota minima della parte azionaria investita nella cesta di titoli (0 = nessuna)
    stock_max: float = 0.60           # peso massimo della cesta nel portafoglio
    shrinkage: bool = True
    method: str = "annual"
    class_caps: bool = True           # il tetto vale anche per la somma dei fondi di una stessa asset class
    min_position: float = MIN_POSITION             # peso minimo di una posizione (0 = nessun minimo)
    min_stock_position: float = MIN_STOCK_POSITION  # peso minimo di ciascun titolo della cesta
    assumptions: Assumptions = field(default_factory=Assumptions)


def split_pool(tickers: Sequence[str]) -> tuple[list[str], list[str]]:
    """(fondi, titoli) di un elenco di ticker; gli sconosciuti al catalogo contano come fondi."""
    table = catalog()
    stocks = [t for t in tickers if t in table.index and table.at[t, "Tipo"] == "stock"]
    return [t for t in tickers if t not in set(stocks)], stocks


def build_pool_market(returns: pd.DataFrame, settings: PoolSettings | None = None, proxy: pd.Series | None = None,
                      cma: Mapping[str, float] | None = None) -> Market:
    """Mercato (portafogli efficienti) per i rendimenti mensili del pool.

    ``cma`` sono rendimenti attesi espliciti per singolo asset (hanno la precedenza sulle ipotesi).
    """
    s = settings or PoolSettings()
    mu = expected_returns(returns, s.assumptions, proxy)
    if cma:
        mu.update({str(k): float(v) for k, v in cma.items() if k in returns.columns and v is not None})
    funds, stocks = split_pool(list(returns.columns))
    basket = None
    if stocks and len(funds) >= 2 and s.stock_share > 0:
        equity = tuple(t for t in funds if class_of(t) in EQUITY_FUNDS)
        basket = Basket(tuple(stocks), float(s.stock_share), float(s.stock_max), equity)
    groups = [[t for t in funds if class_of(t) == c] for c in FUND_CATEGORIES] if s.class_caps else []
    market = build_market(returns, expected_returns=mu, max_weight=s.max_weight, use_shrinkage=s.shrinkage,
                          method=s.method, basket=basket, groups=groups, group_cap=s.max_weight,
                          min_weight=s.min_position, basket_member_min=s.min_stock_position)
    market.meta["pool"] = {"funds": len(funds), "stocks": len(stocks)}
    return market
