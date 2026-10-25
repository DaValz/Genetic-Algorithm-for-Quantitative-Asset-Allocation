"""Parametri del piano finanziario, validazione e preset (casi dell'articolo)."""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from math import isfinite

from .i18n import Msg
from .problem import Flows, build_flows

MAX_HORIZON = 60
MIN_FIRST_PERIOD = 1.0 / 52.0                      # almeno una settimana al primo flusso


def clamp_first_period(value) -> float:
    """Durata del primo anno ammessa: da una settimana a un anno intero (valori non numerici = anno intero)."""
    try:
        x = float(value)
    except (TypeError, ValueError):
        return 1.0
    return min(1.0, max(MIN_FIRST_PERIOD, x)) if x == x else 1.0


@dataclass(frozen=True)
class Plan:
    w0: float = 160_000.0
    contribution: float = 10_000.0
    horizon: int = 30
    last_contribution_year: int | None = None      # None -> horizon - 1 (convenzione del paper)
    contribution_growth: float = 0.0
    inflation: float = 0.0
    goals: tuple[tuple[int, float], ...] = field(default_factory=tuple)
    pr_target: float = 0.95
    alpha: float = 0.02
    first_period: float = 1.0                      # anni mancanti al primo flusso (1 = anno intero; <1 se si riparte a metà anno)

    def effective_last_contribution(self) -> int:
        return self.horizon - 1 if self.last_contribution_year is None else int(self.last_contribution_year)

    def validate(self) -> list[str]:
        """Restituisce l'elenco (vuoto se il piano è valido) dei problemi bloccanti (messaggi traducibili)."""
        errors: list[str] = []
        if not 2 <= self.horizon <= MAX_HORIZON:
            errors.append(Msg("core.plan.horizon", max=MAX_HORIZON))
        if not (isfinite(self.w0) and isfinite(self.contribution)) or self.w0 < 0 or self.contribution < 0:
            errors.append(Msg("core.plan.negative"))
        if self.w0 == 0 and self.contribution == 0:
            errors.append(Msg("core.plan.empty"))
        if not 0 <= self.effective_last_contribution() <= self.horizon:
            errors.append(Msg("core.plan.last_contribution"))
        if not self.goals:
            errors.append(Msg("core.plan.no_goals"))
        for year, amount in self.goals:
            if int(year) != year or not 1 <= year <= self.horizon:
                errors.append(Msg("core.plan.goal_year", year=year, horizon=self.horizon))
            if not (amount > 0 and isfinite(amount)):
                errors.append(Msg("core.plan.goal_amount", year=year))
        if not 0.5 <= self.pr_target <= 1.0:
            errors.append(Msg("core.plan.pr"))
        if not 0.0 < self.alpha <= 0.5:
            errors.append(Msg("core.plan.alpha"))
        return list(dict.fromkeys(errors))

    def flows(self) -> Flows:
        return build_flows(
            self.w0, self.horizon, self.contribution, self.effective_last_contribution(),
            self.contribution_growth, list(self.goals), self.inflation, self.first_period,
        )

    def with_goals(self, goals) -> "Plan":
        return replace(self, goals=tuple((int(y), float(a)) for y, a in goals))

    def advance(self, years: int, wealth: float, fraction: float = 0.0) -> "Plan | None":
        """Piano residuo dopo ``years`` anni interi e una ``fraction`` d'anno, ripartendo dal patrimonio ``wealth``.

        Gli obiettivi già passati vengono rimossi; versamenti e importi degli obiettivi sono riportati ai valori
        nominali dell'anno corrente (crescita dei versamenti e inflazione). Il primo flusso resta al prossimo
        anniversario, tra ``1 - fraction`` anni (``first_period``). ``None`` se non resta nulla da pianificare.
        """
        k = int(years)
        goals = [(y - k, a) for y, a in self.goals if y > k]
        horizon = self.horizon - k
        if horizon < 2 or not goals:
            return None
        return replace(
            self, w0=max(0.0, float(wealth)), horizon=horizon,
            last_contribution_year=max(0, self.effective_last_contribution() - k),
            contribution=self.contribution * (1.0 + self.contribution_growth) ** k,
            goals=tuple((int(y), float(a) * (1.0 + self.inflation) ** k) for y, a in goals),
            first_period=clamp_first_period(1.0 - float(fraction)))


def group_goals(goals) -> list[tuple[int, int, float]]:
    """Unisce anni consecutivi con lo stesso importo: ``[(inizio, fine, importo)]``."""
    groups: list[list[float]] = []
    for year, amount in sorted((int(y), float(a)) for y, a in goals):
        if groups and year == groups[-1][1] + 1 and abs(amount - groups[-1][2]) < 1e-6:
            groups[-1][1] = year
        else:
            groups.append([year, year, amount])
    return [(int(a), int(b), float(c)) for a, b, c in groups]


PAPER_GOALS_CASE_1 = (
    tuple((year, 32_000.0) for year in (10, 11, 12, 13))
    + tuple((year, 40_000.0) for year in (20, 21, 22, 23))
    + ((50, 1_900_000.0),)
)

PRESETS: dict[str, Plan] = {
    "Caso 1 del paper · 50 anni, tre obiettivi": Plan(
        w0=160_000, contribution=10_000, horizon=50, goals=PAPER_GOALS_CASE_1, pr_target=0.95, alpha=0.02),
    "Caso 2 del paper · 15 anni, capitale target": Plan(
        w0=500_000, contribution=15_000, horizon=15, goals=((15, 1_000_000.0),), pr_target=0.95, alpha=0.05),
    "Esempio · casa e pensione": Plan(
        w0=50_000, contribution=6_000, horizon=25, goals=((8, 40_000.0), (25, 350_000.0)),
        pr_target=0.90, alpha=0.05),
}
DEFAULT_PRESET = "Caso 1 del paper · 50 anni, tre obiettivi"
