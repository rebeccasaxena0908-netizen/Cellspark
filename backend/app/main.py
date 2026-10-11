"""
CellSpark API — FastAPI backend.

Run from the backend/ folder:
    uvicorn app.main:app --reload --reload-dir app
"""

import logging
import os
import time
from typing import List, Literal, Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from . import auth, records
from .db import get_db
from .models import Researcher
from .pipeline import run_pipeline, run_tier1
from .tier4.copilot import (
    HISTORY_TURNS,
    answer as copilot_answer,
    cross_check as copilot_cross_check,
)
from .tier4.retriever import corpus_info
from .upload import describe_upload, save_upload, sha256_hex, upload_id_for

logger = logging.getLogger("cellspark.api")

app = FastAPI(
    title="CellSpark API",
    description="Neoantigen identification and mRNA vaccine design pipeline",
    version="0.4.0",
)

# The Vite dev server is a different origin, so the browser blocks requests
# without this.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RequestValidationError)
async def scrub_auth_validation_errors(request: Request, exc: RequestValidationError):
    """
    FastAPI's default 422 echoes the offending input back, and for a body
    with a missing field that "input" is the whole body, password included.
    On auth routes, drop it, so a plaintext password never appears in an
    error response. Every other route keeps the default behaviour.
    """
    if not request.url.path.startswith("/api/auth/"):
        return await request_validation_exception_handler(request, exc)
    errors = [
        {k: v for k, v in err.items() if k not in ("input", "ctx", "url")}
        for err in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


@app.exception_handler(SQLAlchemyError)
async def database_error(request: Request, exc: SQLAlchemyError):
    """
    Any database error that reaches the top becomes a plain 503.

    The full exception goes to the server log only. A driver error can carry
    the host, the SQL and its parameters; none of that belongs in a response.
    """
    logger.exception("Database error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=503,
        content={"detail": "The database is unavailable. Try again shortly."},
    )


# ------------------------------------------------------------ schemas
class PipelineRequest(BaseModel):
    """
    Pydantic validates and documents this automatically — a bad request gets
    a clear 422 instead of a crash deep inside the pipeline.
    """
    alleles: List[str] = Field(
        default=["HLA-A*02:01"],
        description="Patient HLA alleles, e.g. HLA-A*02:01",
    )
    file_name: str = Field(
        default="sample_patient.maf",
        description="Name of the uploaded mutation file",
    )
    algorithm: Literal["kmp", "boyer_moore", "naive"] = Field(
        default="kmp",
        description="String matching algorithm used for tolerance screening",
    )
    upload_id: Optional[str] = Field(
        default=None,
        description=(
            "upload_id returned by /api/upload (the mutation_file id). Omit "
            "to use the demo dataset."
        ),
    )
    sample_barcode: Optional[str] = Field(
        default=None,
        description="Restrict to one patient, e.g. TCGA-XX-XXXX",
    )


# The copilot and cross-check requests name a run by id; the server loads
# that run's stored result and, for the copilot, its stored conversation.
# Clients that still send "result" or "history" are not rejected: unknown
# fields are ignored, so neither can influence the answer.

class CopilotRequest(BaseModel):
    run_id: int = Field(..., description="The run being asked about")
    question: str = Field(..., min_length=1, max_length=4000,
                          description="Clinician's question about the run")


class CrossCheckRequest(BaseModel):
    run_id: int = Field(..., description="The run the target came from")
    gene: str = Field(..., max_length=30, description="Gene symbol, e.g. KRAS")
    change: str = Field(default="", max_length=30, description="Protein change, e.g. p.G12D")


class SignupRequest(BaseModel):
    email: str
    display_name: str
    password: str
    institution: Optional[str] = None


class LoginRequest(BaseModel):
    email: str
    password: str


# ------------------------------------------------------------ routes
@app.get("/")
def root():
    return {"service": "CellSpark API", "docs": "/docs", "health": "/api/health"}


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "cellspark", "version": "0.4.0"}


# Everything below requires a signed-in researcher, and everything that names
# a file or run by id is scoped to that researcher: someone else's id is a
# 404, the same as an id that does not exist. A 403 would confirm it does.

NOT_FOUND_RUN = "Run not found."
NOT_FOUND_UPLOAD = "Upload not found."


def _owned_run(db: Session, researcher: Researcher, run_id: int):
    run = records.get_owned_run(db, researcher.researcher_id, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND_RUN)
    return run


def _stored_result(run):
    """The result the copilot reads: the server's copy, never the client's."""
    result = records.load_result(run) if run.status == "completed" else None
    if result is None:
        raise HTTPException(
            status_code=409,
            detail="This run has no stored result to ask about. Run the analysis again.",
        )
    return result


@app.post("/api/upload")
async def upload_file(
    file: UploadFile = File(...),
    researcher: Researcher = Depends(auth.require_researcher),
    db: Session = Depends(get_db),
):
    """
    Accept a mutation file and report what was found in it.

    Validates immediately so a malformed file fails here with a clear message
    rather than thirty seconds into a pipeline run.

    Deduplicated per researcher by SHA-256: uploading the same file again
    returns the existing mutation_file row ("reused": true) instead of
    creating a second one.
    """
    rid = researcher.researcher_id
    content = await file.read()
    digest = sha256_hex(content)

    try:
        existing = records.find_file(db, rid, digest)
        if existing:
            if os.path.exists(existing.stored_path):
                info = describe_upload(existing.stored_path, existing.original_name, len(content))
            else:
                # Same bytes as before, but the stored copy has gone missing.
                # Put them back where the row says they are.
                info = save_upload(existing.original_name, content, dest_path=existing.stored_path)
            row, created = existing, False
        else:
            info = save_upload(file.filename, content, owner=rid)
            try:
                row, created = records.add_file(
                    db, rid,
                    original_name=info["filename"],
                    stored_path=info["stored_path"],
                    sha256=digest,
                    size_bytes=len(content),
                    mutation_count=info["missense_mutations"],
                )
                db.commit()
            except Exception:
                db.rollback()
                os.remove(info["stored_path"])
                raise
            if not created:
                # Lost a race with an identical upload; keep the winner's copy.
                os.remove(info["stored_path"])
    except ValueError as e:
        # user-fixable problem — 400, with the reason
        raise HTTPException(status_code=400, detail=str(e))
    except SQLAlchemyError:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")

    info.pop("stored_path", None)       # server paths stay on the server
    info.pop("sha256", None)
    info.update(upload_id=str(row.file_id), file_id=row.file_id, reused=not created)
    return info


@app.post("/api/pipeline/run")
def pipeline_run(
    req: PipelineRequest,
    researcher: Researcher = Depends(auth.require_researcher),
    db: Session = Depends(get_db),
):
    """
    Run the full pipeline against either an uploaded file or the demo dataset.

    Recorded in two commits, deliberately:
      1. pipeline_run ('running') and its run_allele rows, committed before
         the pipeline starts, so a crash still leaves a record.
      2. The completion update and every predicted_target row, committed
         together, so a run is never left with half its targets.

    The result JSON is written to disk before step 2. If step 2 fails the
    researcher still gets the result; the run is marked failed with an
    explanation, and the error is logged.

    Tier 4 answers on demand through /api/copilot/ask rather than as part of
    the run.
    """
    rid = researcher.researcher_id

    # run_allele's primary key is (run_id, allele): repeats would collide
    alleles = list(dict.fromkeys(a.strip() for a in req.alleles if a and a.strip()))
    if not alleles:
        alleles = ["HLA-A*02:01"]
    if any(len(a) > 20 for a in alleles):
        raise HTTPException(status_code=422, detail="Allele names are at most 20 characters.")

    if req.upload_id:
        try:
            file_id = int(req.upload_id)
        except ValueError:
            raise HTTPException(status_code=404, detail=NOT_FOUND_UPLOAD)
        mfile = records.get_owned_file(db, rid, file_id)
        if mfile is None:
            raise HTTPException(status_code=404, detail=NOT_FOUND_UPLOAD)
        if not os.path.exists(mfile.stored_path):
            raise HTTPException(
                status_code=404,
                detail="The uploaded file has expired from temporary storage. Upload it again.",
            )
        disk_upload_id = upload_id_for(mfile.stored_path)
    else:
        mfile = records.demo_file(db, rid)
        disk_upload_id = None

    run = records.start_run(db, rid, mfile.file_id, req.algorithm, alleles)
    db.commit()
    run_id = run.run_id

    t0 = time.monotonic()
    elapsed = lambda: int((time.monotonic() - t0) * 1000)

    try:
        result = run_pipeline(
            alleles=alleles,
            file_name=req.file_name,
            algorithm=req.algorithm,
            upload_id=disk_upload_id,
            sample_barcode=req.sample_barcode,
        )
    except FileNotFoundError as e:
        records.fail_run(db, run_id, f"FileNotFoundError: {e}", elapsed())
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        records.fail_run(db, run_id, f"{type(e).__name__}: {e}", elapsed())
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {e}")

    duration_ms = elapsed()
    result["run_id"] = run_id

    # Disk first: once the file exists, nothing below can lose the result.
    try:
        path = records.write_result(run_id, result)
    except OSError as e:
        logger.exception("Run %s completed but its result file could not be written", run_id)
        records.fail_run(db, run_id, f"Completed, but the result file could not be written: {e}",
                         duration_ms)
        return result

    try:
        records.complete_run(db, run, result, path, duration_ms)
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("Run %s completed but recording it failed", run_id)
        records.fail_run(
            db, run_id,
            "The pipeline completed but its results could not be recorded. "
            "The full result was saved to result_path.",
            duration_ms, result_path=path,
        )
    return result


# ------------------------------------------------------------ history
@app.get("/api/runs")
def list_runs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    researcher: Researcher = Depends(auth.require_researcher),
    db: Session = Depends(get_db),
):
    """The caller's runs, newest first, one page at a time."""
    return records.list_runs(db, researcher.researcher_id, limit, offset)


@app.get("/api/runs/{run_id}")
def get_run(
    run_id: int,
    researcher: Researcher = Depends(auth.require_researcher),
    db: Session = Depends(get_db),
):
    """
    One of the caller's runs: the stored record, and the full result JSON so
    it can be re-rendered as it first appeared. If the result file is gone,
    result is null and result_available is false; the stored targets remain.
    """
    run = _owned_run(db, researcher, run_id)
    return records.run_detail(db, run)


@app.get("/api/runs/{run_id}/messages")
def get_run_messages(
    run_id: int,
    researcher: Researcher = Depends(auth.require_researcher),
    db: Session = Depends(get_db),
):
    """The copilot conversation for a run, oldest first, with citations."""
    run = _owned_run(db, researcher, run_id)
    return {"run_id": run.run_id, "messages": records.list_messages(db, run.run_id)}


@app.delete("/api/runs/{run_id}")
def delete_run(
    run_id: int,
    researcher: Researcher = Depends(auth.require_researcher),
    db: Session = Depends(get_db),
):
    """
    Permanently delete a run, its targets, chat and cross-checks, and its
    result file. The uploaded file and its row are kept: other runs may use
    them.

    The file goes only after the delete commits. A failed commit leaves the
    run whole; a failed file removal leaves an orphan file and a log line,
    which is the better way round.
    """
    run = _owned_run(db, researcher, run_id)
    path = records.delete_run(db, run)
    db.commit()
    records.remove_result_file(path)
    return {"deleted": run_id}


@app.get("/api/me/stats")
def my_stats(
    researcher: Researcher = Depends(auth.require_researcher),
    db: Session = Depends(get_db),
):
    """Summary figures for the history view's header."""
    return records.my_stats(db, researcher.researcher_id)


@app.get("/api/tier1/run")
def tier1_run(
    algorithm: str = "kmp",
    max_mutations: int = 30,
    researcher: Researcher = Depends(auth.require_researcher),
):
    """Tier 1 on its own — handy for testing without the frontend. Not recorded."""
    if algorithm not in ("kmp", "boyer_moore", "naive"):
        raise HTTPException(status_code=400, detail=f"Unknown algorithm: {algorithm}")
    return run_tier1(algorithm=algorithm, max_mutations=max_mutations)


@app.post("/api/copilot/cross-check")
def copilot_cross_check_route(
    req: CrossCheckRequest,
    researcher: Researcher = Depends(auth.require_researcher),
    db: Session = Depends(get_db),
):
    """
    Report what the indexed corpus says about one gene and alteration.

    This reports on CellSpark's own ~618-abstract index and nothing more. A
    gene missing from it is a gap in the index, not a finding about the gene,
    and the response's "caveat" field says so in every state — the frontend
    shows it unconditionally.

    Every lookup is recorded in cross_check_lookup, not_covered included.
    """
    run = _owned_run(db, researcher, req.run_id)
    result = _stored_result(run)
    try:
        response = copilot_cross_check(req.gene, req.change, result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cross-check failed: {e}")

    try:
        records.record_cross_check(db, run, researcher.researcher_id, req.gene, req.change, response)
        db.commit()
    except Exception:
        # The lookup itself succeeded; losing its log row is not worth failing it.
        db.rollback()
        logger.exception("Could not record cross-check for run %s", run.run_id)
    return response


@app.get("/api/corpus/info")
def corpus_status(researcher: Researcher = Depends(auth.require_researcher)):
    """What literature is indexed, so the UI can report it."""
    return corpus_info()


@app.post("/api/copilot/ask")
def copilot_ask(
    req: CopilotRequest,
    researcher: Researcher = Depends(auth.require_researcher),
    db: Session = Depends(get_db),
):
    """
    Answer a question about a pipeline run.

    Grounded in two sources: the run's own numbers, and retrieved PubMed
    abstracts. Every response carries its citations.

    The run's result and the conversation so far are both loaded from the
    server's own records, not taken from the request: a client-supplied
    history could contain answers the copilot never gave.

    The response's "provider" field reports which path produced the answer —
    the configured model, or the template fallback when generation is
    unavailable. The same value is stored on the assistant message.
    """
    run = _owned_run(db, researcher, req.run_id)
    result = _stored_result(run)
    history = records.load_history(db, run.run_id, limit=HISTORY_TURNS * 2)

    try:
        response = copilot_answer(req.question, result, history=history)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Copilot failed: {e}")

    try:
        records.record_chat(db, run, researcher.researcher_id, req.question, response)
        db.commit()
    except Exception:
        # The answer is still good; it just won't be in the stored history.
        db.rollback()
        logger.exception("Could not record copilot exchange for run %s", run.run_id)
    return response


# ------------------------------------------------------------ auth
# Signup and login are the only routes besides / and /api/health that work
# without a session.

INVALID_LOGIN = "Invalid email or password"


@app.post("/api/auth/signup", status_code=201)
def auth_signup(
    req: SignupRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Create an account and sign straight in."""
    try:
        email = auth.normalise_email(req.email)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    display_name = req.display_name.strip()
    if not display_name:
        raise HTTPException(status_code=422, detail="Display name is required.")
    if len(display_name) > 100:
        raise HTTPException(status_code=422, detail="Display name must be at most 100 characters.")

    institution = (req.institution or "").strip() or None
    if institution and len(institution) > 150:
        raise HTTPException(status_code=422, detail="Institution must be at most 150 characters.")

    problem = auth.password_problem(req.password)
    if problem:
        raise HTTPException(status_code=422, detail=problem)

    # Trade-off: this 409 tells the caller the address has an account, which
    # login deliberately never does. It can't be avoided without email
    # verification: the person signing up needs to know why it failed.
    # Login, where enumeration matters most, stays generic.
    taken = "An account with this email already exists. Sign in instead."
    if db.execute(select(Researcher.researcher_id).where(Researcher.email == email)).first():
        raise HTTPException(status_code=409, detail=taken)

    researcher = Researcher(
        email=email,
        display_name=display_name,
        institution=institution,
        password_hash=auth.hash_password(req.password),
        last_login_at=func.now(),
    )
    db.add(researcher)
    try:
        db.flush()
    except IntegrityError:
        # Two signups for the same address raced past the check above.
        db.rollback()
        raise HTTPException(status_code=409, detail=taken)

    token = auth.create_session(db, researcher, request)
    db.commit()
    db.refresh(researcher)

    auth.set_session_cookie(response, token)
    return auth.public_profile(researcher)


@app.post("/api/auth/login")
def auth_login(
    req: LoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """
    One message for every failure, whether the email is unknown or the
    password is wrong. bcrypt runs either way (against a dummy hash for an
    unknown email), so response time does not reveal which it was.
    """
    researcher = db.execute(
        select(Researcher).where(Researcher.email == auth.lookup_email(req.email))
    ).scalar_one_or_none()

    ok = auth.verify_password(req.password, researcher.password_hash if researcher else None)
    if not ok:
        raise HTTPException(status_code=401, detail=INVALID_LOGIN)

    # Replace rather than accumulate: a cookie already in this browser
    # belongs to an earlier session, which this login supersedes.
    auth.delete_session(db, request.cookies.get(auth.COOKIE_NAME))

    researcher.last_login_at = func.now()
    token = auth.create_session(db, researcher, request)
    db.commit()
    db.refresh(researcher)

    auth.set_session_cookie(response, token)
    return auth.public_profile(researcher)


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response, db: Session = Depends(get_db)):
    """Delete the session row, not just the cookie, so the token is dead."""
    auth.delete_session(db, request.cookies.get(auth.COOKIE_NAME))
    db.commit()
    auth.clear_session_cookie(response)
    return {"signed_out": True}


@app.get("/api/auth/me")
def auth_me(researcher: Researcher = Depends(auth.require_researcher)):
    return auth.public_profile(researcher)
