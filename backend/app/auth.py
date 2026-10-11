"""
Researcher accounts: password hashing, server-side sessions, current user.

PASSWORDS
bcrypt via passlib. The plaintext is hashed inside the request handler and
goes no further: it is not logged, not stored, and not put into any exception
or error message. bcrypt digests are 60 characters, which is why
researcher.password_hash is CHAR(60).

bcrypt only reads the first 72 bytes of a password. Signup rejects anything
longer rather than silently ignoring the rest of what the user typed.

SESSIONS
The browser holds a random token (secrets.token_urlsafe(32), 256 bits) in an
httpOnly cookie. The database holds only sha256(token) as
auth_session.session_id, so a dump of that table cannot be replayed as a
cookie. Logout deletes the row, which ends the session immediately; a signed
stateless token (JWT) could not be revoked this way.

SHA-256 rather than bcrypt is right for the token: it is 256 random bits, not
a human-chosen password, so it cannot be guessed and does not need a slow
hash. A fast hash also keeps the per-request lookup cheap.

CLOCK
expires_at is computed and compared by the database (NOW()), not by Python,
so there is a single clock. created_at already uses the database's
CURRENT_TIMESTAMP, and the cleanup query in schema.sql compares against NOW().
"""

import hashlib
import secrets
from typing import Optional

from email_validator import EmailNotValidError, validate_email
from fastapi import Depends, HTTPException, Request, Response
from passlib.context import CryptContext
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from .db import get_db
from .models import AuthSession, Researcher

COOKIE_NAME = "cellspark_session"
SESSION_SECONDS = 7 * 24 * 60 * 60          # 7 days
MIN_PASSWORD_LENGTH = 8
MAX_PASSWORD_BYTES = 72                      # bcrypt ignores anything past this

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Verified against when the email is unknown, so that a login for a
# non-existent account costs the same bcrypt work as a wrong password.
# Hashed once at startup from a throwaway random value.
_DUMMY_HASH = _pwd.hash(secrets.token_urlsafe(16))


# ---------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    return _pwd.hash(password)


def verify_password(password: str, password_hash: Optional[str]) -> bool:
    """
    Always runs one bcrypt verification, whether or not there is a real hash.

    With password_hash=None it checks against the dummy hash and returns
    False, so an unknown email and a wrong password take the same time.
    """
    if password_hash is None:
        _pwd.verify(password, _DUMMY_HASH)
        return False
    try:
        return _pwd.verify(password, password_hash)
    except (ValueError, TypeError):
        # Malformed stored hash. Say nothing about the input.
        return False


def password_problem(password: str) -> Optional[str]:
    """
    Length is the only rule. Composition rules ("one symbol, one digit") push
    people toward predictable patterns and make passwords worse, not better.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return f"Password must be at most {MAX_PASSWORD_BYTES} bytes."
    return None


# ---------------------------------------------------------------- email
def normalise_email(raw: str) -> str:
    """
    Validate and canonicalise: trimmed and lowercased.

    researcher.email has a UNIQUE key on the raw column, so normalising before
    insert is what stops "Ana@Lab.org" and "ana@lab.org" becoming two accounts.
    Raises ValueError with a user-facing message.

    Deliverability (a DNS lookup) is not checked. Signup must work offline,
    and confirming an address really exists would need email verification,
    which is out of scope here.
    """
    try:
        info = validate_email((raw or "").strip(), check_deliverability=False)
    except EmailNotValidError as e:
        raise ValueError(str(e))
    return info.normalized.lower()


def lookup_email(raw: str) -> str:
    """
    Canonicalise for login without validating. A malformed address simply
    matches no row and falls through to the generic failure, so login never
    reports anything specific about the email it was given.
    """
    return (raw or "").strip().lower()


# ---------------------------------------------------------------- sessions
def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, researcher: Researcher, request: Request) -> str:
    """
    Insert a session row and return the raw token for the cookie.

    The caller commits. Only the hash is written.
    """
    token = secrets.token_urlsafe(32)
    user_agent = (request.headers.get("user-agent") or "")[:255] or None
    db.add(AuthSession(
        session_id=hash_token(token),
        researcher_id=researcher.researcher_id,
        expires_at=func.timestampadd(text("SECOND"), SESSION_SECONDS, func.now()),
        user_agent=user_agent,
    ))
    return token


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_SECONDS,     # matches expires_at
        httponly=True,               # not readable from JavaScript
        samesite="lax",              # not sent on cross-site POSTs
        secure=False,                # localhost is plain http
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="lax")


def delete_session(db: Session, token: Optional[str]) -> None:
    """Revoke server-side. The caller commits."""
    if token:
        db.execute(delete(AuthSession).where(AuthSession.session_id == hash_token(token)))


# ---------------------------------------------------------------- dependencies
def current_researcher(request: Request, db: Session = Depends(get_db)) -> Optional[Researcher]:
    """
    The signed-in researcher, or None.

    An expired row is treated exactly like a missing one. It is left for the
    cleanup query in schema.sql rather than deleted here, so a read-only
    request never writes.
    """
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None
    return db.execute(
        select(Researcher)
        .join(AuthSession, AuthSession.researcher_id == Researcher.researcher_id)
        .where(AuthSession.session_id == hash_token(token))
        .where(AuthSession.expires_at > func.now())
    ).scalar_one_or_none()


def require_researcher(
    researcher: Optional[Researcher] = Depends(current_researcher),
) -> Researcher:
    """Strict variant: 401 when nobody is signed in."""
    if researcher is None:
        raise HTTPException(status_code=401, detail="Not signed in.")
    return researcher


def public_profile(r: Researcher) -> dict:
    """What the API returns about a researcher. Never the password hash."""
    return {
        "researcher_id": r.researcher_id,
        "email": r.email,
        "display_name": r.display_name,
        "institution": r.institution,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "last_login_at": r.last_login_at.isoformat() if r.last_login_at else None,
    }
