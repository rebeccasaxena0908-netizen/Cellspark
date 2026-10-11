"""
ORM models mapped onto the tables in backend/schema.sql.

schema.sql is the source of truth. These classes describe tables that already
exist; Base.metadata.create_all() is never called; the application's database
user could not run it anyway, because it has no DDL privileges. Generating the
schema from Python would lose the constraints, indexes and design comments
that schema.sql carries.

Column types mirror the SQL exactly (unsigned BIGINT keys, CHAR(60) bcrypt
hashes, CHAR(64) SHA-256 digests, ENUMs) so that the mapping and the DDL can be
read side by side. server_default marks columns that the database fills in,
so the ORM leaves them out of the INSERT instead of sending NULL.

All nine tables are mapped now. Phase 1 uses researcher and auth_session;
phases 2 and 3 use the rest.
"""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import ForeignKey, String, Text, func
from sqlalchemy.dialects.mysql import BIGINT, CHAR, DECIMAL, ENUM, INTEGER, SMALLINT, TINYINT
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

UBIGINT = BIGINT(unsigned=True)
UINT = INTEGER(unsigned=True)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------- accounts
class Researcher(Base):
    __tablename__ = "researcher"

    researcher_id: Mapped[int] = mapped_column(UBIGINT, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    display_name: Mapped[str] = mapped_column(String(100))
    institution: Mapped[Optional[str]] = mapped_column(String(150))
    password_hash: Mapped[str] = mapped_column(CHAR(60))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    last_login_at: Mapped[Optional[datetime]]

    # passive_deletes: the FK is ON DELETE CASCADE, so let the database do it
    sessions: Mapped[List["AuthSession"]] = relationship(
        back_populates="researcher", passive_deletes=True
    )

    def __repr__(self):
        # password_hash deliberately left out
        return f"<Researcher {self.researcher_id} {self.email}>"


class AuthSession(Base):
    __tablename__ = "auth_session"

    # SHA-256 hex of the cookie token. The raw token is never stored.
    session_id: Mapped[str] = mapped_column(CHAR(64), primary_key=True)
    researcher_id: Mapped[int] = mapped_column(
        UBIGINT, ForeignKey("researcher.researcher_id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(index=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(255))

    researcher: Mapped[Researcher] = relationship(back_populates="sessions")


# ---------------------------------------------------------------- files and runs
class MutationFile(Base):
    __tablename__ = "mutation_file"

    file_id: Mapped[int] = mapped_column(UBIGINT, primary_key=True, autoincrement=True)
    researcher_id: Mapped[int] = mapped_column(
        UBIGINT, ForeignKey("researcher.researcher_id", ondelete="CASCADE"), index=True
    )
    original_name: Mapped[str] = mapped_column(String(255))
    stored_path: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(CHAR(64))
    size_bytes: Mapped[int] = mapped_column(UINT)
    mutation_count: Mapped[Optional[int]] = mapped_column(UINT)
    uploaded_at: Mapped[datetime] = mapped_column(server_default=func.now())


class PipelineRun(Base):
    __tablename__ = "pipeline_run"

    run_id: Mapped[int] = mapped_column(UBIGINT, primary_key=True, autoincrement=True)
    researcher_id: Mapped[int] = mapped_column(
        UBIGINT, ForeignKey("researcher.researcher_id", ondelete="CASCADE")
    )
    file_id: Mapped[int] = mapped_column(
        UBIGINT, ForeignKey("mutation_file.file_id", ondelete="RESTRICT"), index=True
    )

    algorithm: Mapped[str] = mapped_column(
        ENUM("kmp", "boyer_moore", "naive"), server_default="kmp"
    )
    status: Mapped[str] = mapped_column(
        ENUM("running", "completed", "failed"), server_default="running"
    )

    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[Optional[datetime]]
    duration_ms: Mapped[Optional[int]] = mapped_column(UINT)

    mutations_parsed: Mapped[Optional[int]] = mapped_column(UINT)
    candidates_built: Mapped[Optional[int]] = mapped_column(UINT)
    targets_returned: Mapped[Optional[int]] = mapped_column(UINT)
    best_ic50_nm: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(10, 2))
    cai_after: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(4, 3))

    result_path: Mapped[Optional[str]] = mapped_column(String(500))
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    alleles: Mapped[List["RunAllele"]] = relationship(passive_deletes=True)
    targets: Mapped[List["PredictedTarget"]] = relationship(
        passive_deletes=True, order_by="PredictedTarget.rank_position"
    )


class RunAllele(Base):
    __tablename__ = "run_allele"

    run_id: Mapped[int] = mapped_column(
        UBIGINT, ForeignKey("pipeline_run.run_id", ondelete="CASCADE"), primary_key=True
    )
    allele: Mapped[str] = mapped_column(String(20), primary_key=True)


class PredictedTarget(Base):
    __tablename__ = "predicted_target"

    target_id: Mapped[int] = mapped_column(UBIGINT, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        UBIGINT, ForeignKey("pipeline_run.run_id", ondelete="CASCADE")
    )
    rank_position: Mapped[int] = mapped_column(TINYINT(unsigned=True))

    peptide: Mapped[str] = mapped_column(String(15))
    wildtype: Mapped[Optional[str]] = mapped_column(String(15))
    gene_symbol: Mapped[str] = mapped_column(String(30))
    protein_change: Mapped[str] = mapped_column(String(30))
    allele: Mapped[str] = mapped_column(String(20))

    ic50_nm: Mapped[Decimal] = mapped_column(DECIMAL(10, 2))
    wt_ic50_nm: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(10, 2))
    agretopicity: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(8, 2))


# ---------------------------------------------------------------- copilot
class ChatMessage(Base):
    __tablename__ = "chat_message"

    message_id: Mapped[int] = mapped_column(UBIGINT, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        UBIGINT, ForeignKey("pipeline_run.run_id", ondelete="CASCADE")
    )
    researcher_id: Mapped[int] = mapped_column(
        UBIGINT, ForeignKey("researcher.researcher_id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(ENUM("user", "assistant"))
    content: Mapped[str] = mapped_column(Text)
    provider: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    citations: Mapped[List["MessageCitation"]] = relationship(passive_deletes=True)


class MessageCitation(Base):
    __tablename__ = "message_citation"

    citation_id: Mapped[int] = mapped_column(UBIGINT, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        UBIGINT, ForeignKey("chat_message.message_id", ondelete="CASCADE"), index=True
    )
    pmid: Mapped[str] = mapped_column(String(20), index=True)
    title: Mapped[Optional[str]] = mapped_column(String(500))
    journal: Mapped[Optional[str]] = mapped_column(String(200))
    pub_year: Mapped[Optional[int]] = mapped_column(SMALLINT(unsigned=True))
    similarity: Mapped[Optional[Decimal]] = mapped_column(DECIMAL(6, 4))


class CrossCheckLookup(Base):
    __tablename__ = "cross_check_lookup"

    lookup_id: Mapped[int] = mapped_column(UBIGINT, primary_key=True, autoincrement=True)
    run_id: Mapped[int] = mapped_column(
        UBIGINT, ForeignKey("pipeline_run.run_id", ondelete="CASCADE"), index=True
    )
    researcher_id: Mapped[int] = mapped_column(
        UBIGINT, ForeignKey("researcher.researcher_id", ondelete="CASCADE")
    )
    gene_symbol: Mapped[str] = mapped_column(String(30))
    protein_change: Mapped[Optional[str]] = mapped_column(String(30))
    coverage: Mapped[str] = mapped_column(ENUM("well_covered", "thin", "not_covered"))
    summary: Mapped[Optional[str]] = mapped_column(Text)
    provider: Mapped[Optional[str]] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
