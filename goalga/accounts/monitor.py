"""Monitor dei portafogli seguiti: rilancia l'algoritmo genetico e avvisa quando i pesi target cambiano.

Per ogni portafoglio con gli avvisi attivi, a ogni esecuzione:

1. calcola l'anno del piano (anni interi dall'inizio dell'investimento) e i pesi target di quell'anno;
2. se è passato il tempo di revisione (predefinito: 90 giorni) o se richiesto, **rilancia l'algoritmo** sul piano
   residuo con prezzi aggiornati e salva una nuova versione. Il piano riparte da oggi: il primo flusso resta al
   prossimo anniversario dell'investimento (il primo anno è parziale) e il patrimonio di partenza è la mediana prevista
   per oggi corretta dello scarto dell'ultimo valore registrato (vedi ``estimate_wealth``);
3. se i pesi target differiscono da quelli già comunicati di almeno la soglia (predefinita: 5 punti percentuali su un
   singolo asset) crea un avviso (nell'app e, se configurato, per email).

I passaggi previsti dal glide path (es. da P7 a P5 al compimento dell'ottavo anno) generano quindi un avviso anche
senza revisione; le revisioni che spostano i pesi ne generano un altro. Pensato per essere eseguito a intervalli
regolari (es. con GitHub Actions: ``scripts/monitor_portfolios.py``).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Callable

import pandas as pd
from ..pipeline import (
    RunSettings,
    default_loader,
    goal_kinds,
    is_monitorable,
    optimize,
    plan_to_spec,
    prepare_market,
    spec_plan,
    spec_settings,
)
from ..plan import Plan
from ..risk import profile_caps
from ..universe import universe_names
from .notify import Notifier, default_notifier, notify_user
from .payload import (
    SOURCE_LABEL,
    elapsed_years,
    fan_value,
    is_completed,
    result_payload,
    year_fraction,
    years_elapsed,
)
from .service import Accounts, Checkin, Portfolio, Version

log = logging.getLogger("goalga.monitor")
MAX_CHECKIN_AGE_DAYS = 400


@dataclass
class Outcome:
    portfolio_id: int
    name: str
    status: str = "ok"            # ok | skipped | completed | error
    year: int = 0
    reviewed: bool = False
    alert_id: int | None = None
    emailed: bool = False
    error: str = ""


def caching_loader(loader: Callable | None = None) -> Callable:
    """Legge una sola volta i prezzi di ogni universo, anche se condiviso da più portafogli."""
    base = loader or default_loader
    cache: dict[tuple, object] = {}

    def load(tickers, years):
        key = (tuple(tickers), int(years))
        if key not in cache:
            cache[key] = base(list(tickers), int(years))
        return cache[key]

    return load


def review_due(pf: Portfolio, version: Version, as_of: date) -> bool:
    """True se dall'ultima versione è passato il tempo di revisione del portafoglio."""
    return (as_of - version.created_at.date()).days >= pf.review_days


def version_origin(version: Version) -> date:
    """Data da cui parte il piano di una versione (quella della revisione o della modifica che l'ha creata)."""
    created = (version.result or {}).get("created")
    try:
        return date.fromisoformat(str(created)) if created else version.created_at.date()
    except ValueError:
        return version.created_at.date()


def estimate_wealth(pf: Portfolio, version: Version, plan: Plan, checkin: Checkin | None,
                    as_of: date) -> tuple[float, str]:
    """Patrimonio stimato alla data ``as_of`` e da dove viene (``checkin`` o ``projection``).

    Parte dalla mediana prevista dalla versione per quel giorno, interpolata tra due flussi come patrimonio *prima*
    del flusso successivo. Se c'è un valore registrato dopo l'inizio della versione, ne aggiunge lo scarto rispetto
    alla mediana del giorno in cui è stato registrato: i flussi del piano tra le due date (versamenti, obiettivi pagati)
    sono già nella mediana, quindi un valore registrato prima di un anniversario non viene scambiato per il
    patrimonio dopo quell'anniversario.
    """
    result = version.result
    net = plan.flows().net
    base = fan_value(result, "p50", elapsed_years(pf.start_date, as_of), net)
    if base is None:
        base = plan.w0
    floor = max(pf.start_date, version_origin(version))
    if checkin is not None and floor <= checkin.on_date <= as_of \
            and (as_of - checkin.on_date).days <= MAX_CHECKIN_AGE_DAYS:
        then = fan_value(result, "p50", elapsed_years(pf.start_date, checkin.on_date), net)
        if then is not None:
            return max(0.0, base + checkin.value - then), "checkin"
    return max(0.0, base), "projection"


def reoptimize(accounts: Accounts, pf: Portfolio, version: Version, k: int, as_of: date,
               loader: Callable) -> tuple[dict, dict] | None:
    """Rilancia l'algoritmo sul piano residuo con dati aggiornati.

    Il piano riparte da ``as_of``: il primo flusso resta al prossimo anniversario dell'investimento (tra
    ``1 - frazione`` anni) e il patrimonio di partenza è la stima per quel giorno (vedi ``estimate_wealth``).
    Restituisce la nuova specifica e il nuovo risultato (con ``anchor = k``), oppure ``None`` se del piano non resta
    nulla da pianificare (ultimo anno).
    """
    spec, old = version.spec, version.result
    anchor = int(old.get("anchor", 0))
    plan = spec_plan(spec)
    floor = max(pf.start_date, version_origin(version))
    wealth, _ = estimate_wealth(pf, version, plan, accounts.latest_checkin(pf.id, after=floor), as_of)
    remaining = plan.advance(k - anchor, wealth, year_fraction(pf.start_date, as_of))
    if remaining is None:
        return None
    new_spec = {**spec, "plan": plan_to_spec(remaining, goal_kinds(remaining, spec["plan"]["goals"], k - anchor))}
    market, prepared = prepare_market(new_spec, loader=loader, as_of=pd.Timestamp(as_of))
    settings: RunSettings = spec_settings(new_spec)
    cap = profile_caps(market.n_portfolios)[spec.get("risk", "balanced")]
    out = optimize(remaining, market, settings, max_level=cap, record=False, validate=True)
    tickers = list(market.names)
    result = result_payload(out.report, market, remaining, names=universe_names(tickers),
                            source=SOURCE_LABEL, risk=spec.get("risk", "balanced"), max_level=cap, anchor=k,
                            as_of=as_of)
    return new_spec, result


def check_portfolio(accounts: Accounts, portfolio_id: int, *, as_of: date | None = None, force: bool = False,
                    loader: Callable | None = None, notifier: Notifier | None = None,
                    app_url: str = "") -> Outcome:
    """Controlla un portafoglio seguito (vedi la descrizione del modulo)."""
    as_of = as_of or accounts.today()
    pf = accounts.portfolio(portfolio_id)
    if pf is None:
        return Outcome(portfolio_id, "", status="skipped")
    out = Outcome(pf.id, pf.name)
    if not pf.invested or pf.start_date is None or pf.status != "active":
        out.status = "skipped"
        return out
    notifier = notifier or default_notifier()
    version = accounts.current_version(pf.id)
    k = years_elapsed(pf.start_date, as_of)
    out.year = k

    if is_completed(version.result, k):
        alert = accounts.create_alert(pf.user_id, pf.id, "completed", {"as_of": as_of.isoformat()})
        accounts.touch_checked(pf.id, completed=True)
        out.status, out.alert_id = "completed", alert.id
        user = accounts.get_user(pf.user_id)
        if user is not None:
            out.emailed = notify_user(accounts, user, alert, pf.name, notifier, app_url)
        return out

    reviewed = False
    if (force or review_due(pf, version, as_of)) and is_monitorable(version.spec):
        try:
            revised = reoptimize(accounts, pf, version, k, as_of, caching_loader(loader))
            if revised is not None:                       # nell'ultimo anno non resta un piano da rivedere
                version = accounts.add_review_version(pf.id, *revised)
                reviewed = True
        except Exception as exc:                          # rete, dati insufficienti...
            log.warning("Revisione del portafoglio %s non riuscita: %s", pf.id, exc)
            out.status, out.error = "error", f"{type(exc).__name__}: {exc}"
    out.reviewed = reviewed

    alert = accounts.notify_if_changed(accounts.portfolio(pf.id), version.result, k,
                                       "reviewed" if reviewed else "scheduled", as_of)
    accounts.touch_checked(pf.id, reviewed=reviewed)
    if alert is not None:
        out.alert_id = alert.id
        user = accounts.get_user(pf.user_id)
        if user is not None:
            out.emailed = notify_user(accounts, user, alert, pf.name, notifier, app_url)
    return out


def run_checks(accounts: Accounts, *, as_of: date | None = None, force: bool = False, loader: Callable | None = None,
               notifier: Notifier | None = None, app_url: str = "", only: list[int] | None = None) -> list[Outcome]:
    """Controlla tutti i portafogli seguiti (o quelli indicati), condividendo gli scaricamenti dei prezzi."""
    shared = caching_loader(loader)
    notifier = notifier or default_notifier()
    outcomes = []
    for pf in accounts.followed_portfolios():
        if only is not None and pf.id not in only:
            continue
        try:
            outcomes.append(check_portfolio(accounts, pf.id, as_of=as_of, force=force, loader=shared,
                                            notifier=notifier, app_url=app_url))
        except Exception as exc:                          # un portafoglio problematico non ferma gli altri
            log.exception("Controllo del portafoglio %s non riuscito", pf.id)
            outcomes.append(Outcome(pf.id, pf.name, status="error", error=f"{type(exc).__name__}: {exc}"))
    return outcomes
