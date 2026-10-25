"""Servizi su conti, portafogli, versioni, check-in e avvisi (regole di business sopra l'archivio SQL)."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from .db import Database, alerts, checkins, portfolios, users, versions
from .payload import level_at, target_weights, weight_changes, weight_distance, years_elapsed
from .security import (AccountError, burn_time, hash_password, normalize_email, validate_email, validate_password,
                       verify_password)

MAX_FAILED_LOGINS = 5
LOCK_MINUTES = 15
MAX_PORTFOLIOS = 20
MAX_JSON_BYTES = 400_000
DEFAULT_REVIEW_DAYS = 90
DEFAULT_TOLERANCE = 0.05


@dataclass(frozen=True)
class User:
    id: int
    email: str
    name: str
    locale: str
    email_alerts: bool
    created_at: datetime


@dataclass(frozen=True)
class Portfolio:
    id: int
    user_id: int
    name: str
    status: str
    invested: bool
    start_date: date | None
    review_days: int
    tolerance: float
    current_version: int | None
    ref_weights: dict | None
    ref_level: int | None
    created_at: datetime
    updated_at: datetime
    last_checked_at: datetime | None
    last_reviewed_at: datetime | None


@dataclass(frozen=True)
class Version:
    id: int
    portfolio_id: int
    number: int
    created_at: datetime
    reason: str
    spec: dict
    result: dict


@dataclass(frozen=True)
class Alert:
    id: int
    user_id: int
    portfolio_id: int | None
    created_at: datetime
    kind: str
    payload: dict
    read_at: datetime | None
    emailed_at: datetime | None


@dataclass(frozen=True)
class Checkin:
    id: int
    portfolio_id: int
    on_date: date
    value: float
    note: str


def _json(obj: Any) -> str:
    text = json.dumps(obj, separators=(",", ":"), ensure_ascii=False, default=_default)
    if len(text.encode("utf-8")) > MAX_JSON_BYTES:
        raise AccountError("acct.err.too_large")
    return text


def _default(obj: Any) -> Any:
    if hasattr(obj, "item"):
        return obj.item()
    if hasattr(obj, "tolist"):
        return obj.tolist()
    if isinstance(obj, (date, datetime)):
        return obj.isoformat()
    return str(obj)


def _user(row) -> User:
    return User(row.id, row.email, row.name, row.locale, bool(row.email_alerts), row.created_at)


def _portfolio(row) -> Portfolio:
    return Portfolio(row.id, row.user_id, row.name, row.status, bool(row.invested), row.start_date, row.review_days,
                     row.tolerance, row.current_version, json.loads(row.ref_weights) if row.ref_weights else None,
                     row.ref_level, row.created_at, row.updated_at, row.last_checked_at, row.last_reviewed_at)


def _version(row) -> Version:
    return Version(row.id, row.portfolio_id, row.number, row.created_at, row.reason, json.loads(row.spec),
                   json.loads(row.result))


def _alert(row) -> Alert:
    return Alert(row.id, row.user_id, row.portfolio_id, row.created_at, row.kind, json.loads(row.payload),
                 row.read_at, row.emailed_at)


class Accounts:
    """Conti, portafogli seguiti e avvisi. ``clock`` e ``today`` si possono sostituire nei test."""

    def __init__(self, db: Database, *, clock: Callable[[], datetime] | None = None) -> None:
        self.db = db
        self._clock = clock

    # ------------------------------------------------------------------ tempo
    def now(self) -> datetime:
        return self._clock() if self._clock else datetime.now(timezone.utc).replace(tzinfo=None)

    def today(self) -> date:
        return self.now().date()

    # ------------------------------------------------------------------ utenti
    def register(self, email: str, password: str, name: str = "", locale: str = "en") -> User:
        email = validate_email(email)
        validate_password(password, email)
        values = dict(email=email, name=(name or "").strip()[:80], password_hash=hash_password(password),
                      locale=(locale or "en")[:8], email_alerts=True, created_at=self.now(), failed_logins=0)
        try:
            with self.db.begin() as conn:
                if conn.execute(select(users.c.id).where(users.c.email == email)).first() is not None:
                    raise AccountError("acct.err.email_taken")
                uid = conn.execute(insert(users).values(**values)).inserted_primary_key[0]
        except IntegrityError as exc:                      # registrazioni concorrenti con la stessa email
            raise AccountError("acct.err.email_taken") from exc
        return self.get_user(uid)

    def authenticate(self, email: str, password: str) -> User:
        email = normalize_email(email)
        error: AccountError | None = None
        user: User | None = None
        with self.db.begin() as conn:
            row = conn.execute(select(users).where(users.c.email == email)).first()
            now = self.now()
            if row is None:
                burn_time(password)
                error = AccountError("acct.err.invalid_credentials")
            elif row.locked_until is not None and row.locked_until > now:
                minutes = max(1, math.ceil((row.locked_until - now).total_seconds() / 60))
                error = AccountError("acct.err.locked", minutes=minutes)
            elif verify_password(password, row.password_hash):
                conn.execute(update(users).where(users.c.id == row.id).values(
                    failed_logins=0, locked_until=None, last_login_at=now))
                user = _user(row)
            else:
                failed = int(row.failed_logins or 0) + 1
                values = ({"failed_logins": 0, "locked_until": now + timedelta(minutes=LOCK_MINUTES)}
                          if failed >= MAX_FAILED_LOGINS else {"failed_logins": failed})
                conn.execute(update(users).where(users.c.id == row.id).values(**values))
                error = AccountError("acct.err.invalid_credentials")
        if error is not None:                              # fuori dalla transazione: il contatore resta registrato
            raise error
        return user

    def get_user(self, user_id: int) -> User | None:
        with self.db.begin() as conn:
            row = conn.execute(select(users).where(users.c.id == user_id)).first()
        return _user(row) if row else None

    def update_profile(self, user_id: int, *, name: str | None = None, locale: str | None = None,
                       email_alerts: bool | None = None) -> User:
        values: dict[str, Any] = {}
        if name is not None:
            values["name"] = name.strip()[:80]
        if locale is not None:
            values["locale"] = locale[:8]
        if email_alerts is not None:
            values["email_alerts"] = bool(email_alerts)
        if values:
            with self.db.begin() as conn:
                conn.execute(update(users).where(users.c.id == user_id).values(**values))
        return self.get_user(user_id)

    def change_password(self, user_id: int, old: str, new: str) -> None:
        with self.db.begin() as conn:
            row = conn.execute(select(users).where(users.c.id == user_id)).first()
            if row is None or not verify_password(old, row.password_hash):
                raise AccountError("acct.err.wrong_password")
            validate_password(new, row.email)
            conn.execute(update(users).where(users.c.id == user_id).values(password_hash=hash_password(new)))

    def delete_user(self, user_id: int, password: str) -> None:
        with self.db.begin() as conn:
            row = conn.execute(select(users).where(users.c.id == user_id)).first()
            if row is None or not verify_password(password, row.password_hash):
                raise AccountError("acct.err.wrong_password")
            ids = [r.id for r in conn.execute(select(portfolios.c.id).where(portfolios.c.user_id == user_id))]
            for pid in ids:
                self._delete_children(conn, pid)
            conn.execute(delete(alerts).where(alerts.c.user_id == user_id))
            conn.execute(delete(portfolios).where(portfolios.c.user_id == user_id))
            conn.execute(delete(users).where(users.c.id == user_id))

    # ------------------------------------------------------------------ portafogli
    @staticmethod
    def _clean_name(name: str) -> str:
        name = " ".join((name or "").split())[:80]
        if not name:
            raise AccountError("acct.err.name_required")
        return name

    @staticmethod
    def _delete_children(conn, portfolio_id: int) -> None:
        conn.execute(delete(alerts).where(alerts.c.portfolio_id == portfolio_id))
        conn.execute(delete(checkins).where(checkins.c.portfolio_id == portfolio_id))
        conn.execute(delete(versions).where(versions.c.portfolio_id == portfolio_id))

    def portfolio(self, portfolio_id: int) -> Portfolio | None:
        """Portafoglio per identificativo, senza controllo del proprietario (uso interno: monitor)."""
        with self.db.begin() as conn:
            row = conn.execute(select(portfolios).where(portfolios.c.id == portfolio_id)).first()
        return _portfolio(row) if row else None

    def get_portfolio(self, user_id: int, portfolio_id: int) -> Portfolio:
        pf = self.portfolio(portfolio_id)
        if pf is None or pf.user_id != user_id:
            raise AccountError("acct.err.not_found")
        return pf

    def list_portfolios(self, user_id: int) -> list[Portfolio]:
        with self.db.begin() as conn:
            rows = conn.execute(select(portfolios).where(portfolios.c.user_id == user_id)
                                .order_by(portfolios.c.updated_at.desc(), portfolios.c.id.desc())).all()
        return [_portfolio(r) for r in rows]

    def followed_portfolios(self) -> list[Portfolio]:
        """Portafogli attivi con gli avvisi accesi (di tutti gli utenti): li controlla il monitor."""
        with self.db.begin() as conn:
            rows = conn.execute(select(portfolios).where(portfolios.c.invested.is_(True),
                                                         portfolios.c.status == "active")
                                .order_by(portfolios.c.id)).all()
        return [_portfolio(r) for r in rows]

    def create_portfolio(self, user_id: int, name: str, spec: Mapping, result: Mapping, *, invested: bool = False,
                         today: date | None = None, review_days: int = DEFAULT_REVIEW_DAYS,
                         tolerance: float = DEFAULT_TOLERANCE) -> Portfolio:
        name = self._clean_name(name)
        spec_json, result_json = _json({**spec}), _json({**result, "anchor": 0})
        now = self.now()
        with self.db.begin() as conn:
            count = conn.execute(select(func.count()).select_from(portfolios)
                                 .where(portfolios.c.user_id == user_id)).scalar_one()
            if count >= MAX_PORTFOLIOS:
                raise AccountError("acct.err.limit", max=MAX_PORTFOLIOS)
            pid = conn.execute(insert(portfolios).values(
                user_id=user_id, name=name, status="active", invested=False, review_days=int(review_days),
                tolerance=float(tolerance), current_version=1, created_at=now, updated_at=now)).inserted_primary_key[0]
            conn.execute(insert(versions).values(portfolio_id=pid, number=1, created_at=now, reason="created",
                                                 spec=spec_json, result=result_json))
        if invested:
            self._start_following(pid, today or self.today())
        return self.get_portfolio(user_id, pid)

    def rename_portfolio(self, user_id: int, portfolio_id: int, name: str) -> None:
        self.get_portfolio(user_id, portfolio_id)
        with self.db.begin() as conn:
            conn.execute(update(portfolios).where(portfolios.c.id == portfolio_id)
                         .values(name=self._clean_name(name), updated_at=self.now()))

    def set_alert_options(self, user_id: int, portfolio_id: int, *, review_days: int | None = None,
                          tolerance: float | None = None) -> None:
        self.get_portfolio(user_id, portfolio_id)
        values: dict[str, Any] = {}
        if review_days is not None:
            values["review_days"] = max(7, min(365, int(review_days)))
        if tolerance is not None:
            values["tolerance"] = max(0.01, min(0.5, float(tolerance)))
        if values:
            with self.db.begin() as conn:
                conn.execute(update(portfolios).where(portfolios.c.id == portfolio_id).values(**values))

    def set_invested(self, user_id: int, portfolio_id: int, invested: bool, *, today: date | None = None) -> Portfolio:
        self.get_portfolio(user_id, portfolio_id)
        if invested:
            self._start_following(portfolio_id, today or self.today())
        else:
            with self.db.begin() as conn:
                conn.execute(update(portfolios).where(portfolios.c.id == portfolio_id)
                             .values(invested=False, updated_at=self.now()))
        return self.get_portfolio(user_id, portfolio_id)

    def _start_following(self, portfolio_id: int, today: date) -> None:
        """Attiva gli avvisi: l'inizio dell'investimento è oggi (se non già impostato) e i pesi attuali sono il riferimento."""
        pf = self.portfolio(portfolio_id)
        result = self.current_version(portfolio_id).result
        start = pf.start_date or today
        k = years_elapsed(start, today)
        with self.db.begin() as conn:
            conn.execute(update(portfolios).where(portfolios.c.id == portfolio_id).values(
                invested=True, status="active", start_date=start, ref_weights=_json(target_weights(result, k)),
                ref_level=level_at(result, k), updated_at=self.now()))

    def delete_portfolio(self, user_id: int, portfolio_id: int) -> None:
        self.get_portfolio(user_id, portfolio_id)
        with self.db.begin() as conn:
            self._delete_children(conn, portfolio_id)
            conn.execute(delete(portfolios).where(portfolios.c.id == portfolio_id))

    # ------------------------------------------------------------------ versioni
    def current_version(self, portfolio_id: int) -> Version:
        with self.db.begin() as conn:
            pf = conn.execute(select(portfolios.c.current_version).where(portfolios.c.id == portfolio_id)).first()
            row = conn.execute(select(versions).where(versions.c.portfolio_id == portfolio_id,
                                                      versions.c.number == pf.current_version)).first()
        return _version(row)

    def versions(self, user_id: int, portfolio_id: int) -> list[Version]:
        self.get_portfolio(user_id, portfolio_id)
        with self.db.begin() as conn:
            rows = conn.execute(select(versions).where(versions.c.portfolio_id == portfolio_id)
                                .order_by(versions.c.number.desc())).all()
        return [_version(r) for r in rows]

    def _append_version(self, portfolio_id: int, spec: Mapping, result: Mapping, reason: str) -> Version:
        spec_json, result_json = _json({**spec}), _json({**result})
        now = self.now()
        with self.db.begin() as conn:
            number = int(conn.execute(select(func.max(versions.c.number))
                                      .where(versions.c.portfolio_id == portfolio_id)).scalar_one() or 0) + 1
            conn.execute(insert(versions).values(portfolio_id=portfolio_id, number=number, created_at=now, reason=reason,
                                                 spec=spec_json, result=result_json))
            conn.execute(update(portfolios).where(portfolios.c.id == portfolio_id)
                         .values(current_version=number, updated_at=now))
        return self.current_version(portfolio_id)

    def save_version(self, user_id: int, portfolio_id: int, spec: Mapping, result: Mapping, *,
                     today: date | None = None) -> tuple[Version, Alert | None]:
        """Nuova versione dopo una modifica del piano; se il portafoglio è seguito e i pesi cambiano, crea un avviso."""
        pf = self.get_portfolio(user_id, portfolio_id)
        today = today or self.today()
        k = years_elapsed(pf.start_date, today) if pf.start_date else 0     # il piano prosegue anche se gli avvisi sono spenti
        version = self._append_version(portfolio_id, spec, {**result, "anchor": k}, "edited")
        alert = (self.notify_if_changed(self.portfolio(portfolio_id), version.result, k, "edited", today)
                 if pf.invested else None)
        return version, alert

    def add_review_version(self, portfolio_id: int, spec: Mapping, result: Mapping) -> Version:
        """Nuova versione prodotta dal monitor dopo una revisione automatica."""
        return self._append_version(portfolio_id, spec, result, "reviewed")

    # ------------------------------------------------------------------ avvisi
    def notify_if_changed(self, pf: Portfolio, result: Mapping, k: int, reason: str, as_of: date) -> Alert | None:
        """Confronta i pesi target dell'anno ``k`` con gli ultimi comunicati; se cambiano oltre la soglia crea un avviso."""
        new = target_weights(result, k)
        level = level_at(result, k)
        if pf.ref_weights is None:                           # primo riferimento: nessun avviso
            self._set_reference(pf.id, new, level)
            return None
        if weight_distance(new, pf.ref_weights) < pf.tolerance:
            return None
        payload = {
            "reason": reason, "as_of": as_of.isoformat(), "level_from": pf.ref_level, "level_to": level,
            "changes": weight_changes(pf.ref_weights, new, result.get("names") or {}), "weights": new,
            "names": {k_: result.get("names", {}).get(k_, k_) for k_ in new},
        }
        alert = self.create_alert(pf.user_id, pf.id, "weights", payload)
        self._set_reference(pf.id, new, level)
        return alert

    def _set_reference(self, portfolio_id: int, weights: Mapping[str, float], level: int) -> None:
        with self.db.begin() as conn:
            conn.execute(update(portfolios).where(portfolios.c.id == portfolio_id)
                         .values(ref_weights=_json(dict(weights)), ref_level=int(level)))

    def touch_checked(self, portfolio_id: int, *, reviewed: bool = False, completed: bool = False) -> None:
        values: dict[str, Any] = {"last_checked_at": self.now()}
        if reviewed:
            values["last_reviewed_at"] = self.now()
        if completed:
            values["status"] = "completed"
        with self.db.begin() as conn:
            conn.execute(update(portfolios).where(portfolios.c.id == portfolio_id).values(**values))

    def create_alert(self, user_id: int, portfolio_id: int | None, kind: str, payload: Mapping) -> Alert:
        with self.db.begin() as conn:
            aid = conn.execute(insert(alerts).values(user_id=user_id, portfolio_id=portfolio_id, created_at=self.now(),
                                                     kind=kind, payload=_json(dict(payload)))).inserted_primary_key[0]
            row = conn.execute(select(alerts).where(alerts.c.id == aid)).first()
        return _alert(row)

    def list_alerts(self, user_id: int, *, unread_only: bool = False, limit: int = 50,
                    portfolio_id: int | None = None) -> list[Alert]:
        query = select(alerts).where(alerts.c.user_id == user_id)
        if unread_only:
            query = query.where(alerts.c.read_at.is_(None))
        if portfolio_id is not None:
            query = query.where(alerts.c.portfolio_id == portfolio_id)
        with self.db.begin() as conn:
            rows = conn.execute(query.order_by(alerts.c.created_at.desc(), alerts.c.id.desc()).limit(limit)).all()
        return [_alert(r) for r in rows]

    def unread_count(self, user_id: int) -> int:
        with self.db.begin() as conn:
            return int(conn.execute(select(func.count()).select_from(alerts).where(
                alerts.c.user_id == user_id, alerts.c.read_at.is_(None))).scalar_one())

    def mark_read(self, user_id: int, ids: list[int] | None = None) -> None:
        query = update(alerts).where(alerts.c.user_id == user_id, alerts.c.read_at.is_(None))
        if ids is not None:
            query = query.where(alerts.c.id.in_(list(ids)))
        with self.db.begin() as conn:
            conn.execute(query.values(read_at=self.now()))

    def mark_emailed(self, alert_id: int) -> None:
        with self.db.begin() as conn:
            conn.execute(update(alerts).where(alerts.c.id == alert_id).values(emailed_at=self.now()))

    # ------------------------------------------------------------------ check-in del valore reale
    def add_checkin(self, user_id: int, portfolio_id: int, value: float, on_date: date | None = None,
                    note: str = "") -> Checkin:
        self.get_portfolio(user_id, portfolio_id)
        if not value >= 0 or not math.isfinite(value):
            raise AccountError("acct.err.invalid_value")
        on_date = on_date or self.today()
        with self.db.begin() as conn:
            cid = conn.execute(insert(checkins).values(portfolio_id=portfolio_id, on_date=on_date, value=float(value),
                                                       note=(note or "")[:200], created_at=self.now())).inserted_primary_key[0]
            row = conn.execute(select(checkins).where(checkins.c.id == cid)).first()
        return Checkin(row.id, row.portfolio_id, row.on_date, row.value, row.note)

    def checkins(self, user_id: int, portfolio_id: int) -> list[Checkin]:
        self.get_portfolio(user_id, portfolio_id)
        return self._checkins(portfolio_id)

    def _checkins(self, portfolio_id: int) -> list[Checkin]:
        with self.db.begin() as conn:
            rows = conn.execute(select(checkins).where(checkins.c.portfolio_id == portfolio_id)
                                .order_by(checkins.c.on_date.desc(), checkins.c.id.desc())).all()
        return [Checkin(r.id, r.portfolio_id, r.on_date, r.value, r.note) for r in rows]

    def latest_checkin(self, portfolio_id: int, after: date | None = None) -> Checkin | None:
        for item in self._checkins(portfolio_id):
            if after is None or item.on_date >= after:
                return item
        return None
