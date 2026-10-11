"""
CellSpark API — FastAPI backend.

Run from the backend/ folder:
    uvicorn app.main:app --reload --reload-dir app
"""

from typing import List, Literal, Optional

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import auth
from .db import get_db
from .models import Researcher
from .pipeline import run_pipeline, run_tier1
from .tier4.copilot import answer as copilot_answer, cross_check as copilot_cross_check
from .tier4.retriever import corpus_info
from .upload import save_upload

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
        description="ID returned by /api/upload. Omit to use the demo dataset.",
    )
    sample_barcode: Optional[str] = Field(
        default=None,
        description="Restrict to one patient, e.g. TCGA-XX-XXXX",
    )


class CopilotRequest(BaseModel):
    question: str = Field(..., description="Clinician's question about the run")
    result: dict = Field(..., description="The pipeline result being asked about")
    history: Optional[list] = Field(
        default=None,
        description=(
            "Recent conversation turns, oldest first. Optional — the copilot "
            "answers a single question fine without it. Only the last few "
            "turns are used."
        ),
    )


class CrossCheckRequest(BaseModel):
    gene: str = Field(..., description="Gene symbol, e.g. KRAS")
    change: str = Field(default="", description="Protein change, e.g. p.G12D")
    result: dict = Field(default_factory=dict, description="The pipeline result in view")


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


@app.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    """
    Accept a mutation file and report what was found in it.

    Validates immediately so a malformed file fails here with a clear message
    rather than thirty seconds into a pipeline run.
    """
    try:
        content = await file.read()
        return save_upload(file.filename, content)
    except ValueError as e:
        # user-fixable problem — 400, with the reason
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")


@app.post("/api/pipeline/run")
def pipeline_run(req: PipelineRequest):
    """
    Run the full pipeline against either an uploaded file or the demo dataset.

    Tier 4 answers on demand through /api/copilot/ask rather than as part of
    the run.
    """
    try:
        return run_pipeline(
            alleles=req.alleles,
            file_name=req.file_name,
            algorithm=req.algorithm,
            upload_id=req.upload_id,
            sample_barcode=req.sample_barcode,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Pipeline failed: {e}")


@app.get("/api/tier1/run")
def tier1_run(algorithm: str = "kmp", max_mutations: int = 30):
    """Tier 1 on its own — handy for testing without the frontend."""
    if algorithm not in ("kmp", "boyer_moore", "naive"):
        raise HTTPException(status_code=400, detail=f"Unknown algorithm: {algorithm}")
    return run_tier1(algorithm=algorithm, max_mutations=max_mutations)


@app.post("/api/copilot/cross-check")
def copilot_cross_check_route(req: CrossCheckRequest):
    """
    Report what the indexed corpus says about one gene and alteration.

    This reports on CellSpark's own ~618-abstract index and nothing more. A
    gene missing from it is a gap in the index, not a finding about the gene,
    and the response's "caveat" field says so in every state — the frontend
    shows it unconditionally.
    """
    try:
        return copilot_cross_check(req.gene, req.change, req.result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cross-check failed: {e}")


@app.get("/api/corpus/info")
def corpus_status():
    """What literature is indexed, so the UI can report it."""
    return corpus_info()


@app.post("/api/copilot/ask")
def copilot_ask(req: CopilotRequest):
    """
    Answer a question about a pipeline run.

    Grounded in two sources: the run's own numbers, and retrieved PubMed
    abstracts. Every response carries its citations.

    The response's "provider" field reports which path produced the answer —
    the configured model, or the template fallback when generation is
    unavailable.
    """
    try:
        return copilot_answer(req.question, req.result, history=req.history)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Copilot failed: {e}")


# ------------------------------------------------------------ auth
# Phase 1: accounts only. The pipeline and copilot routes above stay open;
# phase 2 attaches runs, uploads and chats to the signed-in researcher.

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
