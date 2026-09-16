"""
CellSpark API — FastAPI backend.

Run from the backend/ folder:
    uvicorn app.main:app --reload --reload-dir app
"""

from typing import List, Literal, Optional

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .pipeline import run_pipeline, run_tier1
from .tier4.copilot import answer as copilot_answer
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
    """
    try:
        return copilot_answer(req.question, req.result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Copilot failed: {e}")