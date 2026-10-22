"""
Persistence for researcher work: files, runs, targets, chats, cross-checks
and Tier 5 formulation worksheets.

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

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .models import (
    ChatMessage,
    CrossCheckLookup,
    FormulationLipid,
    FormulationSpec,
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


def demo_path() -> str:
    """Permanent home of the bundled sample patient's MAF, shared by everyone."""
    from . import upload
    return os.path.join(upload.UPLOAD_DIR, "demo", DEMO_FILE_NAME)


def _ensure_demo_copy() -> Tuple[str, bytes, str]:
    """
    Write the demo MAF to its permanent path once, and return (path, bytes,
    sha256).

    pipeline.py still builds its demo dataset in memory per process (it needs
    the synthetic proteome too, and that code is not touched here). The bytes
    are identical every time because the generator is seeded, so the copy
    written here is the same file the pipeline reads — just at a path that
    survives a restart, which is what the mutation_file row records.
    """
    from .pipeline import _get_demo        # deferred: pipeline imports heavy ML code

    _, (_, maf_path, _, _) = _get_demo()
    with open(maf_path, "rb") as fh:
        content = fh.read()
    digest = sha256_hex(content)

    path = demo_path()
    current = None
    if os.path.exists(path):
        with open(path, "rb") as fh:
            current = sha256_hex(fh.read())
    if current != digest:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".part"
        with open(tmp, "wb") as fh:
            fh.write(content)
        os.replace(tmp, path)
    return path, content, digest


def demo_file(db: Session, researcher_id: int) -> MutationFile:
    """
    The bundled sample patient, registered as a file this researcher owns.

    pipeline_run.file_id is NOT NULL, so a demo run needs a file row like any
    other. The demo MAF's SHA-256 is stable (seeded generator), so the
    (researcher_id, sha256) key means this inserts once per researcher and is
    reused after. A row written before Phase 3 points into a temp folder that
    no longer exists; it is repointed at the permanent copy here.
    """
    from .tier1.maf_parser import load_maf

    path, content, digest = _ensure_demo_copy()

    existing = find_file(db, researcher_id, digest)
    if existing:
        if existing.stored_path != path:
            existing.stored_path = path
            db.flush()
        return existing

    row, _ = add_file(
        db, researcher_id,
        original_name=DEMO_FILE_NAME,
        stored_path=path,
        sha256=digest,
        size_bytes=len(content),
        mutation_count=len(load_maf(path)),
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
            "wildtype": t.wildtype,
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


# ---------------------------------------------------------------- history
# Read paths for the history dashboard. Each is a fixed number of statements
# however many rows come back: the list is one query plus one count, the chat
# is messages plus citations. Nothing loops over runs issuing a query each.

_RUN_LIST_SQL = text("""
    SELECT r.run_id, r.status, r.algorithm, r.started_at, r.finished_at,
           r.duration_ms, r.targets_returned, r.best_ic50_nm, r.cai_after,
           r.error_message,
           f.file_id, f.original_name, f.stored_path,
           t.gene_symbol AS top_gene, t.peptide AS top_peptide,
           (SELECT GROUP_CONCAT(a.allele ORDER BY a.allele SEPARATOR ',')
              FROM run_allele a
             WHERE a.run_id = r.run_id) AS alleles
      FROM pipeline_run r
      JOIN mutation_file f        ON f.file_id = r.file_id
      LEFT JOIN predicted_target t ON t.run_id = r.run_id AND t.rank_position = 1
     WHERE r.researcher_id = :rid
     ORDER BY r.started_at DESC, r.run_id DESC
     LIMIT :limit OFFSET :offset
""")


def _iso(dt) -> Optional[str]:
    return dt.isoformat() if dt else None


def _num(v) -> Optional[float]:
    return float(v) if v is not None else None


def list_runs(db: Session, researcher_id: int, limit: int, offset: int) -> Dict[str, Any]:
    """
    One page of a researcher's runs, newest first.

    started_at has one-second resolution, so run_id breaks ties: two runs in
    the same second still come back in a stable, newest-first order.

    run_allele has no ordering column, so alleles come back alphabetically,
    not in the order they were requested.
    """
    rows = db.execute(
        _RUN_LIST_SQL, {"rid": researcher_id, "limit": limit, "offset": offset}
    ).mappings().all()
    total = db.execute(
        select(func.count()).select_from(PipelineRun)
        .where(PipelineRun.researcher_id == researcher_id)
    ).scalar_one()

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "runs": [{
            "run_id": r["run_id"],
            "status": r["status"],
            "algorithm": r["algorithm"],
            "started_at": _iso(r["started_at"]),
            "finished_at": _iso(r["finished_at"]),
            "duration_ms": r["duration_ms"],
            "targets_returned": r["targets_returned"],
            "best_ic50_nm": _num(r["best_ic50_nm"]),
            "cai_after": _num(r["cai_after"]),
            "error_message": r["error_message"],
            "file_id": r["file_id"],
            "file_name": r["original_name"],
            # Computed, not stored: the schema has no column for it and the
            # application user cannot add one. A stat per row, not a query.
            "file_available": bool(r["stored_path"]) and os.path.exists(r["stored_path"]),
            "alleles": r["alleles"].split(",") if r["alleles"] else [],
            "top_gene": r["top_gene"],
            "top_peptide": r["top_peptide"],
        } for r in rows],
    }


def run_detail(db: Session, run: PipelineRun) -> Dict[str, Any]:
    """
    Everything needed to re-render a past run.

    With the result file present, `result` is the exact JSON the run returned
    and the page renders as it first did. Without it, result is None,
    result_available is False, and the stored rows — targets and headline
    figures — are what's left to show.
    """
    mfile = db.get(MutationFile, run.file_id)
    result = load_result(run)
    return {
        **run_summary(run),
        "file_name": mfile.original_name if mfile else None,
        "file_available": bool(mfile and os.path.exists(mfile.stored_path)),
        "result_available": result is not None,
        "result": result,
    }


_corpus_by_pmid: Optional[Dict[str, Dict[str, Any]]] = None


def _corpus_lookup(pmid: str) -> Optional[Dict[str, Any]]:
    """
    The indexed abstract for a PMID, loaded once from corpus.json.

    message_citation stores which abstracts were cited, not their text. The
    snippet shown under a reopened answer is rebuilt from the corpus with the
    copilot's own trimming, so it matches what was shown the first time.
    """
    global _corpus_by_pmid
    if _corpus_by_pmid is None:
        from .tier4.retriever import CORPUS_PATH
        try:
            with open(CORPUS_PATH, encoding="utf-8") as fh:
                _corpus_by_pmid = {str(d["pmid"]): d for d in json.load(fh)}
        except (OSError, ValueError):
            logger.warning("Corpus unavailable; reopened citations will have no snippet")
            _corpus_by_pmid = {}
    return _corpus_by_pmid.get(str(pmid))


def list_messages(db: Session, run_id: int) -> List[Dict[str, Any]]:
    """A run's conversation in order, each assistant message with its citations."""
    from .tier4.copilot import _snippet

    messages = db.execute(
        select(ChatMessage)
        .where(ChatMessage.run_id == run_id)
        .order_by(ChatMessage.created_at, ChatMessage.message_id)
    ).scalars().all()
    citations = db.execute(
        select(MessageCitation)
        .join(ChatMessage, ChatMessage.message_id == MessageCitation.message_id)
        .where(ChatMessage.run_id == run_id)
        .order_by(MessageCitation.citation_id)
    ).scalars().all()

    by_message: Dict[int, List[Dict[str, Any]]] = {}
    for c in citations:
        doc = _corpus_lookup(c.pmid)
        snippet = (
            _snippet(f"{doc['title']}\n\n{doc.get('abstract', '')}", doc["title"])
            if doc else ""
        )
        by_message.setdefault(c.message_id, []).append({
            "pmid": c.pmid,
            "title": c.title,
            "journal": c.journal,
            "year": c.pub_year,
            "similarity": _num(c.similarity),
            "snippet": snippet,
        })

    return [{
        "message_id": m.message_id,
        "role": m.role,
        "content": m.content,
        "provider": m.provider,
        "created_at": _iso(m.created_at),
        "citations": by_message.get(m.message_id, []) if m.role == "assistant" else [],
    } for m in messages]


def delete_run(db: Session, run: PipelineRun) -> Optional[str]:
    """
    Delete a run and return the result file it owned, for the caller to
    remove once the delete has committed.

    A Core DELETE rather than session.delete(): the foreign keys cascade to
    run_allele, predicted_target, chat_message (and on to message_citation)
    and cross_check_lookup inside the database. The ORM would otherwise try to
    null out any children it had loaded. The mutation_file row is untouched;
    other runs may use the same upload.
    """
    path = run.result_path or result_path_for(run.run_id)
    db.execute(
        delete(PipelineRun)
        .where(PipelineRun.run_id == run.run_id)
        .where(PipelineRun.researcher_id == run.researcher_id)
    )
    return path


def remove_result_file(path: Optional[str]) -> None:
    """Remove a result file, but only one inside RESULTS_DIR."""
    if not path:
        return
    root = os.path.realpath(RESULTS_DIR)
    real = os.path.realpath(path)
    if os.path.commonpath([root, real]) != root:
        logger.warning("Refusing to delete result file outside %s: %s", root, path)
        return
    try:
        os.remove(real)
    except FileNotFoundError:
        pass
    except OSError:
        logger.exception("Could not delete result file %s", real)


_STATS_SQL = text("""
    SELECT
      (SELECT COUNT(*)                FROM pipeline_run WHERE researcher_id = :rid) AS runs,
      (SELECT COUNT(DISTINCT file_id) FROM pipeline_run WHERE researcher_id = :rid) AS files,
      (SELECT COALESCE(SUM(targets_returned), 0)
                                      FROM pipeline_run WHERE researcher_id = :rid
                                                          AND status = 'completed') AS targets,
      (SELECT MIN(best_ic50_nm)       FROM pipeline_run WHERE researcher_id = :rid
                                                          AND status = 'completed') AS best_ic50,
      (SELECT COUNT(*)                FROM chat_message WHERE researcher_id = :rid) AS messages
""")


def my_stats(db: Session, researcher_id: int) -> Dict[str, Any]:
    """
    The dashboard header, in one statement. Every subquery is served by an
    index on researcher_id. Targets are summed from the denormalised
    targets_returned column rather than counted from predicted_target — the
    reason that column exists.
    """
    r = db.execute(_STATS_SQL, {"rid": researcher_id}).mappings().one()
    return {
        "total_runs": int(r["runs"]),
        "distinct_files": int(r["files"]),
        "total_targets": int(r["targets"]),
        "best_ic50_nm": _num(r["best_ic50"]),
        "copilot_messages": int(r["messages"]),
    }


# ---------------------------------------------------------------- formulation
# Tier 5 worksheets. One formulation_spec row and one formulation_lipid row
# per lipid, written together in one transaction so a saved worksheet is
# never missing its lipid table.

class ValueTooWide(ValueError):
    """
    A computed value will not fit the DECIMAL column it is bound for.

    Raised rather than silently dropped. Elsewhere in this module `_dec`
    returns None for an out-of-range score, because one odd score must not
    cost a whole run its record and the column is nullable. A formulation's
    columns are NOT NULL and every one of them is load-bearing arithmetic, so
    the only honest options are to store the real value or to refuse. A
    truncated lipid mass that still looked plausible would be the worst
    outcome of the three.
    """


def _exact(value: Any, places: int, digits: int, name: str, unit: str) -> Decimal:
    """One value as a Decimal guaranteed to fit DECIMAL(digits, places)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        raise ValueTooWide(f"{name} is not a number.") from None
    if not math.isfinite(f):
        raise ValueTooWide(f"{name} is not a finite number.")

    limit = 10 ** (digits - places)
    if abs(f) >= limit:
        raise ValueTooWide(
            f"{name} works out to {f:,.4g} {unit}, which is beyond what this "
            f"worksheet can store (under {limit:,g}). Check the body weight, "
            "dose per kg and sequence length."
        )
    return Decimal(str(round(f, places)))


def _plain(envelope: Any) -> Any:
    """The number out of a provenance envelope."""
    return envelope["value"] if isinstance(envelope, dict) else envelope


def record_formulation(db: Session, run: PipelineRun, researcher_id: int,
                       worksheet: Dict[str, Any]) -> FormulationSpec:
    """
    Persist one worksheet. Does not commit; the route closes the transaction.

    The lipid rows snapshot the molar percentage and molecular weight they
    were computed with rather than referencing tier5.constants, so correcting
    a published constant later cannot change a sheet that is already saved.
    """
    seq = worksheet["sequence"]
    inp = worksheet["inputs"]
    amt = worksheet["amounts"]
    preset = worksheet["preset"]
    size = worksheet["particle_size"]

    spec = FormulationSpec(
        run_id=run.run_id,
        researcher_id=researcher_id,

        nucleotide_length=int(_plain(seq["nucleotide_length"])),
        count_a=int(_plain(seq["count_a"])),
        count_u=int(_plain(seq["count_u"])),
        count_g=int(_plain(seq["count_g"])),
        count_c=int(_plain(seq["count_c"])),
        molecular_weight_da=_exact(
            _plain(seq["molecular_weight_da"]), 2, 14, "The molecular weight", "Da"),

        patient_weight_kg=_exact(
            _plain(inp["patient_weight_kg"]), 2, 5, "The body weight", "kg"),
        dose_per_kg_mcg=_exact(
            _plain(inp["dose_per_kg_mcg"]), 3, 6, "The dose per kg", "ug/kg"),
        concentration_mcg_ml=_exact(
            _plain(inp["concentration_mcg_ml"]), 2, 8, "The concentration", "ug/mL"),
        np_ratio=_exact(_plain(inp["np_ratio"]), 2, 5, "The N/P ratio", ""),
        route=_text(_plain(inp["route"]), 60) or "",
        schedule_label=_text(_plain(inp["schedule"]), 120) or "",

        dose_mcg=_exact(_plain(amt["dose_mcg"]), 3, 10, "The dose", "ug"),
        injection_volume_ml=_exact(
            _plain(amt["injection_volume_ml"]), 3, 8, "The injection volume", "mL"),
        mrna_nanomoles=_exact(
            _plain(amt["mrna_nanomoles"]), 6, 12, "The mRNA amount", "nmol"),
        phosphate_micromoles=_exact(
            _plain(amt["phosphate_micromoles"]), 6, 12,
            "The RNA phosphate amount", "umol"),
        total_lipid_mass_mg=_exact(
            _plain(amt["total_lipid_mass_mg"]), 4, 10, "The total lipid mass", "mg"),

        preset_key=_text(preset["key"], 40) or "",
        preset_label=_text(preset["label"], 120) or "",
        preset_citation=_text(preset["citation"], 300) or "",
        target_size_nm_min=int(_plain(size["target_size_nm_min"])),
        target_size_nm_max=int(_plain(size["target_size_nm_max"])),
    )
    db.add(spec)
    db.flush()          # assigns formulation_id for the lipid rows below

    for lipid in worksheet["lipids"]:
        db.add(FormulationLipid(
            formulation_id=spec.formulation_id,
            role=lipid["role"],
            lipid_name=_text(lipid["name"], 80) or "",
            molar_pct=_exact(
                _plain(lipid["molar_pct"]), 2, 5,
                f"{lipid['name']}'s molar percentage", "mol%"),
            molecular_weight_da=_exact(
                _plain(lipid["molecular_weight_da"]), 2, 10,
                f"{lipid['name']}'s molecular weight", "Da"),
            micromoles=_exact(
                _plain(lipid["micromoles"]), 6, 12,
                f"The {lipid['name']} amount", "umol"),
            mass_mg=_exact(
                _plain(lipid["mass_mg"]), 4, 10,
                f"The {lipid['name']} mass", "mg"),
        ))
    db.flush()
    return spec


def formulation_row(spec: FormulationSpec) -> Dict[str, Any]:
    """
    A saved spec as the history list shows it: the headline figures only.

    The full worksheet is recomputed on demand rather than stored as JSON, so
    this is deliberately a summary and says which preset produced it.
    """
    return {
        "formulation_id": spec.formulation_id,
        "run_id": spec.run_id,
        "created_at": _iso(spec.created_at),
        "preset_key": spec.preset_key,
        "preset_label": spec.preset_label,
        "preset_citation": spec.preset_citation,
        "nucleotide_length": int(spec.nucleotide_length),
        "molecular_weight_da": _num(spec.molecular_weight_da),
        "patient_weight_kg": _num(spec.patient_weight_kg),
        "dose_per_kg_mcg": _num(spec.dose_per_kg_mcg),
        "concentration_mcg_ml": _num(spec.concentration_mcg_ml),
        "np_ratio": _num(spec.np_ratio),
        "route": spec.route,
        "schedule_label": spec.schedule_label,
        "dose_mcg": _num(spec.dose_mcg),
        "injection_volume_ml": _num(spec.injection_volume_ml),
        "total_lipid_mass_mg": _num(spec.total_lipid_mass_mg),
        "lipids": [
            {
                "role": l.role,
                "name": l.lipid_name,
                "molar_pct": _num(l.molar_pct),
                "molecular_weight_da": _num(l.molecular_weight_da),
                "micromoles": _num(l.micromoles),
                "mass_mg": _num(l.mass_mg),
            }
            for l in spec.lipids
        ],
    }


def list_formulations(db: Session, run_id: int) -> List[Dict[str, Any]]:
    """Saved worksheets for one run, newest first. Ownership is the caller's."""
    specs = db.scalars(
        select(FormulationSpec)
        .where(FormulationSpec.run_id == run_id)
        .order_by(FormulationSpec.created_at.desc(), FormulationSpec.formulation_id.desc())
    ).all()
    return [formulation_row(s) for s in specs]


def get_owned_formulation(db: Session, researcher_id: int,
                          formulation_id: int) -> Optional[FormulationSpec]:
    """
    One saved worksheet, scoped to its owner.

    Filtered on researcher_id like every other lookup here: someone else's
    formulation_id comes back None and the route turns that into 404.
    """
    return db.scalars(
        select(FormulationSpec).where(
            FormulationSpec.formulation_id == formulation_id,
            FormulationSpec.researcher_id == researcher_id,
        )
    ).first()
