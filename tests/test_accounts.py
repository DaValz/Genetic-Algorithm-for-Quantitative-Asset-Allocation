"""Test dei conti, dei portafogli seguiti, degli avvisi sui pesi, delle email e del monitor."""
import html
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select

from goalga import i18n
from goalga.accounts import AccountError, Accounts, Database, monitor, notify
from goalga.accounts.db import users
from goalga.accounts.messages import describe
from goalga.accounts.payload import (SOURCE_LABEL, anniversary, elapsed_years, fan_position, fan_value, is_completed,
                                     level_at, projected_wealth, result_payload, target_weights, weight_changes,
                                     weight_distance, year_fraction, years_elapsed)
from goalga.accounts.service import MAX_PORTFOLIOS
from goalga.data import PriceData
from goalga.pipeline import optimize, plan_to_spec, prepare_market, spec_plan, spec_settings
from goalga.plan import Plan
from goalga.risk import profile_caps
from goalga.universe import DEFAULT_ETF_SELECTION

TICKERS = ["BND", "MIX", "EQ"]
LEVELS = [[1.0, 0.0, 0.0], [0.6, 0.4, 0.0], [0.2, 0.3, 0.5]]        # P1, P2, P3
PLAN = Plan(w0=20_000, contribution=3_000, horizon=5, goals=((3, 15_000.0), (5, 40_000.0)), pr_target=0.9, alpha=0.05)
PASSWORD = "correct horse battery"


def synthetic_result(path=(3, 3, 2, 2, 1), anchor=0, levels=LEVELS):
    n = len(path)
    return {
        "v": 1, "anchor": anchor, "horizon": n, "tickers": list(TICKERS), "names": {t: f"Fondo {t}" for t in TICKERS},
        "levels": [list(level) for level in levels], "path": list(path), "risk": "balanced", "max_level": 3,
        "metrics": {"pr": 0.95, "oos_pr": 0.94, "irr_es": 0.03, "required": 0.04, "expected_return": 0.05,
                    "generations": 50, "feasible": True},
        "fan": {"p5": [20_000.0 + 1_000 * i for i in range(n + 1)], "p50": [20_000.0 + 5_000 * i for i in range(n + 1)],
                "p95": [20_000.0 + 9_000 * i for i in range(n + 1)]},
        "data": {"source": SOURCE_LABEL, "start": "2010-01", "end": "2026-09"}, "created": "2026-10-24",
    }


def synthetic_spec(source="file"):
    return {"v": 1, "plan": plan_to_spec(PLAN, ["casa", "pensione"]), "risk": "balanced", "advanced": False,
            "market": {"source": source}, "ga": {}}


class Clock:
    def __init__(self, start=datetime(2026, 10, 24, 9, 0)):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, **kwargs):
        self.now += timedelta(**kwargs)


@pytest.fixture()
def clock():
    return Clock()


@pytest.fixture()
def accounts(tmp_path, clock):
    db = Database(f"sqlite:///{(tmp_path / 'accounts.db').as_posix()}")
    yield Accounts(db, clock=clock)
    db.dispose()


@pytest.fixture()
def user(accounts):
    return accounts.register("Mario.Rossi@Example.com", PASSWORD, "Mario", locale="it")


class Recorder:
    """Notificatore di prova: registra le email e può simulare un invio fallito."""

    def __init__(self, ok=True):
        self.sent, self.ok = [], ok

    def send(self, to, subject, text, html_body):
        self.sent.append((to, subject, text, html_body))
        return self.ok


# ------------------------------------------------------------------ registrazione e accesso
def test_register_normalizes_the_email_and_never_stores_the_password(accounts, user):
    assert user.email == "mario.rossi@example.com" and user.name == "Mario" and user.email_alerts
    with accounts.db.begin() as conn:
        stored = conn.execute(select(users.c.password_hash)).scalar_one()
    assert stored.startswith(("scrypt$", "pbkdf2$")) and PASSWORD not in stored


@pytest.mark.parametrize("args, key", [
    (("MARIO.ROSSI@example.com", PASSWORD), "acct.err.email_taken"),
    (("not-an-email", PASSWORD), "acct.err.invalid_email"),
    (("a@b", PASSWORD), "acct.err.invalid_email"),
    (("new@example.com", "short"), "acct.err.weak_password"),
    (("new@example.com", "password"), "acct.err.weak_password"),
    (("longuser@example.com", "LongUser"), "acct.err.weak_password"),
    (("new@example.com", "x" * 200), "acct.err.weak_password"),
])
def test_register_rejects_duplicates_bad_emails_and_weak_passwords(accounts, user, args, key):
    with pytest.raises(AccountError) as info:
        accounts.register(*args)
    assert info.value.key == key


def test_authenticate_gives_the_same_error_for_unknown_email_and_wrong_password(accounts, user):
    assert accounts.authenticate(" MARIO.rossi@example.com ", PASSWORD).id == user.id
    for email, password in (("nobody@example.com", PASSWORD), (user.email, "wrong password!")):
        with pytest.raises(AccountError) as info:
            accounts.authenticate(email, password)
        assert info.value.key == "acct.err.invalid_credentials"


def test_five_failed_logins_lock_the_account_for_fifteen_minutes(accounts, user, clock):
    for _ in range(5):
        with pytest.raises(AccountError):
            accounts.authenticate(user.email, "bad password!")
    with pytest.raises(AccountError) as info:
        accounts.authenticate(user.email, PASSWORD)           # anche la password giusta è rifiutata
    assert info.value.key == "acct.err.locked" and info.value.params["minutes"] == 15
    clock.advance(minutes=14)
    with pytest.raises(AccountError):
        accounts.authenticate(user.email, PASSWORD)
    clock.advance(minutes=2)
    assert accounts.authenticate(user.email, PASSWORD).id == user.id


def test_a_successful_login_resets_the_failure_counter(accounts, user):
    for _ in range(4):
        with pytest.raises(AccountError):
            accounts.authenticate(user.email, "bad password!")
    accounts.authenticate(user.email, PASSWORD)
    for _ in range(4):
        with pytest.raises(AccountError):
            accounts.authenticate(user.email, "bad password!")
    assert accounts.authenticate(user.email, PASSWORD).id == user.id


def test_profile_and_password_changes(accounts, user):
    updated = accounts.update_profile(user.id, name="  Maria  ", locale="fr", email_alerts=False)
    assert (updated.name, updated.locale, updated.email_alerts) == ("Maria", "fr", False)
    with pytest.raises(AccountError) as info:
        accounts.change_password(user.id, "wrong password!", "another good password")
    assert info.value.key == "acct.err.wrong_password"
    with pytest.raises(AccountError):
        accounts.change_password(user.id, PASSWORD, "short")
    accounts.change_password(user.id, PASSWORD, "another good password")
    assert accounts.authenticate(user.email, "another good password").id == user.id
    with pytest.raises(AccountError):
        accounts.authenticate(user.email, PASSWORD)


def test_deleting_an_account_removes_everything_it_owned(accounts, user):
    pf = accounts.create_portfolio(user.id, "Piano", synthetic_spec(), synthetic_result(), invested=True)
    accounts.create_alert(user.id, pf.id, "weights", {"changes": []})
    with pytest.raises(AccountError):
        accounts.delete_user(user.id, "wrong password!")
    accounts.delete_user(user.id, PASSWORD)
    assert accounts.get_user(user.id) is None and accounts.portfolio(pf.id) is None
    assert accounts.list_alerts(user.id) == [] and accounts.followed_portfolios() == []
    with pytest.raises(AccountError):
        accounts.authenticate(user.email, PASSWORD)


# ------------------------------------------------------------------ portafogli
def test_create_list_rename_and_delete_portfolios(accounts, user):
    other = accounts.register("other@example.com", PASSWORD)
    pf = accounts.create_portfolio(user.id, "  Casa   e   pensione ", synthetic_spec(), synthetic_result())
    assert pf.name == "Casa e pensione" and pf.current_version == 1 and not pf.invested and pf.start_date is None
    assert accounts.current_version(pf.id).reason == "created" and accounts.current_version(pf.id).number == 1
    accounts.rename_portfolio(user.id, pf.id, "Piano B")
    assert [p.name for p in accounts.list_portfolios(user.id)] == ["Piano B"]
    for action in (lambda: accounts.get_portfolio(other.id, pf.id), lambda: accounts.rename_portfolio(other.id, pf.id, "x"),
                   lambda: accounts.delete_portfolio(other.id, pf.id), lambda: accounts.versions(other.id, pf.id)):
        with pytest.raises(AccountError) as info:
            action()
        assert info.value.key == "acct.err.not_found", "un utente non vede i portafogli degli altri"
    with pytest.raises(AccountError) as info:
        accounts.create_portfolio(user.id, "   ", synthetic_spec(), synthetic_result())
    assert info.value.key == "acct.err.name_required"
    accounts.delete_portfolio(user.id, pf.id)
    assert accounts.list_portfolios(user.id) == [] and accounts.portfolio(pf.id) is None


def test_limits_on_portfolios_and_payload_size(accounts, user):
    for i in range(MAX_PORTFOLIOS):
        accounts.create_portfolio(user.id, f"P{i}", synthetic_spec(), synthetic_result())
    with pytest.raises(AccountError) as info:
        accounts.create_portfolio(user.id, "one too many", synthetic_spec(), synthetic_result())
    assert info.value.key == "acct.err.limit"
    other = accounts.register("other@example.com", PASSWORD)
    huge = {**synthetic_result(), "blob": "x" * 500_000}
    with pytest.raises(AccountError) as info:
        accounts.create_portfolio(other.id, "huge", synthetic_spec(), huge)
    assert info.value.key == "acct.err.too_large"


def test_following_a_portfolio_sets_the_start_date_and_the_reference_weights(accounts, user, clock):
    pf = accounts.create_portfolio(user.id, "Piano", synthetic_spec(), synthetic_result())
    assert accounts.followed_portfolios() == []
    followed = accounts.set_invested(user.id, pf.id, True)
    assert followed.invested and followed.start_date == date(2026, 10, 24) and followed.ref_level == 3
    assert followed.ref_weights == pytest.approx({"BND": 0.2, "MIX": 0.3, "EQ": 0.5})
    assert [p.id for p in accounts.followed_portfolios()] == [pf.id]
    clock.advance(days=400)
    again = accounts.set_invested(user.id, pf.id, True)
    assert again.start_date == date(2026, 10, 24), "riattivare gli avvisi non sposta l'inizio dell'investimento"
    assert not accounts.set_invested(user.id, pf.id, False).invested and accounts.followed_portfolios() == []


def test_alert_options_are_clamped(accounts, user):
    pf = accounts.create_portfolio(user.id, "Piano", synthetic_spec(), synthetic_result())
    accounts.set_alert_options(user.id, pf.id, review_days=1, tolerance=0.9)
    assert (accounts.portfolio(pf.id).review_days, accounts.portfolio(pf.id).tolerance) == (7, 0.5)
    accounts.set_alert_options(user.id, pf.id, review_days=9999, tolerance=0.0)
    assert (accounts.portfolio(pf.id).review_days, accounts.portfolio(pf.id).tolerance) == (365, 0.01)
    accounts.set_alert_options(user.id, pf.id, review_days=45, tolerance=0.08)
    assert (accounts.portfolio(pf.id).review_days, accounts.portfolio(pf.id).tolerance) == (45, 0.08)


# ------------------------------------------------------------------ versioni e avvisi sui pesi
def test_editing_a_portfolio_creates_a_version_and_alerts_only_if_it_is_followed(accounts, user):
    pf = accounts.create_portfolio(user.id, "Piano", synthetic_spec(), synthetic_result())
    version, alert = accounts.save_version(user.id, pf.id, synthetic_spec(), synthetic_result(path=(1, 1, 1, 1, 1)))
    assert version.number == 2 and version.reason == "edited" and alert is None, "non investito: nessun avviso"
    accounts.set_invested(user.id, pf.id, True)                 # ora il riferimento è P1 (100% BND)
    _, alert = accounts.save_version(user.id, pf.id, synthetic_spec(), synthetic_result(path=(3, 3, 3, 3, 3)))
    assert alert is not None and alert.kind == "weights" and alert.payload["reason"] == "edited"
    assert (alert.payload["level_from"], alert.payload["level_to"]) == (1, 3)
    changes = {c["ticker"]: (c["old"], c["new"]) for c in alert.payload["changes"]}
    assert changes == {"BND": (1.0, pytest.approx(0.2)), "MIX": (0.0, pytest.approx(0.3)), "EQ": (0.0, pytest.approx(0.5))}
    assert alert.payload["changes"][0]["ticker"] == "BND", "prima la variazione più ampia"
    assert accounts.portfolio(pf.id).ref_level == 3 and accounts.unread_count(user.id) == 1
    _, again = accounts.save_version(user.id, pf.id, synthetic_spec(), synthetic_result(path=(3, 3, 3, 3, 3)))
    assert again is None, "stessi pesi di prima: nessun nuovo avviso"
    assert [v.number for v in accounts.versions(user.id, pf.id)] == [4, 3, 2, 1]


def test_the_clock_of_the_plan_keeps_running_while_the_alerts_are_off(accounts, user, clock):
    """Un portafoglio già avviato, con gli avvisi spenti, non riparte dall'anno 1 quando lo si modifica."""
    pf = accounts.create_portfolio(user.id, "Piano", synthetic_spec(), synthetic_result(), invested=True,
                                   today=date(2026, 10, 24))
    accounts.set_invested(user.id, pf.id, False)
    version, alert = accounts.save_version(user.id, pf.id, synthetic_spec(), synthetic_result(anchor=0),
                                           today=date(2028, 11, 1))
    assert version.result["anchor"] == 2 and alert is None
    never = accounts.create_portfolio(user.id, "Mai seguito", synthetic_spec(), synthetic_result())
    assert accounts.save_version(user.id, never.id, synthetic_spec(), synthetic_result(),
                                 today=date(2030, 1, 1))[0].result["anchor"] == 0, "se non è mai partito l'anno è il primo"


def test_changes_below_the_tolerance_do_not_alert(accounts, user):
    pf = accounts.create_portfolio(user.id, "Piano", synthetic_spec(), synthetic_result(), invested=True)
    nudged = [list(level) for level in LEVELS]
    nudged[2] = [0.17, 0.30, 0.53]                              # 3 punti percentuali al massimo: sotto la soglia del 5%
    _, alert = accounts.save_version(user.id, pf.id, synthetic_spec(), synthetic_result(levels=nudged))
    assert alert is None and accounts.list_alerts(user.id) == []
    accounts.set_alert_options(user.id, pf.id, tolerance=0.02)
    nudged[2] = [0.12, 0.30, 0.58]
    _, alert = accounts.save_version(user.id, pf.id, synthetic_spec(), synthetic_result(levels=nudged))
    assert alert is not None, "con una soglia più stretta lo stesso scostamento avvisa"


def test_alert_inbox(accounts, user):
    pf = accounts.create_portfolio(user.id, "Piano", synthetic_spec(), synthetic_result())
    ids = [accounts.create_alert(user.id, pf.id, "weights", {"n": i}).id for i in range(3)]
    assert accounts.unread_count(user.id) == 3
    assert [a.payload["n"] for a in accounts.list_alerts(user.id)] == [2, 1, 0], "dal più recente"
    accounts.mark_read(user.id, [ids[0]])
    assert accounts.unread_count(user.id) == 2 and len(accounts.list_alerts(user.id, unread_only=True)) == 2
    assert len(accounts.list_alerts(user.id, portfolio_id=pf.id, limit=1)) == 1
    accounts.mark_read(user.id)
    assert accounts.unread_count(user.id) == 0
    other = accounts.register("other@example.com", PASSWORD)
    assert accounts.unread_count(other.id) == 0 and accounts.list_alerts(other.id) == []


def test_checkins_record_the_real_value(accounts, user, clock):
    pf = accounts.create_portfolio(user.id, "Piano", synthetic_spec(), synthetic_result(), invested=True)
    for bad in (-1.0, float("nan"), float("inf")):
        with pytest.raises(AccountError) as info:
            accounts.add_checkin(user.id, pf.id, bad)
        assert info.value.key == "acct.err.invalid_value"
    first = accounts.add_checkin(user.id, pf.id, 21_500.0, note="primo")
    clock.advance(days=200)
    second = accounts.add_checkin(user.id, pf.id, 26_000.0)
    assert [c.value for c in accounts.checkins(user.id, pf.id)] == [26_000.0, 21_500.0]
    assert accounts.latest_checkin(pf.id).id == second.id and first.note == "primo"
    assert accounts.latest_checkin(pf.id, after=date(2027, 12, 1)) is None


# ------------------------------------------------------------------ calcoli sul contenuto salvato
def test_payload_helpers():
    result = synthetic_result()
    assert years_elapsed(date(2026, 10, 24), date(2027, 10, 23)) == 0
    assert years_elapsed(date(2026, 10, 24), date(2027, 10, 24)) == 1
    assert years_elapsed(date(2026, 10, 24), date(2020, 1, 1)) == 0
    assert [level_at(result, k) for k in range(7)] == [3, 3, 2, 2, 1, 1, 1], "dopo l'orizzonte resta l'ultimo livello"
    assert target_weights(result, 4) == {"BND": 1.0} and target_weights(result, 0) == pytest.approx(
        {"BND": 0.2, "MIX": 0.3, "EQ": 0.5})
    assert not is_completed(result, 4) and is_completed(result, 5)
    later = synthetic_result(anchor=2)
    assert level_at(later, 2) == 3 and level_at(later, 4) == 2 and is_completed(later, 7) and not is_completed(later, 6)
    assert weight_distance({"a": 0.5, "b": 0.5}, {"a": 0.4, "c": 0.6}) == pytest.approx(0.6)
    assert weight_distance(None, None) == 0.0
    rows = weight_changes({"a": 0.5, "b": 0.5, "d": 0.0}, {"a": 0.52, "b": 0.28, "c": 0.2, "d": 0.004}, {"b": "Beta"})
    assert [(r["ticker"], r["name"]) for r in rows] == [("b", "Beta"), ("c", "c"), ("a", "a")], \
        "dalla più ampia; scarta le variazioni trascurabili"
    assert projected_wealth(result, 2) == 30_000.0 and projected_wealth(later, 2) == 20_000.0
    assert projected_wealth({"anchor": 0}, 1) is None


# ------------------------------------------------------------------ tempo: anniversari, frazioni d'anno, patrimonio atteso
def test_anniversaries_and_the_fraction_of_the_year():
    start = date(2026, 10, 24)
    assert anniversary(start, 2) == date(2028, 10, 24) and anniversary(date(2024, 2, 29), 1) == date(2025, 3, 1)
    assert anniversary(date(2024, 2, 29), 4) == date(2028, 2, 29)
    assert year_fraction(start, start) == 0.0 and year_fraction(start, date(2020, 1, 1)) == 0.0
    assert year_fraction(start, date(2027, 4, 24)) == pytest.approx(182 / 365)
    assert year_fraction(start, date(2027, 10, 23)) == pytest.approx(364 / 365)
    assert year_fraction(start, date(2027, 10, 24)) == 0.0, "all'anniversario si riparte da zero"
    assert elapsed_years(start, date(2029, 4, 24)) == pytest.approx(2 + 182 / 365)
    assert year_fraction(date(2024, 2, 29), date(2025, 2, 28)) < 1.0


def test_the_expected_wealth_is_interpolated_between_the_flows_of_the_plan():
    result = synthetic_result()                              # mediana 20.000 + 5.000 per anno, dopo i flussi
    net = PLAN.flows().net                                   # versamenti meno obiettivi di ogni anno
    assert net.tolist() == [3_000, 3_000, -12_000, 3_000, -40_000]
    assert [fan_position(result, t) for t in (-1, 0, 2.5, 5, 9)] == [0, 0, 2.5, 5, 5]
    assert fan_value(result, "p50", 2) == 30_000 and fan_value(result, "p50", 3) == 35_000
    assert fan_value(result, "p50", 2.5, net) == pytest.approx(0.5 * 30_000 + 0.5 * (35_000 + 12_000)), \
        "prima dell'obiettivo del terzo anno il patrimonio è ancora quello pre-flusso"
    assert fan_value(result, "p50", 2.5) == pytest.approx(32_500), "senza i flussi: interpolazione lineare"
    assert fan_value({"anchor": 0}, "p50", 1) is None
    midyear = {**synthetic_result(anchor=2), "first_period": 0.4}            # versione creata a 2,6 anni dall'inizio
    assert [fan_position(midyear, t) for t in (1, 2.6, 2.8, 3, 4.5)] == pytest.approx([0, 0, 0.5, 1, 2.5])
    assert fan_value(midyear, "p50", 2.8, net) == pytest.approx(0.5 * 20_000 + 0.5 * (25_000 - 3_000))


# ------------------------------------------------------------------ monitor: passaggi del glide path
def test_scheduled_glide_path_step_creates_an_alert(accounts, user):
    pf = accounts.create_portfolio(user.id, "Piano", synthetic_spec("file"), synthetic_result(), invested=True)
    sent = Recorder()
    quiet = monitor.check_portfolio(accounts, pf.id, as_of=date(2027, 3, 1), notifier=sent)
    assert quiet.status == "ok" and quiet.year == 0 and quiet.alert_id is None and not sent.sent
    step = monitor.check_portfolio(accounts, pf.id, as_of=date(2028, 10, 24), notifier=sent, app_url="https://app.test")
    assert step.status == "ok" and step.year == 2 and not step.reviewed and step.emailed
    alert = accounts.list_alerts(user.id)[0]
    assert alert.payload["reason"] == "scheduled" and (alert.payload["level_from"], alert.payload["level_to"]) == (3, 2)
    assert len(sent.sent) == 1 and sent.sent[0][0] == user.email and "https://app.test" in sent.sent[0][2]
    assert accounts.list_alerts(user.id)[0].emailed_at is not None
    again = monitor.check_portfolio(accounts, pf.id, as_of=date(2028, 11, 1), notifier=sent)
    assert again.alert_id is None, "lo stesso passaggio non viene comunicato due volte"


def test_completed_plan_sends_a_final_alert_and_stops_being_followed(accounts, user):
    pf = accounts.create_portfolio(user.id, "Piano", synthetic_spec("file"), synthetic_result(), invested=True)
    out = monitor.check_portfolio(accounts, pf.id, as_of=date(2031, 10, 24), notifier=Recorder())
    assert out.status == "completed" and accounts.portfolio(pf.id).status == "completed"
    assert accounts.list_alerts(user.id)[0].kind == "completed" and accounts.followed_portfolios() == []


def test_monitor_skips_portfolios_that_are_not_followed(accounts, user):
    pf = accounts.create_portfolio(user.id, "Piano", synthetic_spec("file"), synthetic_result())
    assert monitor.check_portfolio(accounts, pf.id, as_of=date(2030, 1, 1)).status == "skipped"
    assert monitor.check_portfolio(accounts, 12345).status == "skipped"
    assert monitor.run_checks(accounts, as_of=date(2030, 1, 1)) == []


def test_email_is_not_sent_when_the_user_turned_alerts_off_or_delivery_fails(accounts, user):
    pf = accounts.create_portfolio(user.id, "Piano", synthetic_spec("file"), synthetic_result(), invested=True)
    failing = Recorder(ok=False)
    out = monitor.check_portfolio(accounts, pf.id, as_of=date(2028, 10, 24), notifier=failing)
    assert out.alert_id is not None and not out.emailed and len(failing.sent) == 1
    assert accounts.list_alerts(user.id)[0].emailed_at is None, "invio fallito: l'avviso resta solo nell'app"
    accounts.update_profile(user.id, email_alerts=False)
    pf2 = accounts.create_portfolio(user.id, "Altro", synthetic_spec("file"), synthetic_result(), invested=True)
    quiet = Recorder()
    out = monitor.check_portfolio(accounts, pf2.id, as_of=date(2028, 10, 24), notifier=quiet)
    assert out.alert_id is not None and quiet.sent == []


def test_a_failing_portfolio_does_not_stop_the_others(accounts, user, monkeypatch):
    good = accounts.create_portfolio(user.id, "Buono", synthetic_spec("file"), synthetic_result(), invested=True)
    bad = accounts.create_portfolio(user.id, "Guasto", synthetic_spec("file"), synthetic_result(), invested=True)
    real = monitor.check_portfolio

    def flaky(acc, pid, **kwargs):
        if pid == bad.id:
            raise RuntimeError("boom")
        return real(acc, pid, **kwargs)

    monkeypatch.setattr(monitor, "check_portfolio", flaky)
    outcomes = monitor.run_checks(accounts, as_of=date(2028, 10, 24), notifier=Recorder())
    assert {o.portfolio_id: o.status for o in outcomes} == {good.id: "ok", bad.id: "error"}
    assert "boom" in next(o for o in outcomes if o.status == "error").error
    only = monitor.run_checks(accounts, as_of=date(2028, 10, 24), notifier=Recorder(), only=[good.id])
    assert [o.portfolio_id for o in only] == [good.id]


def test_caching_loader_downloads_each_universe_once():
    calls = []
    load = monitor.caching_loader(lambda tickers, years: calls.append((tuple(tickers), years)) or "data")
    assert load(["A", "B"], 20) == load(["A", "B"], 20) == "data" and len(calls) == 1
    load(["A"], 20)
    load(["A", "B"], 10)
    assert len(calls) == 3


def test_review_is_due_after_the_review_period(accounts, user):
    pf = accounts.create_portfolio(user.id, "Piano", synthetic_spec(), synthetic_result())
    version = accounts.current_version(pf.id)
    assert not monitor.review_due(pf, version, date(2027, 1, 21)) and monitor.review_due(pf, version, date(2027, 1, 22))


# ------------------------------------------------------------------ monitor: rilancio dell'algoritmo con dati aggiornati
def fake_loader(end):
    def load(tickers, years):
        idx = pd.bdate_range(end=end, periods=252 * 20)
        cols = {}
        for k, name in enumerate(tickers):
            rng = np.random.default_rng(1000 + sum(map(ord, name)))
            cols[name] = 100 * np.exp(np.cumsum(rng.normal(0.00025 + 0.00003 * (k % 6), 0.003 + 0.0016 * (k % 7), len(idx))))
        return PriceData(pd.DataFrame(cols, index=idx), {})
    return load


POOL = [*DEFAULT_ETF_SELECTION, "AAPL", "MSFT", "JNJ", "XOM"]       # fondi e quattro titoli (cesta)


def real_spec(source="market"):
    market = {"source": source, "universe": list(POOL), "years": 20, "min_years": 10, "max_weight": 0.4,
              "shrinkage": True, "method": "annual", "cma": None, "custom_weights": False}
    if source == "market":
        market.update(stock_share=0.3, stock_max=0.6, class_caps=True, assumptions={})
    return {"v": 2 if source == "market" else 1, "plan": plan_to_spec(PLAN, ["casa", "pensione"]), "risk": "balanced",
            "advanced": False, "market": market,
            "ga": {"pop_size": 30, "p_c": 0.55, "p_m": 0.3, "mut_v": 2, "patience": 12, "max_generations": 60,
                   "elitism": 1, "seed": 7, "n_scenarios": 300, "oos_n": 0}}


def real_result(spec, as_of):
    market, _ = prepare_market(spec, loader=fake_loader(as_of), as_of=pd.Timestamp(as_of))
    cap = profile_caps(market.n_portfolios)["balanced"]
    out = optimize(PLAN, market, spec_settings(spec), max_level=cap, record=False, validate=False)
    return result_payload(out.report, market, PLAN, names={}, source=SOURCE_LABEL, risk="balanced", max_level=cap,
                          as_of=as_of)


def test_review_reruns_the_algorithm_with_fresh_data_and_saves_a_new_version(accounts, user):
    start, later = date(2026, 10, 24), date(2027, 2, 1)
    spec = real_spec()
    pf = accounts.create_portfolio(user.id, "Reale", spec, real_result(spec, start), invested=True, today=start)
    out = monitor.check_portfolio(accounts, pf.id, as_of=later, loader=fake_loader(later), notifier=Recorder())
    assert out.status == "ok" and out.reviewed, out.error
    version = accounts.current_version(pf.id)
    assert version.number == 2 and version.reason == "reviewed" and version.result["anchor"] == 0
    assert accounts.portfolio(pf.id).last_reviewed_at is not None
    assert level_at(version.result, 0) <= 6, "il profilo scelto (equilibrato) resta rispettato"
    assert set(version.result["tickers"]) == set(POOL), "la revisione non rimescola gli asset: il pool è quello salvato"


def test_review_still_works_for_portfolios_saved_before_the_universe_existed(accounts, user):
    start, later = date(2026, 10, 24), date(2027, 2, 1)
    spec = real_spec("yahoo")
    pf = accounts.create_portfolio(user.id, "Vecchio", spec, real_result(spec, start), invested=True, today=start)
    out = monitor.check_portfolio(accounts, pf.id, as_of=later, loader=fake_loader(later), notifier=Recorder())
    assert out.status == "ok" and out.reviewed, out.error


def test_review_starts_from_the_latest_checkin_and_the_remaining_plan(accounts, user, monkeypatch):
    start, later = date(2026, 10, 24), date(2028, 11, 1)
    spec = real_spec()
    pf = accounts.create_portfolio(user.id, "Reale", spec, real_result(spec, start), invested=True, today=start)
    accounts.add_checkin(user.id, pf.id, 41_000.0, on_date=date(2028, 10, 30))
    seen = {}
    real_optimize = monitor.optimize

    def spy(plan, market, settings, **kwargs):
        seen["plan"], seen["cap"] = plan, kwargs.get("max_level")
        return real_optimize(plan, market, settings, **kwargs)

    monkeypatch.setattr(monitor, "optimize", spy)
    out = monitor.check_portfolio(accounts, pf.id, as_of=later, loader=fake_loader(later), notifier=Recorder())
    assert out.status == "ok" and out.reviewed and out.year == 2, out.error
    remaining = seen["plan"]
    assert remaining.w0 == pytest.approx(41_000.0, abs=150), "il valore registrato due giorni prima vale il patrimonio di oggi"
    assert remaining.horizon == 3 and [y for y, _ in remaining.goals] == [1, 3]
    assert remaining.first_period == pytest.approx(1 - 8 / 365), "il piano riparte da otto giorni dopo l'anniversario"
    version = accounts.current_version(pf.id)
    assert version.result["anchor"] == 2 and version.result["first_period"] == pytest.approx(1 - 8 / 365)
    assert version.spec["plan"]["first_period"] == pytest.approx(1 - 8 / 365)


def test_a_review_in_the_middle_of_a_year_gives_a_partial_first_year(accounts, user):
    start, later = date(2026, 10, 24), date(2027, 5, 1)
    spec = real_spec()
    pf = accounts.create_portfolio(user.id, "Reale", spec, real_result(spec, start), invested=True, today=start)
    out = monitor.check_portfolio(accounts, pf.id, as_of=later, loader=fake_loader(later), notifier=Recorder(), force=True)
    assert out.reviewed, out.error
    result = accounts.current_version(pf.id).result
    assert result["anchor"] == 0 and result["first_period"] == pytest.approx(1 - 189 / 365)
    assert result["created"] == "2027-05-01" and result["horizon"] == 5, "il piano ha ancora cinque flussi"


def test_the_last_plan_year_has_nothing_left_to_review_and_is_not_an_error(accounts, user):
    start, later = date(2026, 10, 24), date(2030, 11, 1)
    spec = real_spec()
    pf = accounts.create_portfolio(user.id, "Reale", spec, real_result(spec, start), invested=True, today=start)
    out = monitor.check_portfolio(accounts, pf.id, as_of=later, notifier=Recorder(), force=True)
    assert out.status == "ok" and not out.reviewed and out.error == "" and out.year == 4
    assert accounts.current_version(pf.id).number == 1


# ------------------------------------------------------------------ patrimonio di partenza della revisione
def _followed(accounts, user, result=None):
    pf = accounts.create_portfolio(user.id, "Piano", synthetic_spec(), result or synthetic_result(), invested=True,
                                   today=date(2026, 10, 24))
    version = accounts.current_version(pf.id)
    return pf, version, spec_plan(version.spec)


def test_a_checkin_taken_before_an_anniversary_is_not_mistaken_for_the_wealth_after_it(accounts, user):
    """Prima del terzo anniversario (24/10/2029) il patrimonio non ha ancora pagato l'obiettivo da 15.000."""
    pf, version, plan = _followed(accounts, user)
    checkin = accounts.add_checkin(user.id, pf.id, 41_000.0, on_date=date(2029, 10, 22))
    wealth, source = monitor.estimate_wealth(pf, version, plan, checkin, date(2029, 10, 26))
    assert source == "checkin" and wealth == pytest.approx(41_000 - 12_000, abs=300), \
        "versamento di 3.000 meno obiettivo di 15.000 tra il valore registrato e la revisione"
    after = accounts.add_checkin(user.id, pf.id, 29_000.0, on_date=date(2029, 10, 25))
    wealth, _ = monitor.estimate_wealth(pf, version, plan, after, date(2029, 10, 26))
    assert wealth == pytest.approx(29_000, abs=150), "un valore registrato dopo l'anniversario vale così com'è"


def test_without_a_recent_checkin_the_review_starts_from_the_expected_median(accounts, user):
    pf, version, plan = _followed(accounts, user)
    wealth, source = monitor.estimate_wealth(pf, version, plan, None, date(2028, 10, 24))
    assert source == "projection" and wealth == pytest.approx(30_000)
    old = accounts.add_checkin(user.id, pf.id, 99_000.0, on_date=date(2027, 1, 5))
    wealth, source = monitor.estimate_wealth(pf, version, plan, old, date(2028, 10, 24))
    assert source == "projection" and wealth == pytest.approx(30_000), "oltre 400 giorni il valore non è più attendibile"
    future = accounts.add_checkin(user.id, pf.id, 99_000.0, on_date=date(2028, 12, 1))
    assert monitor.estimate_wealth(pf, version, plan, future, date(2028, 10, 24))[1] == "projection"
    before_start = type(old)(old.id, old.portfolio_id, date(2026, 9, 1), 99_000.0, "")
    assert monitor.estimate_wealth(pf, version, plan, before_start, date(2028, 10, 24))[1] == "projection"


def test_a_checkin_older_than_the_current_version_was_already_used_by_it(accounts, user):
    pf, version, plan = _followed(accounts, user)
    reviewed = accounts.add_review_version(pf.id, version.spec, {**synthetic_result(anchor=1), "created": "2028-03-01"})
    stale = accounts.add_checkin(user.id, pf.id, 50_000.0, on_date=date(2028, 2, 15))
    wealth, source = monitor.estimate_wealth(pf, reviewed, plan, stale, date(2028, 4, 1))
    assert source == "projection" and wealth < 45_000
    fresh = accounts.add_checkin(user.id, pf.id, 50_000.0, on_date=date(2028, 3, 20))
    assert monitor.estimate_wealth(pf, reviewed, plan, fresh, date(2028, 4, 1))[1] == "checkin"


def test_the_estimate_never_goes_below_zero(accounts, user):
    pf, version, plan = _followed(accounts, user)
    broke = accounts.add_checkin(user.id, pf.id, 0.0, on_date=date(2029, 10, 22))
    assert monitor.estimate_wealth(pf, version, plan, broke, date(2029, 10, 26))[0] == 0.0


def test_the_tracking_message_compares_with_the_expectation_of_that_day_not_of_the_start_of_the_year(accounts, user):
    """Il 10/10/2029 (a 15 giorni dal terzo anniversario) la mediana è ~46.300 €, non i 30.000 € di inizio anno."""
    from ui.account import _tracking_text
    pf, version, _ = _followed(accounts, user)
    on = date(2029, 10, 10)
    text = {v: _tracking_text(version, pf, accounts.add_checkin(user.id, pf.id, v, on_date=on))
            for v in (30_000.0, 40_000.0, 50_000.0)}
    assert text[30_000.0] == i18n.t("acct.checkin.below")
    assert text[40_000.0].startswith(i18n.t("acct.checkin.inside", median="").split("(")[0].strip()), \
        "40.000 € erano «sopra la mediana» con le attese di inizio anno: oggi la mediana del giorno è 46,3 k€"
    assert text[50_000.0].startswith(i18n.t("acct.checkin.above", median="").split("(")[0].strip())
    early = accounts.add_checkin(user.id, pf.id, 50_000.0, on_date=date(2027, 1, 5))
    reviewed = accounts.add_review_version(pf.id, version.spec, {**synthetic_result(anchor=1), "created": "2028-03-01"})
    assert _tracking_text(reviewed, pf, early) == "", "un valore precedente alla versione in corso non è confrontabile"


def test_failed_review_is_reported_but_the_scheduled_check_still_runs(accounts, user):
    start, later = date(2026, 10, 24), date(2027, 3, 1)
    spec = real_spec()
    pf = accounts.create_portfolio(user.id, "Reale", spec, real_result(spec, start), invested=True, today=start)

    def offline(tickers, years):
        raise ConnectionError("rete assente")

    out = monitor.check_portfolio(accounts, pf.id, as_of=later, loader=offline, notifier=Recorder())
    assert out.status == "error" and "rete assente" in out.error and not out.reviewed
    assert accounts.current_version(pf.id).number == 1


# ------------------------------------------------------------------ messaggi ed email
def _weights_alert(accounts, user, name="Piano"):
    pf = accounts.create_portfolio(user.id, name, synthetic_spec("file"), synthetic_result(), invested=True)
    monitor.check_portfolio(accounts, pf.id, as_of=date(2028, 10, 24), notifier=Recorder())
    return pf, accounts.list_alerts(user.id)[0]


def test_alert_text_lists_the_changes_with_their_sign(accounts, user):
    pf, alert = _weights_alert(accounts, user)
    text = describe(alert, pf.name)
    assert pf.name in text.title and text.summary and len(text.rows) == 3
    by_ticker = {r["ticker"]: r for r in text.rows}
    assert by_ticker["EQ"]["delta"].startswith("−") and not by_ticker["EQ"]["up"]
    assert by_ticker["BND"]["delta"].startswith("+") and by_ticker["BND"]["up"]
    assert by_ticker["EQ"]["asset"] == "Fondo EQ"


@pytest.mark.parametrize("lang", list(i18n.LANGS))
def test_alert_email_is_written_in_the_language_of_the_user(accounts, lang):
    owner = accounts.register(f"user-{lang}@example.com", PASSWORD, "Ana", locale=lang)
    pf, alert = _weights_alert(accounts, owner, name="Mi plan")
    subject, text, body = notify.build_email(owner, alert, pf.name, "https://app.test")
    with i18n.use(lang):
        title = describe(alert, pf.name).title
        footer = i18n.t("email.footer")
    assert subject == f"GoalGA · {title}" and title in text and footer in text and html.escape(footer) in body
    assert "https://app.test" in text and 'href="https://app.test"' in body and "Fondo EQ" in body
    assert "{" not in subject and "alert." not in text and "email." not in text


def test_smtp_configuration_comes_from_the_environment(monkeypatch):
    for name in ("HOST", "PORT", "USER", "PASSWORD", "FROM", "SECURITY"):
        monkeypatch.delenv(f"GOALGA_SMTP_{name}", raising=False)
    monkeypatch.delenv("GOALGA_APP_URL", raising=False)
    assert notify.SmtpConfig.from_env() is None and isinstance(notify.default_notifier(), notify.LogNotifier)
    monkeypatch.setenv("GOALGA_SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("GOALGA_SMTP_PORT", "2525")
    monkeypatch.setenv("GOALGA_SMTP_USER", "bot@example.com")
    monkeypatch.setenv("GOALGA_SMTP_SECURITY", "SSL")
    monkeypatch.setenv("GOALGA_APP_URL", "https://goalga.example.com")
    config = notify.SmtpConfig.from_env()
    assert (config.host, config.port, config.user, config.sender) == ("smtp.example.com", 2525, "bot@example.com",
                                                                      "bot@example.com")
    assert config.security == "ssl" and config.app_url == "https://goalga.example.com"
    assert isinstance(notify.default_notifier(), notify.SmtpNotifier)
    assert notify.LogNotifier().send("a@b.c", "s", "t", "<p>t</p>") is False
