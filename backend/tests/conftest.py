"""
Shared database fixtures for the tests that touch MySQL.

Nothing persists. Each test runs inside one outer transaction on a single
connection, rolled back at the end. The session joins it with
join_transaction_mode="create_savepoint", so the route handlers' own commit()
and rollback() calls become savepoints inside that transaction rather than
real commits. The working cellspark database is never written to.

(A separate test database isn't an option: the application user deliberately
has no CREATE privilege.)

If MySQL isn't reachable, any test using these fixtures is skipped rather
than failed, so the pipeline tests still run on a machine without XAMPP.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import get_db, get_engine
from app.main import app


# --------------------------------------------------------------- fixtures
@pytest.fixture(scope="session")
def engine():
    try:
        eng = get_engine()
        with eng.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception as e:
        pytest.skip(f"MySQL not reachable: {type(e).__name__}")
    return eng


@pytest.fixture
def db(engine):
    conn = engine.connect()
    outer = conn.begin()
    session = Session(
        bind=conn,
        join_transaction_mode="create_savepoint",
        autoflush=False,
        expire_on_commit=False,
    )
    try:
        yield session
    finally:
        session.close()
        outer.rollback()
        conn.close()


@pytest.fixture
def client(db):
    def override():
        yield db
    app.dependency_overrides[get_db] = override
    try:
        with TestClient(app) as c:
            yield c
    finally:
        app.dependency_overrides.pop(get_db, None)
