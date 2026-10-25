"""Pipeline di ottimizzazione senza interfaccia: scenari, algoritmo genetico, report, anteprime per profilo di rischio.

Usata dall'interfaccia (``ui/engine.py``), dal monitor dei portafogli seguiti e dai test: un unico percorso di
calcolo per tutti, così gli stessi parametri producono gli stessi risultati ovunque.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Callable, Mapping, Sequence

import numpy as np

from . import data as gdata
from . import snapshot
from .analytics import OptimizationReport, build_report
from .genetic import GAConfig, GAResult, run_ga
from .market import Market
from .plan import Plan, clamp_first_period
from .problem import Flows, GoalProblem
from .risk import PROFILE_KEYS, annual_return_quantile, profile_caps, restrict_market
from .selection import (
    DEFAULT_STOCKS,
    PROXY,
    Assumptions,
    PoolSettings,
    Screen,
    build_pool_market,
    draw_pool,
    get_screen,
)
from .trace import EvolutionTrace
from .universe import CATEGORIES, DEFAULT_ETF_SELECTION

SPEC_VERSION = 2
PREVIEW_PATIENCE = 40         # generazioni senza miglioramenti nelle anteprime (200 nell'ottimizzazione completa)
DEFAULT_YEARS, DEFAULT_MIN_YEARS = 20, 10
MARKET_SOURCE = "market"      # origine dei dati nelle specifiche (le versioni precedenti scrivevano «yahoo»)


@dataclass(frozen=True)
class RunSettings:
    """Parametri di una ricerca: algoritmo genetico, numero di scenari e scenari di validazione."""

    ga: GAConfig = GAConfig()
    n_scenarios: int = 1000
    oos_n: int = 10_000


@dataclass
class RunOutput:
    report: OptimizationReport
    result: GAResult
    trace: dict | None
    market: Market            # mercato effettivamente usato (limitato al profilo di rischio)
    max_level: int
    problem: GoalProblem
    flows: Flows


def make_problem(plan: Plan, market: Market, settings: RunSettings) -> tuple[Flows, GoalProblem]:
    """Flussi del piano e problema di ottimizzazione su un insieme di scenari riproducibile (seed)."""
    flows = plan.flows()
    rng = np.random.default_rng(np.random.SeedSequence([settings.ga.seed or 0, 101]))
    scenarios = market.draw_scenarios(plan.horizon, settings.n_scenarios, rng)
    return flows, GoalProblem(flows, scenarios, plan.pr_target, plan.alpha)


def optimize(plan: Plan, market: Market, settings: RunSettings, *, max_level: int | None = None,
             record: bool = True, validate: bool = True,
             callback: Callable | None = None) -> RunOutput:
    """Ricerca del glide path ottimale (opzionalmente entro un livello massimo di rischio)."""
    full_levels = market.n_portfolios
    used = restrict_market(market, max_level) if max_level else market
    flows, problem = make_problem(plan, used, settings)
    trace = EvolutionTrace(n_scenarios=settings.n_scenarios, n_portfolios=full_levels) if record else None

    def hook(progress) -> None:
        if trace is not None:
            trace(progress)
        if callback is not None:
            callback(progress)

    result = run_ga(problem, settings.ga, callback=hook if (trace is not None or callback is not None) else None)
    oos = settings.oos_n if validate else 0
    report = build_report(used, flows, problem, result, oos_scenarios=oos, oos_seed=(settings.ga.seed or 0) + 777)
    payload = None
    if trace is not None:
        payload = trace.payload(elapsed=result.elapsed, stopped_by=result.stopped_by,
                                best_generation=result.best_generation)
        payload["cap"] = int(max_level or full_levels)
    return RunOutput(report, result, payload, used, int(max_level or full_levels), problem, flows)


# ------------------------------------------------------------------ anteprima per profilo di rischio
@dataclass(frozen=True)
class ProfilePreview:
    key: str
    max_level: int
    pr: float                 # probabilità di successo (sugli scenari della ricerca) del miglior percorso trovato
    feasible: bool            # raggiunge la soglia Pr* del piano
    irr_es: float
    ret: float                # rendimento atteso del portafoglio più aggressivo consentito
    vol: float
    bad_year: float           # rendimento annuo nel 5° percentile (un anno sfavorevole su 20) di quel portafoglio
    path: tuple[int, ...]


def preview_profiles(plan: Plan, market: Market, settings: RunSettings, *, patience: int = PREVIEW_PATIENCE,
                     keys: Sequence[str] = PROFILE_KEYS,
                     progress: Callable[[int, int], None] | None = None) -> list[ProfilePreview]:
    """Probabilità di successo ottenibile con ciascun profilo (ricerca più breve, stessi scenari e stesso seed).

    A parità di seed la ricerca breve è un *prefisso* di quella completa: il risultato finale non può che
    coincidere con l'anteprima o migliorarla.
    """
    caps = profile_caps(market.n_portfolios)
    ret, vol = market.stats
    cfg = replace(settings.ga, patience=min(settings.ga.patience, int(patience)))
    quick = replace(settings, ga=cfg)
    done: dict[int, tuple[GAResult, float]] = {}
    out: list[ProfilePreview] = []
    for i, key in enumerate(keys):
        cap = caps[key]
        if cap not in done:
            restricted = restrict_market(market, cap)
            _, problem = make_problem(plan, restricted, quick)
            done[cap] = (run_ga(problem, cfg), annual_return_quantile(restricted, cap))
        res, bad = done[cap]
        out.append(ProfilePreview(key, cap, res.pr, res.feasible, res.irr_es, float(ret[cap - 1]),
                                  float(vol[cap - 1]), bad, tuple(int(x) for x in res.path)))
        if progress:
            progress(i + 1, len(keys))
    return out


# ------------------------------------------------------------------ specifiche serializzabili (portafogli salvati)
def spec_plan(spec: Mapping) -> Plan:
    """Piano descritto da una specifica (vedi ``ui.state.spec_from_state``)."""
    p = spec["plan"]
    goals = [(year, float(g["amount"])) for g in p["goals"] for year in range(int(g["start"]), int(g["end"]) + 1)]
    horizon = max([y for y, _ in goals], default=0)
    horizon = max(2, int(p.get("horizon") or horizon))
    return Plan(
        w0=float(p["w0"]), contribution=float(p["contribution"]), horizon=horizon,
        last_contribution_year=int(p["last_contribution_year"]) if p.get("last_contribution_year") is not None
        else max(0, horizon - 1),
        contribution_growth=float(p.get("growth", 0.0)), inflation=float(p.get("inflation", 0.0)),
        goals=tuple(goals), pr_target=float(p.get("pr", 0.9)), alpha=float(p.get("alpha", 0.05)),
        first_period=clamp_first_period(p.get("first_period", 1.0)))


def is_monitorable(spec: Mapping) -> bool:
    """True se la specifica si può ricalcolare in automatico (prezzi dell'archivio, portafogli efficienti)."""
    m = spec.get("market") or {}
    return m.get("source", MARKET_SOURCE) in (MARKET_SOURCE, "yahoo") and not m.get("custom_weights")


def plan_to_spec(plan: Plan, kinds: Sequence[str] | None = None) -> dict:
    """Parte «plan» di una specifica a partire da un piano (obiettivi consecutivi uguali raggruppati)."""
    from .plan import group_goals

    goals = [{"kind": (kinds[i] if kinds and i < len(kinds) else "altro"), "start": a, "end": b, "amount": c}
             for i, (a, b, c) in enumerate(group_goals(plan.goals))]
    spec = {"w0": plan.w0, "contribution": plan.contribution, "horizon": plan.horizon,
            "last_contribution_year": plan.effective_last_contribution(), "growth": plan.contribution_growth,
            "inflation": plan.inflation, "pr": plan.pr_target, "alpha": plan.alpha, "goals": goals}
    if plan.first_period != 1.0:
        spec["first_period"] = plan.first_period
    return spec


def goal_kinds(plan: Plan, original_goals: Sequence[Mapping], shift: int = 0) -> list[str]:
    """Tipo di obiettivo (casa, studi...) di ciascun gruppo di ``plan``, per ``plan_to_spec``.

    ``original_goals`` sono gli obiettivi della specifica da cui ``plan`` deriva e ``shift`` gli anni trascorsi dalla
    sua origine: dopo che alcuni obiettivi sono stati pagati i gruppi restanti non coincidono più per posizione.
    """
    from .plan import group_goals

    def kind_of(year: int) -> str:
        for g in original_goals:
            if int(g["start"]) <= year + shift <= int(g["end"]):
                return str(g.get("kind") or "altro")
        return "altro"

    return [kind_of(start) for start, _, _ in group_goals(plan.goals)]


def spec_settings(spec: Mapping) -> RunSettings:
    g = spec.get("ga") or {}
    cfg = GAConfig(
        pop_size=int(g.get("pop_size", 100)), p_c=float(g.get("p_c", 0.55)), p_m=float(g.get("p_m", 0.30)),
        mut_v=int(g.get("mut_v", 2)), patience=int(g.get("patience", 200)),
        max_generations=int(g.get("max_generations", 1000)), elitism=int(g.get("elitism", 1)),
        seed=int(g.get("seed", 42)))
    return RunSettings(cfg, int(g.get("n_scenarios", 1000)), int(g.get("oos_n", 10_000)))


def spec_market_options(spec: Mapping) -> dict:
    """Opzioni di costruzione del mercato descritte da una specifica (con i valori predefiniti per i campi assenti)."""
    m = spec.get("market") or {}
    return {
        "universe": list(m.get("universe") or DEFAULT_ETF_SELECTION), "years": int(m.get("years", DEFAULT_YEARS)),
        "min_years": int(m.get("min_years", DEFAULT_MIN_YEARS)), "max_weight": float(m.get("max_weight", 0.40)),
        "stock_share": float(m.get("stock_share", 0.30)), "stock_max": float(m.get("stock_max", 0.60)),
        "class_caps": bool(m.get("class_caps", True)),
        "min_position": float(m.get("min_position", 0.0)),        # i portafogli salvati prima dei minimi restano identici
        "min_stock_position": float(m.get("min_stock_position", 0.0)),
        "max_years": float(m["max_years"]) if m.get("max_years") else None,
        "shrinkage": bool(m.get("shrinkage", True)), "method": str(m.get("method", "annual")),
        "assumptions": Assumptions.from_dict(m.get("assumptions")),
        "cma": dict(m["cma"]) if m.get("cma") else None,
    }


def proxy_returns(prices, index=None):
    """Rendimenti mensili dell'indice di riferimento (usato per il beta dei titoli), se presente nei prezzi."""
    if PROXY not in getattr(prices, "columns", ()):
        return None
    series = prices[PROXY].where(prices[PROXY] > 0).resample("ME").last()
    rets = series.ffill(limit=2).pct_change(fill_method=None)
    return rets if index is None else rets.reindex(index)


def market_from_prices(prices, opts: Mapping, *, as_of=None) -> tuple[Market, gdata.PreparedReturns]:
    """Mercato (portafogli efficienti) dai prezzi mensili e dalle opzioni di una specifica.

    ``prices`` può contenere anche l'indice di riferimento (colonna ``SPY``): serve solo al beta dei titoli e non entra
    nel mercato se non fa parte dell'universo della specifica.
    """
    wanted = [t for t in opts.get("universe", []) if t in prices.columns] or list(prices.columns)
    # gli asset del pool hanno già superato la valutazione (niente movimenti mensili oltre +100% / -60%): l'avviso
    # sui salti anomali serve solo per dati non valutati
    prepared = gdata.prepare_returns(prices[wanted], min_years=float(opts["min_years"]), as_of=as_of,
                                     extreme_move=1.0, max_years=opts.get("max_years"))
    settings = PoolSettings(
        max_weight=float(opts["max_weight"]), stock_share=float(opts.get("stock_share", 0.30)),
        stock_max=float(opts.get("stock_max", 0.60)), shrinkage=bool(opts["shrinkage"]), method=str(opts["method"]),
        class_caps=bool(opts.get("class_caps", True)), assumptions=opts.get("assumptions") or Assumptions(),
        min_position=float(opts.get("min_position", 0.0)), min_stock_position=float(opts.get("min_stock_position", 0.0)))
    market = build_pool_market(prepared.returns, settings, proxy_returns(prices, prepared.returns.index),
                               cma=opts.get("cma"))
    return market, prepared


def default_loader(tickers, years):
    """Prezzi dall'archivio dell'universo (vedi ``goalga.snapshot``)."""
    return snapshot.snapshot_loader(tickers, years)


def prepare_market(spec: Mapping, *, loader: Callable | None = None, as_of=None) -> tuple[Market, gdata.PreparedReturns]:
    """Legge i prezzi dell'universo della specifica e costruisce il mercato (usato dal monitor)."""
    opts = spec_market_options(spec)
    load = loader or default_loader
    wanted = list(dict.fromkeys([*opts["universe"], PROXY]))
    price_data = load(wanted, int(opts["years"]))
    return market_from_prices(price_data.prices, opts, as_of=as_of)


# ------------------------------------------------------------------ universo scelto dall'utente
@dataclass(frozen=True)
class UniverseChoice:
    """Che cosa può usare l'algoritmo: tutte le categorie (predefinito), alcune, oppure asset scelti a mano."""

    mode: str = "auto"                         # auto: pool estratto dal seed | manual: solo gli asset indicati
    categories: tuple[str, ...] = CATEGORIES
    excluded: tuple[str, ...] = ()
    picks: tuple[str, ...] = ()
    stocks: int = DEFAULT_STOCKS
    min_years: int = DEFAULT_MIN_YEARS


def choose_pool(prices, seed: int, choice: UniverseChoice) -> tuple[list[str], Screen]:
    """Valuta tutto l'universo e restituisce il pool dei ticker per questo seed insieme alla valutazione."""
    screen = get_screen(prices, float(choice.min_years))
    if choice.mode == "manual":
        eligible = screen.eligible().index
        return [t for t in choice.picks if t in eligible], screen
    pool = draw_pool(screen, int(seed), categories=choice.categories, excluded=choice.excluded, stocks=int(choice.stocks))
    return pool, screen
