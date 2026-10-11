"""
Database connection — SQLAlchemy 2.x engine and session factory.

Connection details come from backend/.env (MYSQL_HOST, MYSQL_PORT,
MYSQL_USER, MYSQL_PASSWORD, MYSQL_DB). Nothing is hardcoded here.

The application user has SELECT/INSERT/UPDATE/DELETE on cellspark.* and no
DDL privileges. That is deliberate: schema.sql is the source of truth for
the schema, and nothing in Python creates, alters or drops tables.
"""

import os
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import URL, Engine
from sqlalchemy.orm import Session, sessionmaker


def _load_env_file():
    """Same approach as tier4/llm.py: read backend/.env without overriding."""
    try:
        from dotenv import load_dotenv
    except Exception:
        return
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
    try:
        load_dotenv(env_path, override=False)
    except Exception:
        pass


_load_env_file()


def database_url() -> URL:
    """
    Build the connection URL from the environment.

    URL.create escapes each part itself, so a password containing '@' or '/'
    cannot break the string. The error for a missing variable names the
    variable, never its value.
    """
    missing = [k for k in ("MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DB")
               if not os.environ.get(k)]
    if missing:
        raise RuntimeError(
            f"Database is not configured: set {', '.join(missing)} in backend/.env"
        )
    return URL.create(
        "mysql+pymysql",
        username=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
        host=os.environ["MYSQL_HOST"],
        port=int(os.environ.get("MYSQL_PORT") or 3306),
        database=os.environ["MYSQL_DB"],
        query={"charset": "utf8mb4"},
    )


_engine = None
_SessionLocal = None


def get_engine() -> Engine:
    """
    Created on first use rather than at import, so the pipeline endpoints and
    the existing tests keep working on a machine where MySQL isn't running.
    """
    global _engine, _SessionLocal
    if _engine is None:
        _engine = create_engine(
            database_url(),
            # XAMPP's MariaDB drops idle connections. Without a ping, the first
            # request after a pause fails with "MySQL server has gone away".
            pool_pre_ping=True,
            pool_recycle=3600,
        )
        _SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)
    return _engine


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    get_engine()
    db = _SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
