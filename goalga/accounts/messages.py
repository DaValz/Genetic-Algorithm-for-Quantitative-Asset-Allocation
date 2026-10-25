"""Testi degli avvisi (schermo ed email) nella lingua dell'utente."""
from __future__ import annotations

from dataclasses import dataclass

from ..i18n import fmt, t
from .service import Alert


@dataclass(frozen=True)
class AlertText:
    title: str
    summary: str
    rows: list[dict]            # [{asset, ticker, old, new, delta}] con importi già formattati


def describe(alert: Alert, portfolio_name: str) -> AlertText:
    """Titolo, frase di sintesi e variazioni per asset di un avviso (nella lingua attiva)."""
    p = alert.payload
    if alert.kind == "completed":
        return AlertText(t("alert.title.completed", name=portfolio_name), t("alert.completed"), [])
    a, b = p.get("level_from"), p.get("level_to")
    reason = p.get("reason", "reviewed")
    if reason == "reviewed" and a == b:
        summary = t("alert.reason.updated", b=b)
    else:
        summary = t(f"alert.reason.{reason}", a=a if a is not None else "?", b=b if b is not None else "?")
    rows = []
    for c in p.get("changes", []):
        delta = c["new"] - c["old"]
        rows.append({
            "asset": c.get("name") or c["ticker"], "ticker": c["ticker"],
            "old": fmt.pct(c["old"], 0), "new": fmt.pct(c["new"], 0),
            "delta": f"{'+' if delta >= 0 else '−'}{fmt.number(abs(delta) * 100, 0)} {t('unit.pp')}",
            "up": delta >= 0})
    return AlertText(t("alert.title.weights", name=portfolio_name), summary, rows)
