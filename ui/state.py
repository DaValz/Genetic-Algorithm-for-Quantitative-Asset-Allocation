"""Stato di sessione: percorso guidato, piano dell'utente, impostazioni avanzate e risultati."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Mapping

import numpy as np
import pandas as pd
import streamlit as st

from goalga.data import PreparedReturns
from goalga.genetic import GAConfig
from goalga.market import Market
from goalga.pipeline import MARKET_SOURCE, SPEC_VERSION, UniverseChoice
from goalga.pipeline import is_monitorable as _is_monitorable
from goalga.plan import Plan, clamp_first_period
from goalga.risk import PROFILE_KEYS
from goalga.selection import DEFAULT_STOCKS, MAX_WINDOW_YEARS, MIN_POSITION, MIN_STOCK_POSITION, Assumptions
from goalga.universe import CATEGORIES, FUND_CATEGORIES, SECTOR_CATEGORIES, class_defaults, equity_premium_default

STEPS = ("welcome", "start", "goals", "risk", "review", "evolve", "plan", "holdings", "lab", "account")
JOURNEY = ("start", "goals", "risk", "review", "evolve", "plan")      # segmenti della barra di avanzamento
DEFAULT_RISK = "balanced"
GA_DEFAULTS = dict(pop_size=100, p_c=0.55, p_m=0.30, mut_v=2, patience=200, max_gens=1000,
                   elitism=1, n_scenarios=1000, oos_n=10_000)
# livelli di impegno della ricerca (area avanzata): parametri dell'algoritmo genetico e dei scenari
EFFORTS: dict[str, dict[str, Any]] = {
    "quick": dict(pop_size=60, n_scenarios=500, patience=60, oos_n=5_000),
    "standard": dict(pop_size=GA_DEFAULTS["pop_size"], n_scenarios=GA_DEFAULTS["n_scenarios"],
                     patience=GA_DEFAULTS["patience"], oos_n=GA_DEFAULTS["oos_n"]),
    "thorough": dict(pop_size=200, n_scenarios=3000, patience=300, oos_n=20_000),
}
CLASS_KEYS = ("cash", "govt_bond", "corp_bond", "hy_bond", "em_bond", "dev_equity", "em_equity", "commodities",
              "real_estate_fund")
# valori di partenza di tutte le impostazioni dell'area avanzata (le scelte automatiche dell'app)
LAB_DEFAULTS: dict[str, Any] = {
    **GA_DEFAULTS, "rob_runs": 10, "seed_fixed": False, "seed": 42,
    "pool_mode": "auto", "cats_funds": list(FUND_CATEGORIES), "cats_sectors": list(SECTOR_CATEGORIES),
    "manual_sel": [], "excluded_sel": [], "pool_stocks": DEFAULT_STOCKS, "stock_share_pct": 30, "min_years": 10,
    "assump_source": "long_term", "outlook_pt": 0.0,
    "max_weight_pct": 40, "use_shrinkage": True, "boot_method": "annual", "use_custom_weights": False,
    "tail_free": 1, "growth_pct": 0.0, "infl_pct": 2.0, "pr_pct": 90, "alpha_pct": 5.0,
}

# tipo di obiettivo -> (icona Material, anno suggerito, importo suggerito); il nome è nel catalogo («goal.kind.<tipo>»)
GOAL_KINDS: dict[str, tuple[str, int, int]] = {
    "casa": ("home", 8, 40_000),
    "studi": ("school", 15, 40_000),
    "pensione": ("beach_access", 25, 300_000),
    "altro": ("flag", 10, 20_000),
}

# chiavi dei widget dell'area avanzata: vanno "fissate" per sopravvivere ai cambi di schermata
# (non i data_editor: Streamlit non ammette di assegnarne la chiave, le loro modifiche sono salvate a parte)
LAB_KEYS = [
    "pool_mode", "cats_funds", "cats_sectors", "manual_sel", "excluded_sel", "pool_stocks", "stock_share_pct",
    "min_years", "assump_source", "outlook_pt", *[f"cls_{k}" for k in (*CLASS_KEYS, "stocks")],
    "max_weight_pct", "use_shrinkage", "boot_method", "use_custom_weights", "pop_size", "p_c", "p_m", "mut_v", "elitism",
    "patience", "max_gens", "n_scenarios", "seed", "seed_fixed", "oos_n", "rob_runs", "tail_free", "growth_pct",
    "infl_pct", "pr_pct", "alpha_pct", "lab_section", "effort",
]
# chiavi dei widget dei passi: ripartono dai valori canonici a ogni nuovo piano
_STEP_WIDGET_PREFIXES = ("in_", "bad_", "gy_", "gw_", "gm_", "ga_", "gk_", "chip-")


for _key in CLASS_KEYS:
    LAB_DEFAULTS[f"cls_{_key}"] = round(class_defaults().get(_key, 0.0) * 100, 2)
LAB_DEFAULTS["cls_stocks"] = round(equity_premium_default() * 100, 2)


def _jsonable(obj: Any) -> Any:
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return dataclasses.asdict(obj)
    if isinstance(obj, (np.ndarray, pd.Index)):
        return np.asarray(obj).tolist()
    if isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    if isinstance(obj, (pd.Timestamp, datetime)):
        return obj.isoformat()
    if isinstance(obj, (set, frozenset)):
        return sorted(obj)
    return str(obj)


def signature(*parts: Any) -> str:
    """Firma stabile di un insieme di parametri (serve a capire se un risultato è ancora valido)."""
    raw = json.dumps(parts, default=_jsonable, sort_keys=True)
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


@dataclass
class DataBundle:
    """I dati su cui lavora il mercato corrente: pool di asset, rendimenti puliti e quanto è stato valutato."""

    sig: str
    prepared: PreparedReturns
    requested: list[str]                 # ticker del pool
    names: dict[str, str]
    cma: dict[str, float]                # rendimenti attesi usati (ticker -> annuo)
    seed: int = 0
    evaluated: int = 0                   # asset valutati (tutto il catalogo)
    eligible: int = 0                    # asset idonei dopo la valutazione
    failed: dict[str, str] = field(default_factory=dict)
    loaded_at: datetime = field(default_factory=datetime.now)


@dataclass
class MarketBundle:
    """Mercato corrente: ``market`` è quello usato dall'ottimizzazione, ``base`` quello con i portafogli efficienti."""

    sig: str
    market: Market
    data: DataBundle | None = None
    base: Market | None = None


@dataclass
class ResultBundle:
    sig: str
    report: Any
    plan: Plan
    settings: dict
    market: Market
    ga_config: Any
    n_scenarios: int
    data: DataBundle | None = None
    trace: dict | None = None
    risk: str = DEFAULT_RISK
    max_level: int = 9
    spec: dict | None = None
    previews: list | None = None


# --------------------------------------------------------------------------- impostazioni (automatiche o avanzate)
def setting(key: str) -> Any:
    """Valore effettivo di un'impostazione: quello scelto nell'area avanzata se attiva, altrimenti l'automatico."""
    ss = st.session_state
    if ss.get("use_advanced") and key in ss:
        return ss[key]
    default = LAB_DEFAULTS[key]
    return list(default) if isinstance(default, list) else default


# --------------------------------------------------------------------------- seed e avvii della ricerca
def fresh_seed() -> int:
    """Seed casuale (entropia del sistema operativo): ogni ricerca esplora una sequenza diversa."""
    return int(np.random.default_rng().integers(1, 2**31 - 1))


def seed_is_fixed() -> bool:
    """True se l'utente ha chiesto risultati riproducibili (solo area avanzata)."""
    ss = st.session_state
    return bool(ss.get("use_advanced") and ss.get("seed_fixed"))


def pending_seed() -> int:
    """Seed che userà il prossimo avvio: quello fissato nell'area avanzata, altrimenti uno casuale già estratto.

    Le anteprime del rischio usano lo stesso seed della ricerca che seguirà (a parità di seed la ricerca breve è un
    prefisso di quella completa); dopo ogni avvio ne viene estratto uno nuovo.
    """
    ss = st.session_state
    if seed_is_fixed():
        return int(ss["seed"])
    if not ss.get("seed_next"):
        ss["seed_next"] = fresh_seed()
    return int(ss["seed_next"])


def begin_launch(*, keep_seed: bool = False) -> None:
    """Avvia una ricerca: fissa il seed da usare e, se non è fisso, ne prepara uno nuovo per la prossima.

    ``keep_seed`` riusa il seed dell'ultimo risultato (per confrontare i profili di rischio a parità di pool e di scenari).
    """
    ss = st.session_state
    fixed = seed_is_fixed()
    current = ss.get("result")
    if keep_seed and current is not None:
        seed = int(current.ga_config.seed)
    else:
        seed = pending_seed()
        if not fixed:
            ss["seed_next"] = fresh_seed()
    ss["launch"] = {"id": uuid.uuid4().hex[:8], "seed": seed}


def launch_seed() -> int:
    """Seed della ricerca in corso (se manca un avvio esplicito ne viene creato uno)."""
    ss = st.session_state
    if not ss.get("launch"):
        begin_launch()
    return int(ss["launch"]["seed"])


# --------------------------------------------------------------------------- obiettivi e piano
def new_goal(kind: str = "altro", start: int | None = None, end: int | None = None,
             amount: float | None = None) -> dict:
    """Obiettivo: ``amount`` euro ogni anno dall'anno ``start`` all'anno ``end`` (inclusi)."""
    ss = st.session_state
    gid = int(ss.get("next_goal_id", 1))
    ss["next_goal_id"] = gid + 1
    _, year, default = GOAL_KINDS[kind]
    start = year if start is None else int(start)
    return {"id": gid, "kind": kind, "start": start, "end": start if end is None else int(end),
            "amount": float(default if amount is None else amount)}


def expand_goals(goals: Iterable[dict]) -> list[tuple[int, float]]:
    return [(year, float(g["amount"])) for g in goals for year in range(int(g["start"]), int(g["end"]) + 1)]


def _reset_step_widgets() -> None:
    ss = st.session_state
    for key in [k for k in ss if str(k).startswith(_STEP_WIDGET_PREFIXES) or k == "add_goal"]:
        del ss[key]


def start_fresh() -> None:
    """Nuovo piano: nessun valore precedente (le impostazioni avanzate scelte dall'utente restano)."""
    ss = st.session_state
    ss.update(w0=0.0, contribution=0.0, goals=[], risk=DEFAULT_RISK)
    for key in ("result", "risk_previews", "_export_cache", "_fig_cache", "robust", "editing_portfolio", "seen_run",
                "saved_portfolio", "launch", "pool_pin", "plan_fp", "edit_note"):
        ss.pop(key, None)
    _reset_step_widgets()


def build_plan() -> tuple[Plan, list[str]]:
    """Piano corrente dallo stato di sessione e relativi errori di validazione."""
    ss = st.session_state
    goals = expand_goals(ss["goals"])
    horizon = max([y for y, _ in goals], default=0)
    horizon = max(2, horizon)
    tail = max(0, int(setting("tail_free")))
    plan = Plan(
        w0=float(ss["w0"]), contribution=float(ss["contribution"]), horizon=horizon,
        last_contribution_year=max(0, horizon - tail), contribution_growth=float(setting("growth_pct")) / 100.0,
        inflation=float(setting("infl_pct")) / 100.0, goals=tuple(goals), pr_target=float(setting("pr_pct")) / 100.0,
        alpha=float(setting("alpha_pct")) / 100.0, first_period=clamp_first_period(ss.get("plan_fp", 1.0)),
    )
    return plan, plan.validate()


# --------------------------------------------------------------------------- universo e ipotesi scelti dall'utente
def _tickers_of(labels) -> tuple[str, ...]:
    """Ticker da etichette del tipo «AAPL · Apple Inc.»."""
    return tuple(dict.fromkeys(str(x).split(" · ")[0].strip().upper() for x in labels if str(x).strip()))


def universe_choice() -> UniverseChoice:
    """Che cosa può usare l'algoritmo, secondo le impostazioni (automatiche o avanzate)."""
    return UniverseChoice(
        mode=str(setting("pool_mode")), categories=(*setting("cats_funds"), *setting("cats_sectors")),
        excluded=_tickers_of(setting("excluded_sel")), picks=_tickers_of(setting("manual_sel")),
        stocks=int(setting("pool_stocks")), min_years=int(setting("min_years")))


def current_assumptions() -> Assumptions:
    """Ipotesi di rendimento: fonte, prospettiva e scostamenti per classe rispetto alle ipotesi di partenza."""
    shift = {}
    for key in (*CLASS_KEYS, "stocks"):
        delta = (float(setting(f"cls_{key}")) - float(LAB_DEFAULTS[f"cls_{key}"])) / 100.0
        if abs(delta) > 1e-9:
            shift[key] = delta
    return Assumptions(source=str(setting("assump_source")), outlook=float(setting("outlook_pt")) / 100.0,
                       class_shift=shift)


def market_options(pool: list[str]) -> dict:
    """Opzioni di costruzione del mercato per ``goalga.pipeline.market_from_prices``."""
    manual = setting("pool_mode") == "manual"
    return {
        "universe": list(pool), "min_years": int(setting("min_years")), "max_weight": float(setting("max_weight_pct")) / 100,
        "stock_share": 0.0 if manual else float(setting("stock_share_pct")) / 100, "stock_max": 0.60,
        "class_caps": not manual, "shrinkage": bool(setting("use_shrinkage")), "method": str(setting("boot_method")),
        "min_position": MIN_POSITION, "min_stock_position": MIN_STOCK_POSITION, "max_years": MAX_WINDOW_YEARS,
        "assumptions": current_assumptions(), "cma": None,
    }


# --------------------------------------------------------------------------- specifiche dei portafogli salvati
def spec_from_run(plan: Plan, market: Market, data: DataBundle | None, ga: GAConfig, n_scenarios: int, oos_n: int,
                  *, risk: str, advanced: bool, goals: list[dict], choice: UniverseChoice, options: Mapping,
                  custom_weights: bool) -> dict:
    """Descrizione serializzabile (JSON) di una ricerca: sufficiente a ripeterla con dati aggiornati.

    L'universo è l'elenco esplicito dei ticker del pool: rilanciando la specifica gli asset non cambiano.
    """
    tickers = list(data.requested) if data is not None else list(market.names)
    plan_part = {
        "w0": plan.w0, "contribution": plan.contribution, "horizon": plan.horizon,
        "last_contribution_year": plan.effective_last_contribution(), "growth": plan.contribution_growth,
        "inflation": plan.inflation, "pr": plan.pr_target, "alpha": plan.alpha,
        "goals": [{"kind": g["kind"], "start": int(g["start"]), "end": int(g["end"]), "amount": float(g["amount"])}
                  for g in goals],
    }
    if plan.first_period != 1.0:
        plan_part["first_period"] = plan.first_period
    return {
        "v": SPEC_VERSION,
        "plan": plan_part,
        "risk": risk,
        "advanced": bool(advanced),
        "market": {
            "source": MARKET_SOURCE, "universe": tickers, "years": 20, "min_years": int(options["min_years"]),
            "max_weight": float(options["max_weight"]), "stock_share": float(options["stock_share"]),
            "stock_max": float(options["stock_max"]), "class_caps": bool(options["class_caps"]),
            "min_position": float(options.get("min_position", 0.0)),
            "min_stock_position": float(options.get("min_stock_position", 0.0)),
            "max_years": options.get("max_years"),
            "shrinkage": bool(options["shrinkage"]), "method": str(options["method"]),
            "assumptions": options["assumptions"].to_dict(), "custom_weights": bool(custom_weights),
            "mode": choice.mode, "categories": list(choice.categories), "excluded": list(choice.excluded),
            "stocks": int(choice.stocks),
            "evaluated": int(data.evaluated) if data is not None else 0,
            "eligible": int(data.eligible) if data is not None else 0,
        },
        "ga": {"pop_size": ga.pop_size, "p_c": ga.p_c, "p_m": ga.p_m, "mut_v": ga.mut_v, "patience": ga.patience,
               "max_generations": ga.max_generations, "elitism": ga.elitism, "seed": ga.seed,
               "n_scenarios": int(n_scenarios), "oos_n": int(oos_n)},
    }


def is_monitorable(spec: Mapping) -> bool:
    """True se la specifica può essere ricalcolata in automatico (prezzi dell'archivio, portafogli efficienti)."""
    return _is_monitorable(spec)


def apply_spec(spec: Mapping) -> None:
    """Carica una specifica salvata nello stato (piano, rischio e, se presenti, impostazioni avanzate).

    Il primo avvio dopo il caricamento riusa il seed salvato e lo stesso pool di asset: modificare il piano non
    rimescola i titoli; gli avvii successivi estraggono di nuovo.
    """
    ss = st.session_state
    p, m, g = spec["plan"], spec.get("market") or {}, spec.get("ga") or {}
    ss.update(w0=float(p["w0"]), contribution=float(p["contribution"]),
              goals=[new_goal(x["kind"] if x["kind"] in GOAL_KINDS else "altro", x["start"], x["end"], x["amount"])
                     for x in p["goals"]],
              risk=spec.get("risk") if spec.get("risk") in PROFILE_KEYS else DEFAULT_RISK,
              use_advanced=bool(spec.get("advanced")))
    ss["plan_fp"] = clamp_first_period(p.get("first_period", 1.0))
    inflation, growth = float(p.get("inflation", 0.0)) * 100, float(p.get("growth", 0.0)) * 100
    if not spec.get("advanced") and (abs(inflation - LAB_DEFAULTS["infl_pct"]) > 1e-9
                                     or abs(growth - LAB_DEFAULTS["growth_pct"]) > 1e-9):
        ss.update(infl_pct=inflation, growth_pct=growth, use_advanced=True)     # piani salvati con ipotesi diverse da quelle di oggi
    if spec.get("advanced"):
        horizon = int(p.get("horizon") or 0)
        a = Assumptions.from_dict(m.get("assumptions"))
        ss.update(
            pr_pct=int(round(float(p.get("pr", 0.9)) * 100)), alpha_pct=float(p.get("alpha", 0.05)) * 100,
            tail_free=max(0, horizon - int(p.get("last_contribution_year", horizon - 1))),
            growth_pct=float(p.get("growth", 0.0)) * 100, infl_pct=float(p.get("inflation", 0.0)) * 100,
            max_weight_pct=int(round(float(m.get("max_weight", 0.4)) * 100)),
            use_shrinkage=bool(m.get("shrinkage", True)), boot_method=m.get("method", "annual"),
            min_years=min(int(m.get("min_years", 10)), MAX_WINDOW_YEARS), pool_mode=str(m.get("mode", "auto")),
            cats_funds=[c for c in m.get("categories", CATEGORIES) if c in FUND_CATEGORIES] or list(FUND_CATEGORIES),
            cats_sectors=[c for c in m.get("categories", CATEGORIES) if c in SECTOR_CATEGORIES] or list(SECTOR_CATEGORIES),
            excluded_sel=list(m.get("excluded") or []), pool_stocks=int(m.get("stocks", DEFAULT_STOCKS)),
            stock_share_pct=int(round(float(m.get("stock_share", 0.30)) * 100)),
            assump_source=a.source, outlook_pt=a.outlook * 100,
            **{f"cls_{k}": round(float(LAB_DEFAULTS[f"cls_{k}"]) + a.class_shift.get(k, 0.0) * 100, 2)
               for k in (*CLASS_KEYS, "stocks")},
            **{k: g[k] for k in ("pop_size", "p_c", "p_m", "mut_v", "patience", "elitism", "n_scenarios", "oos_n")
               if k in g},
            max_gens=int(g.get("max_generations", 1000)), seed_fixed=False)
        if m.get("mode") == "manual":
            ss["manual_sel"] = list(m.get("universe") or [])
        for key in ("market_bundle", "market_auto"):
            ss.pop(key, None)
    seed = int(g.get("seed") or 0)
    if seed:
        ss["seed"] = seed
        ss["seed_next"] = seed
        if m.get("universe") and m.get("mode", "auto") == "auto":
            ss["pool_pin"] = {"seed": seed, "sig": signature(universe_choice()), "tickers": list(m["universe"])}
    _reset_step_widgets()
    for key in ("result", "risk_previews", "_export_cache", "_fig_cache", "robust", "seen_run", "launch"):
        ss.pop(key, None)


# --------------------------------------------------------------------------- navigazione
def go(step: str, *, keep_seed: bool = False) -> None:
    """Callback di navigazione: da usare come ``on_click``.

    Entrare nella schermata «evolve» è un nuovo avvio della ricerca: ogni avvio usa un seed nuovo (salvo seed fisso
    nell'area avanzata o ``keep_seed``, usato per confrontare i profili di rischio a parità di scenari).
    """
    ss = st.session_state
    if step == "lab" and ss.get("step") != "lab":
        ss["lab_from"] = ss.get("step", "review")
        ss["use_advanced"] = True          # chi apre l'area avanzata vuole usare quelle impostazioni
    if step == "evolve" and ss.get("step") != "evolve":
        begin_launch(keep_seed=keep_seed)
    ss["step"] = step


def begin() -> None:
    """Inizio del percorso dalla home: sempre un piano nuovo."""
    start_fresh()
    go("start")


def pin(keys: Iterable[str]) -> None:
    """Impedisce a Streamlit di scartare lo stato dei widget non mostrati in questa schermata."""
    ss = st.session_state
    for key in keys:
        if key in ss:
            ss[key] = ss[key]


def init_state() -> None:
    """Valori predefiniti alla prima esecuzione e, a ogni esecuzione, protezione delle impostazioni avanzate.

    Streamlit scarta lo stato dei widget che non vengono mostrati: le impostazioni dell'area avanzata devono
    sopravvivere anche mentre l'utente si trova su un'altra schermata, quindi le si "fissa" a ogni esecuzione.
    """
    ss = st.session_state
    if not ss.get("_initialized"):
        ss.update(w0=0.0, contribution=0.0, goals=[], step="welcome", risk=DEFAULT_RISK, use_advanced=False)
        ss["_initialized"] = True
    ss.setdefault("use_advanced", False)
    ss.setdefault("risk", DEFAULT_RISK)
    for key, value in LAB_DEFAULTS.items():
        ss.setdefault(key, list(value) if isinstance(value, list) else value)
    pin(LAB_KEYS)


def reset_ga_settings() -> None:
    for key, value in GA_DEFAULTS.items():
        st.session_state[key] = value
