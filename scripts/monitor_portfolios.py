"""Controlla i portafogli seguiti: rilancia l'algoritmo genetico e avvisa quando i pesi target cambiano.

Da eseguire a intervalli regolari (cron, GitHub Actions: ``.github/workflows/monitor.yml``):

    python scripts/monitor_portfolios.py                    # controlla tutti i portafogli seguiti
    python scripts/monitor_portfolios.py --dry-run          # elenca cosa verrebbe controllato, senza scrivere nulla
    python scripts/monitor_portfolios.py --force            # rilancia l'algoritmo anche se la revisione non è dovuta
    python scripts/monitor_portfolios.py --portfolio 3 7    # solo alcuni portafogli
    python scripts/monitor_portfolios.py --as-of 2027-03-01 # simula una data diversa da oggi

Configurazione (variabili d'ambiente):
    GOALGA_DATABASE_URL     archivio condiviso con l'app (es. postgresql://utente:password@host/db);
                            in alternativa GOALGA_DB_PATH (file SQLite)
    GOALGA_SMTP_HOST, GOALGA_SMTP_PORT, GOALGA_SMTP_USER, GOALGA_SMTP_PASSWORD, GOALGA_SMTP_FROM,
    GOALGA_SMTP_SECURITY    (starttls | ssl | none) per le email; senza SMTP gli avvisi restano nell'app
    GOALGA_APP_URL          indirizzo dell'app, usato nel collegamento delle email

Codice di uscita: 0 = eseguito, 1 = almeno un portafoglio non è stato controllato per un errore.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from goalga.accounts import Accounts, Database  # noqa: E402
from goalga.accounts.monitor import review_due, run_checks  # noqa: E402
from goalga.accounts.notify import SmtpConfig  # noqa: E402
from goalga.accounts.payload import is_completed, years_elapsed  # noqa: E402


def _date(text: str) -> date:
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"data non valida: {text} (usa AAAA-MM-GG)") from exc


def dry_run(accounts: Accounts, as_of: date, only: list[int] | None) -> int:
    """Mostra, senza scrivere né scaricare dati, che cosa farebbe un controllo reale."""
    followed = [pf for pf in accounts.followed_portfolios() if only is None or pf.id in only]
    print(f"{len(followed)} portafogli seguiti al {as_of.isoformat()}")
    for pf in followed:
        version = accounts.current_version(pf.id)
        year = years_elapsed(pf.start_date, as_of) if pf.start_date else 0
        if is_completed(version.result, year):
            action = "piano concluso: avviso di completamento"
        elif review_due(pf, version, as_of):
            action = "revisione dovuta: rilancio dell'algoritmo"
        else:
            action = "solo verifica dei passaggi del glide path"
        print(f"  #{pf.id:<4} {pf.name[:40]:<40} anno {year:<3} v{version.number:<3} {action}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dry-run", action="store_true", help="elenca i controlli senza eseguirli")
    parser.add_argument("--force", action="store_true", help="rilancia l'algoritmo anche se la revisione non è dovuta")
    parser.add_argument("--as-of", type=_date, default=None, help="data di riferimento (AAAA-MM-GG), predefinita: oggi")
    parser.add_argument("--portfolio", type=int, nargs="+", default=None, metavar="ID", help="solo questi portafogli")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    accounts = Accounts(Database())
    as_of = args.as_of or accounts.today()
    if args.dry_run:
        return dry_run(accounts, as_of, args.portfolio)

    config = SmtpConfig.from_env()
    print("Email:", f"SMTP {config.host}:{config.port}" if config else "SMTP non configurato (solo avvisi nell'app)")
    outcomes = run_checks(accounts, as_of=as_of, force=args.force, app_url=config.app_url if config else "",
                          only=args.portfolio)
    for o in outcomes:
        extra = ", ".join(filter(None, [
            "rivisto" if o.reviewed else "", f"avviso #{o.alert_id}" if o.alert_id else "",
            "email inviata" if o.emailed else "", o.error]))
        print(f"  #{o.portfolio_id:<4} {o.name[:40]:<40} {o.status:<9} anno {o.year:<3} {extra}")
    errors = [o for o in outcomes if o.status == "error"]
    print(f"Controllati {len(outcomes)} portafogli: {sum(1 for o in outcomes if o.alert_id)} avvisi, {len(errors)} errori")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
