"""
Researcher account tests: signup, login, logout, /me.

Nothing here persists. Each test runs inside one outer transaction on a single
connection, rolled back at the end. The session joins it with
join_transaction_mode="create_savepoint", so the route handlers' own commit()
and rollback() calls become savepoints inside that transaction rather than
real commits. The working cellspark database is never written to.

(A separate test database isn't an option: the application user deliberately
has no CREATE privilege.)

The engine/db/client fixtures live in conftest.py, shared with
test_records.py. Needs MariaDB running with backend/.env configured; if it
isn't reachable these tests are skipped rather than failed, so the pipeline
tests still run on a machine without XAMPP.
"""
import hashlib
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlalchemy import func, select, text, update

from app import auth
from app.main import INVALID_LOGIN
from app.models import AuthSession, Researcher

PASSWORD = "correct horse battery"


def unique_email() -> str:
    return f"auth-test-{uuid.uuid4().hex[:10]}@example.org"


def signup(client, email=None, password=PASSWORD, **extra):
    body = {"email": email or unique_email(), "display_name": "Test Researcher",
            "password": password, **extra}
    return client.post("/api/auth/signup", json=body)


def rows_for(db, email):
    return db.execute(select(Researcher).where(Researcher.email == email)).scalars().all()


def all_session_values(db):
    """Every value in every auth_session row, as strings."""
    rows = db.execute(text("SELECT * FROM auth_session")).all()
    return [str(v) for row in rows for v in row]


# --------------------------------------------------------------- signup
def test_signup_creates_one_row_with_bcrypt_hash(client, db):
    email = unique_email()
    r = signup(client, email=email, institution="Test Institute")
    assert r.status_code == 201
    assert r.json()["email"] == email
    assert "password_hash" not in r.json()

    rows = rows_for(db, email)
    assert len(rows) == 1
    h = rows[0].password_hash
    assert h != PASSWORD
    assert len(h) == 60
    assert h.startswith("$2b$")
    assert PASSWORD not in h


def test_signup_normalises_email(client, db):
    raw = "  Mixed.Case@Example.ORG "
    r = signup(client, email=raw)
    assert r.status_code == 201
    assert r.json()["email"] == "mixed.case@example.org"
    assert len(rows_for(db, "mixed.case@example.org")) == 1


def test_duplicate_email_is_409_and_creates_no_row(client, db):
    email = unique_email()
    assert signup(client, email=email).status_code == 201
    client.cookies.clear()

    r = signup(client, email=email.upper())       # same address, other case
    assert r.status_code == 409
    assert len(rows_for(db, email)) == 1


def test_signup_rejects_short_password_and_bad_email(client, db):
    email = unique_email()
    r = signup(client, email=email, password="short")
    assert r.status_code == 422
    assert "short" not in r.text
    assert rows_for(db, email) == []

    r = signup(client, email="not-an-email")
    assert r.status_code == 422


def test_validation_error_does_not_echo_password(client):
    # display_name missing: FastAPI's default 422 would echo the whole body
    r = client.post("/api/auth/signup",
                    json={"email": unique_email(), "password": PASSWORD})
    assert r.status_code == 422
    assert PASSWORD not in r.text


# --------------------------------------------------------------- login
def test_login_sets_cookie_and_stores_only_its_hash(client, db):
    email = unique_email()
    signup(client, email=email)
    client.cookies.clear()

    r = client.post("/api/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200

    token = r.cookies.get(auth.COOKIE_NAME)
    assert token
    set_cookie = r.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie

    researcher = rows_for(db, email)[0]
    stored = db.get(AuthSession, hashlib.sha256(token.encode()).hexdigest())
    assert stored is not None
    assert stored.researcher_id == researcher.researcher_id

    # the raw token is nowhere in the table, in any column of any row
    assert not any(token in v for v in all_session_values(db))
    assert researcher.last_login_at is not None


def test_wrong_password_and_unknown_email_are_indistinguishable(client):
    email = unique_email()
    signup(client, email=email)
    client.cookies.clear()

    wrong = client.post("/api/auth/login", json={"email": email, "password": "wrong-password"})
    unknown = client.post("/api/auth/login",
                          json={"email": unique_email(), "password": PASSWORD})

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": INVALID_LOGIN}
    assert auth.COOKIE_NAME not in wrong.cookies
    assert auth.COOKIE_NAME not in unknown.cookies


def test_unknown_email_still_runs_bcrypt(client, monkeypatch):
    """The timing equaliser: an unknown email must still cost one verify."""
    calls = []
    real = auth._pwd

    class Spy:
        def verify(self, secret, h):
            calls.append(h)
            return real.verify(secret, h)

    monkeypatch.setattr(auth, "_pwd", Spy())
    r = client.post("/api/auth/login", json={"email": unique_email(), "password": PASSWORD})
    assert r.status_code == 401
    assert calls == [auth._DUMMY_HASH]


# --------------------------------------------------------------- /me
def test_me_without_cookie_is_401(client):
    client.cookies.clear()
    assert client.get("/api/auth/me").status_code == 401


def test_me_with_valid_cookie_returns_researcher(client):
    email = unique_email()
    signup(client, email=email)
    r = client.get("/api/auth/me")
    assert r.status_code == 200
    assert r.json()["email"] == email
    assert r.json()["display_name"] == "Test Researcher"


def test_me_with_expired_session_is_401(client, db):
    email = unique_email()
    signup(client, email=email)
    assert client.get("/api/auth/me").status_code == 200

    rid = rows_for(db, email)[0].researcher_id
    db.execute(
        update(AuthSession)
        .where(AuthSession.researcher_id == rid)
        .values(expires_at=func.timestampadd(text("SECOND"), -60, func.now()))
    )
    db.flush()
    assert client.get("/api/auth/me").status_code == 401


def test_me_with_forged_cookie_is_401(client):
    client.cookies.set(auth.COOKIE_NAME, "not-a-real-token")
    assert client.get("/api/auth/me").status_code == 401


# --------------------------------------------------------------- logout
def test_logout_deletes_row_and_old_cookie_stops_working(client, db):
    email = unique_email()
    signup(client, email=email)
    token = client.cookies.get(auth.COOKIE_NAME)
    session_id = hashlib.sha256(token.encode()).hexdigest()
    assert db.get(AuthSession, session_id) is not None

    r = client.post("/api/auth/logout")
    assert r.status_code == 200
    db.expire_all()
    assert db.get(AuthSession, session_id) is None

    # replay the old cookie by hand: the browser cleared it, an attacker wouldn't
    client.cookies.clear()
    client.cookies.set(auth.COOKIE_NAME, token)
    assert client.get("/api/auth/me").status_code == 401
