"""
Persistence for researcher work: files, runs, targets, chats, cross-checks.

The routes in main.py call these; nothing in the pipeline or the tiers knows
the database exists. Functions here add and update rows but never commit —
the route decides where each transaction ends.

OWNERSHIP
Every lookup by id also filters on researcher_id. A row that exists but
belongs to someone else is indistinguishable from one that does not exist:
both come back as None, and the route turns that into 404. A 403 would
confirm the id is real.

RESULT FILES
A run's full result JSON is written to disk, never into the database. It can
be hundreds of kilobytes and is read whole or not at all; the headline figures
the history list needs are copied into pipeline_run columns instead.
"""

import json
import logging
import math
import os
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import (
    ChatMessage,
    CrossCheckLookup,
    MessageCitation,
    MutationFile,
    PipelineRun,
    PredictedTarget,
    RunAllele,
)
from .upload import sha256_hex

logger = logging.getLogger("cellspark.records")

RESULTS_DIR = os.environ.get("CELLSPARK_RESULTS_DIR") or os.path.join(
    os.path.dirname(__file__), "..", "data", "results"
)

DEMO_FILE_NAME = "sample_patient.maf"


# ---------------------------------------------------------------- helpers
def _dec(value: Any, places: int, max_abs: float) -> Optional[Decimal]:
    """
    A number as a Decimal fitting DECIMAL(p, places), or None.

    None for missing, non-numeric, non-finite or out-of-range values: a strict
    MariaDB rejects an out-of-range DECIMAL outright, and one odd score must
    not cost the whole run its record.
    """
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f) or abs(f) > max_abs:
        return None
    try:
        return Decimal(str(round(f, places)))
    except InvalidOperation:
        return None


def _text(value: Any, limit: int) -> Optional[str]:
    """Trimmed to the column width; None for empty."""
    if value is None:
        return None
    s = str(value).strip()
    return s[:limit] if s else None


# ---------------------------------------------------------------- files
def find_file(db: Session, researcher_id: int, sha256: str) -> Optional[MutationFile]:
    return db.execute(
        select(MutationFile)
        .where(MutationFile.researcher_id == researcher_id)
        .where(MutationFile.sha256 == sha256)
    ).scalar_one_or_none()


def get_owned_file(db: Session, researcher_id: int, file_id: int) -> Optional[MutationFile]:
    return db.execute(
        select(MutationFile)
        .where(MutationFile.file_id == file_id)
        .where(MutationFile.researcher_id == researcher_id)
    ).scalar_one_or_none()


def add_file(db: Session, researcher_id: int, original_name: str, stored_path: str,
             sha256: str, size_bytes: int,
             mutation_count: Optional[int]) -> Tuple[MutationFile, bool]:
    """
    Insert a mutation_file row, or return the existing one for this
    (researcher, sha256). Returns (row, created).

    The SELECT-then-INSERT has a race: two identical uploads in flight at
    once both see no row. The UNIQUE key catches the second; a savepoint
    lets it fall back to the winner's row without abandoning the request's
    transaction.
    """
    existing = find_file(db, researcher_id, sha256)
    if existing:
        return existing, False

    row = MutationFile(
        researcher_id=researcher_id,
        original_name=_text(original_name, 255) or "upload.maf",
        stored_path=stored_path[:500],
        sha256=sha256,
        size_bytes=size_bytes,
        mutation_count=mutation_count,
    )
    try:
        with db.begin_nested():
            db.add(row)
    except IntegrityError:
        existing = find_file(db, researcher_id, sha256)
        if existing is None:
            raise
        return existing, False
    return row, True


def demo_file(db: Session, researcher_id: int) -> MutationFile:
    """
    The bundled sample patient, registered as a file this researcher owns.

    pipeline_run.file_id is NOT NULL, so a demo run needs a file row like any
    other. The demo MAF is regenerated per process into a fresh temp directory
    but from a fixed seed, so its SHA-256 is stable: the (researcher_id,
    sha256) key means this inserts once per researcher and is reused after.
    """
    from .pipeline import _get_demo        # deferred: pipeline imports heavy ML code
    from .tier1.maf_parser import load_maf

    _, (_, maf_path, _, _) = _get_demo()
    with open(maf_path, "rb") as fh:
        content = fh.read()
    digest = sha256_hex(content)

    existing = find_file(db, researcher_id, digest)
    if existing:
        return existing

    row, _ = add_file(
        db, researcher_id,
        original_name=DEMO_FILE_NAME,
        stored_path=maf_path,
        sha256=digest,
        size_bytes=len(content),
        mutation_count=len(load_maf(maf_path)),
    )
    return row


# ---------------------------------------------------------------- runs
def get_owned_run(db: Session, researcher_id: int, run_id: int) -> Optional[PipelineRun]:
    return db.execute(
        select(PipelineRun)
        .where(PipelineRun.run_id == run_id)
        .where(PipelineRun.researcher_id == researcher_id)
    ).scalar_one_or_none()


def start_run(db: Session, researcher_id: int, file_id: int, algorithm: str,
              alleles: List[str]) -> PipelineRun:
    """
    The 'running' row and its alleles, inserted before the pipeline executes.
    The caller commits straight away, so a crash mid-pipeline still leaves a
    record rather than nothing.
    """
    run = PipelineRun(
        researcher_id=researcher_id,
        file_id=file_id,
        algorithm=algorithm,
        status="running",
    )
    db.add(run)
    db.flush()                              # assigns run_id
    for allele in alleles:
        db.add(RunAllele(run_id=run.run_id, allele=allele))
    db.flush()
    return run


def result_path_for(run_id: int) -> str:
    return os.path.abspath(os.path.join(RESULTS_DIR, f"run_{run_id}.json"))


def write_result(run_id: int, result: Dict[str, Any]) -> str:
    """
    Write the result JSON and return its path.

    Written to a temp name and renamed, so a crash mid-write never leaves a
    truncated file that later reads as a corrupt result.
    """
    path = result_path_for(run_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(result, fh, default=str)
    os.replace(tmp, path)
    return path


def load_result(run: PipelineRun) -> Optional[Dict[str, Any]]:
    """The stored result for a run, or None if there isn't a readable one."""
    path = run.result_path or result_path_for(run.run_id)
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def complete_run(db: Session, run: PipelineRun, result: Dict[str, Any],
                 result_path: str, duration_ms: int) -> None:
    """
    Mark the run completed and write its ranked targets.

    Everything here lands in one commit, made by the caller: either the run
    is completed with all its targets, or none of it is written.
    """
    tier1 = result.get("tier1") or {}
    tier2 = result.get("tier2") or {}
    tier3 = result.get("tier3") or {}
    stats = tier1.get("stats") or {}
    # A degraded Tier 2 (model failed to load) reports implemented=False and
    # has no real targets; the run still completed, with zero of them.
    targets = (tier2.get("targets") or []) if tier2.get("implemented", True) else []

    ic50s = [t.get("ic50") for t in targets if t.get("ic50") is not None]

    run.status = "completed"
    run.finished_at = func.now()
    run.duration_ms = duration_ms
    run.mutations_parsed = stats.get("mutations")
    run.candidates_built = stats.get("candidates")
    run.targets_returned = len(targets)
    run.best_ic50_nm = _dec(min(ic50s), 2, 99_999_999.99) if ic50s else None
    run.cai_after = (
        _dec((tier3.get("after") or {}).get("cai"), 3, 9.999)
        if tier3.get("implemented") else None
    )
    run.result_path = result_path[:500]

    # Ranked order as returned; rank_position is 1..n with no gaps regardless
    # of what the tiers numbered them.
    for position, t in enumerate(targets, start=1):
        ic50 = _dec(t.get("ic50"), 2, 99_999_999.99)
        if ic50 is None:
            # NOT NULL column. A target without a score is not a ranked target.
            raise ValueError(f"Target {position} has no usable IC50")
        wt = _dec(t.get("wtIc50", t.get("wt_ic50")), 2, 99_999_999.99)
        agretopicity = _dec(float(wt) / float(ic50), 2, 999_999.99) if wt and ic50 > 0 else None

        db.add(PredictedTarget(
            run_id=run.run_id,
            rank_position=position,
            peptide=_text(t.get("peptide"), 15) or "",
            wildtype=_text(t.get("wildtype"), 15),
            gene_symbol=_text(t.get("gene"), 30) or "",
            protein_change=_text(t.get("change"), 30) or "",
            allele=_text(t.get("allele"), 20) or "",
            ic50_nm=ic50,
            wt_ic50_nm=wt,
            agretopicity=agretopicity,
        ))
    db.flush()


def fail_run(db: Session, run_id: int, message: str, duration_ms: Optional[int],
             result_path: Optional[str] = None) -> None:
    """
    Record a failure in its own transaction, committed here.

    Best effort: this runs after something has already gone wrong, possibly
    the database itself, so it logs instead of raising — the original error
    is the one the caller reports.
    """
    try:
        run = db.get(PipelineRun, run_id)
        if run is None:
            return
        run.status = "failed"
        run.finished_at = func.now()
        run.duration_ms = duration_ms
        run.error_message = message or "Unknown error"
        if result_path:
            run.result_path = result_path[:500]
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Could not mark run %s as failed", run_id)


def run_summary(run: PipelineRun) -> Dict[str, Any]:
    """A run's stored record, for the API. Ids and figures only."""
    def num(v):
        return float(v) if v is not None else None
    return {
        "run_id": run.run_id,
        "file_id": run.file_id,
        "algorithm": run.algorithm,
        "status": run.status,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "duration_ms": run.duration_ms,
        "mutations_parsed": run.mutations_parsed,
        "candidates_built": run.candidates_built,
        "targets_returned": run.targets_returned,
        "best_ic50_nm": num(run.best_ic50_nm),
        "cai_after": num(run.cai_after),
        "error_message": run.error_message,
        "alleles": [a.allele for a in run.alleles],
        "targets": [{
            "rank_position": t.rank_position,
            "peptide": t.peptide,
            "gene_symbol": t.gene_symbol,
            "protein_change": t.protein_change,
            "allele": t.allele,
            "ic50_nm": num(t.ic50_nm),
            "wt_ic50_nm": num(t.wt_ic50_nm),
            "agretopicity": num(t.agretopicity),
        } for t in run.targets],
    }


# ---------------------------------------------------------------- copilot
def load_history(db: Session, run_id: int, limit: int) -> List[Dict[str, str]]:
    """
    The last `limit` messages for a run, oldest first, as role/content.

    This replaces the history the client used to send. A client-supplied
    transcript can say anything, including answers the copilot never gave;
    the stored one is what actually happened.
    """
    rows = db.execute(
        select(ChatMessage.role, ChatMessage.content)
        .where(ChatMessage.run_id == run_id)
        .order_by(ChatMessage.created_at.desc(), ChatMessage.message_id.desc())
        .limit(limit)
    ).all()
    return [{"role": r.role, "content": r.content} for r in reversed(rows)]


def record_chat(db: Session, run: PipelineRun, researcher_id: int,
                question: str, response: Dict[str, Any]) -> ChatMessage:
    """The question, the answer, and the abstracts the answer was grounded in."""
    db.add(ChatMessage(
        run_id=run.run_id, researcher_id=researcher_id,
        role="user", content=question,
    ))
    reply = ChatMessage(
        run_id=run.run_id, researcher_id=researcher_id,
        role="assistant", content=response.get("answer") or "",
        provider=_text(response.get("provider"), 50),
    )
    db.add(reply)
    db.flush()                              # assigns reply.message_id

    # `sources` rather than `passages`: same abstracts, but with year as a
    # number and the raw similarity, which is what the columns hold.
    for s in response.get("sources") or []:
        pmid = _text(s.get("pmid"), 20)
        if not pmid:
            continue
        year = s.get("year")
        try:
            year = int(year) if year not in (None, "") else None
        except (TypeError, ValueError):
            year = None
        db.add(MessageCitation(
            message_id=reply.message_id,
            pmid=pmid,
            title=_text(s.get("title"), 500),
            journal=_text(s.get("journal"), 200),
            pub_year=year if year is not None and 0 <= year <= 65535 else None,
            similarity=_dec(s.get("similarity"), 4, 99.9999),
        ))
    db.flush()
    return reply


COVERAGE_STATES = ("well_covered", "thin", "not_covered")


def record_cross_check(db: Session, run: PipelineRun, researcher_id: int,
                       gene: str, change: str, response: Dict[str, Any]) -> None:
    """
    One row per lookup, not_covered included — those rows are the point:
    counted per gene they show where the abstract index is thin.

    provider tells an index miss apart from a retrieval outage: both report
    not_covered, but an outage has provider 'unavailable'.
    """
    coverage = response.get("coverage")
    if coverage not in COVERAGE_STATES:
        logger.warning("Cross-check returned unknown coverage %r; not recorded", coverage)
        return
    db.add(CrossCheckLookup(
        run_id=run.run_id,
        researcher_id=researcher_id,
        gene_symbol=_text(response.get("gene") or gene, 30) or "",
        protein_change=_text(response.get("change") or change, 30),
        coverage=coverage,
        summary=response.get("summary"),
        provider=_text(response.get("provider"), 50),
    ))
    db.flush()
