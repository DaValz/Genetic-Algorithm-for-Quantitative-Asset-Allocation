"""Sicurezza dei conti: hash delle password, validazione di email e password."""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re

from ..i18n import LocalizedError

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
PBKDF2_ITERATIONS = 600_000
MIN_PASSWORD, MAX_PASSWORD = 8, 128
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")
_COMMON = {"password", "password1", "12345678", "123456789", "1234567890", "qwertyui", "qwerty123", "iloveyou",
           "11111111", "00000000", "abcd1234", "letmein1", "welcome1", "passw0rd", "admin123", "goalga123"}


class AccountError(LocalizedError):
    """Errore di un'operazione su conti e portafogli (chiave ``acct.err.*`` traducibile)."""


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def hash_password(password: str) -> str:
    """Hash con salt casuale (scrypt; PBKDF2-SHA256 se scrypt non è disponibile)."""
    salt = os.urandom(16)
    try:
        digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
        return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"
    except (AttributeError, ValueError):
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS, dklen=32)
        return f"pbkdf2${PBKDF2_ITERATIONS}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    """Confronto a tempo costante; restituisce False per hash malformati."""
    try:
        parts = stored.split("$")
        if parts[0] == "scrypt":
            _, n, r, p, salt, digest = parts
            expected = base64.b64decode(digest)
            actual = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(salt), n=int(n), r=int(r),
                                    p=int(p), dklen=len(expected))
        elif parts[0] == "pbkdf2":
            _, iterations, salt, digest = parts
            expected = base64.b64decode(digest)
            actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt), int(iterations),
                                         dklen=len(expected))
        else:
            return False
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, AttributeError):
        return False


def burn_time(password: str = "x") -> None:
    """Esegue un hash a vuoto: rende simile il tempo di risposta per email esistenti e non."""
    verify_password(password, _DUMMY)


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def validate_email(email: str) -> str:
    email = normalize_email(email)
    if len(email) > 254 or not _EMAIL.match(email):
        raise AccountError("acct.err.invalid_email")
    return email


def validate_password(password: str, email: str = "") -> None:
    password = password or ""
    local = normalize_email(email).split("@")[0]
    if not MIN_PASSWORD <= len(password) <= MAX_PASSWORD or password.lower() in _COMMON or (
            local and password.lower() == local):
        raise AccountError("acct.err.weak_password", min=MIN_PASSWORD)


_DUMMY = hash_password("dummy-password-for-timing")
