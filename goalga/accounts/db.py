"""Archivio di conti, portafogli, versioni, check-in e avvisi.

SQLAlchemy Core: SQLite per provare in locale, PostgreSQL (o altro) in produzione tramite ``GOALGA_DATABASE_URL``.
Su piattaforme con file system effimero (es. Streamlit Community Cloud) un file SQLite si azzera a ogni riavvio:
in produzione usare un database esterno.
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import (Boolean, Column, Date, DateTime, Float, ForeignKey, Integer, MetaData, String, Table, Text,
                        create_engine, event)

metadata = MetaData()

users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("email", String(254), nullable=False, unique=True),
    Column("name", String(80), nullable=False, default=""),
    Column("password_hash", String(255), nullable=False),
    Column("locale", String(8), nullable=False, default="en"),
    Column("email_alerts", Boolean, nullable=False, default=True),
    Column("created_at", DateTime, nullable=False),
    Column("last_login_at", DateTime),
    Column("failed_logins", Integer, nullable=False, default=0),
    Column("locked_until", DateTime),
)

portfolios = Table(
    "portfolios", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("name", String(80), nullable=False),
    Column("status", String(16), nullable=False, default="active"),      # active | completed
    Column("invested", Boolean, nullable=False, default=False),          # «seguito»: gli avvisi sono attivi
    Column("start_date", Date),                                          # inizio dell'investimento (anno 0 del piano)
    Column("review_days", Integer, nullable=False, default=90),          # ogni quanti giorni rilanciare l'algoritmo
    Column("tolerance", Float, nullable=False, default=0.05),            # variazione minima di peso che fa scattare l'avviso
    Column("current_version", Integer),
    Column("ref_weights", Text),                                         # ultimi pesi target comunicati (JSON)
    Column("ref_level", Integer),
    Column("created_at", DateTime, nullable=False),
    Column("updated_at", DateTime, nullable=False),
    Column("last_checked_at", DateTime),
    Column("last_reviewed_at", DateTime),
)

versions = Table(
    "portfolio_versions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("portfolio_id", Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("number", Integer, nullable=False),
    Column("created_at", DateTime, nullable=False),
    Column("reason", String(16), nullable=False),                        # created | edited | reviewed
    Column("spec", Text, nullable=False),                                # JSON: piano, rischio, impostazioni
    Column("result", Text, nullable=False),                              # JSON: percorso, pesi, metriche
)

checkins = Table(
    "checkins", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("portfolio_id", Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("on_date", Date, nullable=False),
    Column("value", Float, nullable=False),
    Column("note", String(200), nullable=False, default=""),
    Column("created_at", DateTime, nullable=False),
)

alerts = Table(
    "alerts", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("user_id", Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("portfolio_id", Integer, ForeignKey("portfolios.id", ondelete="CASCADE"), index=True),
    Column("created_at", DateTime, nullable=False),
    Column("kind", String(24), nullable=False),                          # weights | completed
    Column("payload", Text, nullable=False),
    Column("read_at", DateTime),
    Column("emailed_at", DateTime),
)


def default_url() -> str:
    """URL dell'archivio: ``GOALGA_DATABASE_URL`` oppure un file SQLite locale (``GOALGA_DB_PATH``)."""
    url = os.environ.get("GOALGA_DATABASE_URL", "").strip()
    if url:
        return "postgresql://" + url[len("postgres://"):] if url.startswith("postgres://") else url
    path = Path(os.environ.get("GOALGA_DB_PATH") or Path(__file__).resolve().parents[2] / "data" / "goalga.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.as_posix()}"


class Database:
    """Connessione all'archivio (crea le tabelle se mancano)."""

    def __init__(self, url: str | None = None) -> None:
        self.url = url or default_url()
        self.is_sqlite = self.url.startswith("sqlite")
        kwargs = {"connect_args": {"check_same_thread": False}} if self.is_sqlite else {"pool_pre_ping": True}
        self.engine = create_engine(self.url, **kwargs)
        if self.is_sqlite:
            @event.listens_for(self.engine, "connect")
            def _pragma(dbapi_connection, _record) -> None:      # integrità referenziale e scritture concorrenti
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.close()
        metadata.create_all(self.engine)

    def begin(self):
        return self.engine.begin()

    def dispose(self) -> None:
        self.engine.dispose()
