"""Invio degli avvisi per email (SMTP) con ripiego sul solo registro quando l'SMTP non è configurato."""
from __future__ import annotations

import html
import logging
import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from typing import Protocol

from .. import i18n
from ..i18n import t
from .messages import describe
from .service import Accounts, Alert, User

log = logging.getLogger("goalga.notify")


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: int = 587
    user: str = ""
    password: str = ""
    sender: str = ""
    security: str = "starttls"          # starttls | ssl | none
    app_url: str = ""

    @classmethod
    def from_env(cls) -> "SmtpConfig | None":
        host = os.environ.get("GOALGA_SMTP_HOST", "").strip()
        if not host:
            return None
        user = os.environ.get("GOALGA_SMTP_USER", "")
        return cls(host=host, port=int(os.environ.get("GOALGA_SMTP_PORT", "587")), user=user,
                   password=os.environ.get("GOALGA_SMTP_PASSWORD", ""),
                   sender=os.environ.get("GOALGA_SMTP_FROM", user or f"goalga@{host}"),
                   security=os.environ.get("GOALGA_SMTP_SECURITY", "starttls").lower(),
                   app_url=os.environ.get("GOALGA_APP_URL", "").strip())


class Notifier(Protocol):
    def send(self, to: str, subject: str, text: str, html_body: str) -> bool: ...


class LogNotifier:
    """Nessun SMTP configurato: l'avviso resta nell'applicazione e viene solo registrato."""

    def send(self, to: str, subject: str, text: str, html_body: str) -> bool:
        log.info("Email non inviata (SMTP non configurato) a %s: %s", to, subject)
        return False


class SmtpNotifier:
    def __init__(self, config: SmtpConfig) -> None:
        self.config = config

    def send(self, to: str, subject: str, text: str, html_body: str) -> bool:
        cfg = self.config
        message = EmailMessage()
        message["Subject"], message["From"], message["To"] = subject, cfg.sender, to
        message.set_content(text)
        message.add_alternative(html_body, subtype="html")
        context = ssl.create_default_context()
        try:
            if cfg.security == "ssl":
                server = smtplib.SMTP_SSL(cfg.host, cfg.port, context=context, timeout=20)
            else:
                server = smtplib.SMTP(cfg.host, cfg.port, timeout=20)
            with server:
                if cfg.security == "starttls":
                    server.starttls(context=context)
                if cfg.user:
                    server.login(cfg.user, cfg.password)
                server.send_message(message)
            return True
        except (OSError, smtplib.SMTPException) as exc:
            log.warning("Invio email a %s non riuscito: %s", to, exc)
            return False


def default_notifier() -> Notifier:
    config = SmtpConfig.from_env()
    return SmtpNotifier(config) if config else LogNotifier()


def build_email(user: User, alert: Alert, portfolio_name: str, app_url: str = "") -> tuple[str, str, str]:
    """Oggetto, testo semplice e HTML dell'email, nella lingua dell'utente."""
    with i18n.use(user.locale):
        text = describe(alert, portfolio_name)
        subject = f"GoalGA · {text.title}"
        lines = [text.title, "", text.summary, ""]
        lines += [f"- {r['asset']} ({r['ticker']}): {r['old']} → {r['new']} ({r['delta']})" for r in text.rows]
        lines += ["", t("email.footer")]
        if app_url:
            lines += [app_url]
        rows = "".join(
            f'<tr><td style="padding:6px 10px;border-bottom:1px solid #e5e7eb">{html.escape(r["asset"])}'
            f'<br><span style="color:#6b7280;font-size:12px">{html.escape(r["ticker"])}</span></td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #e5e7eb;text-align:right">{html.escape(r["old"])}</td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #e5e7eb;text-align:right"><b>{html.escape(r["new"])}</b></td>'
            f'<td style="padding:6px 10px;border-bottom:1px solid #e5e7eb;text-align:right;'
            f'color:{"#059669" if r["up"] else "#dc2626"}">{html.escape(r["delta"])}</td></tr>' for r in text.rows)
        table = (f'<table style="border-collapse:collapse;width:100%;font-size:14px"><thead><tr>'
                 f'<th style="text-align:left;padding:6px 10px">{html.escape(t("alert.col.asset"))}</th>'
                 f'<th style="text-align:right;padding:6px 10px">{html.escape(t("alert.col.old"))}</th>'
                 f'<th style="text-align:right;padding:6px 10px">{html.escape(t("alert.col.new"))}</th>'
                 f'<th style="text-align:right;padding:6px 10px"></th></tr></thead><tbody>{rows}</tbody></table>'
                 if rows else "")
        link = (f'<p><a href="{html.escape(app_url, quote=True)}">{html.escape(t("email.open_app"))}</a></p>'
                if app_url else "")
        body = (f'<div style="font-family:Arial,Helvetica,sans-serif;color:#111827;max-width:560px">'
                f'<h2 style="margin:0 0 8px">{html.escape(text.title)}</h2><p>{html.escape(text.summary)}</p>{table}{link}'
                f'<p style="color:#6b7280;font-size:12px">{html.escape(t("email.footer"))}</p></div>')
    return subject, "\n".join(lines), body


def notify_user(accounts: Accounts, user: User, alert: Alert, portfolio_name: str, notifier: Notifier,
                app_url: str = "") -> bool:
    """Invia l'avviso per email se l'utente lo desidera; registra l'invio. Restituisce True se è partito."""
    if not user.email_alerts:
        return False
    subject, text, body = build_email(user, alert, portfolio_name, app_url)
    sent = notifier.send(user.email, subject, text, body)
    if sent:
        accounts.mark_emailed(alert.id)
    return sent
