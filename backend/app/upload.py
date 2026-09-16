"""
File upload handling.

Accepts a MAF/VCF file from the clinician, validates it's parseable, and
stores it in a temp directory keyed by an upload ID. The pipeline then reads
from that path instead of the synthetic demo dataset.

WHY VALIDATE ON UPLOAD:
A malformed file should fail immediately with a clear message, not thirty
seconds into a pipeline run with a stack trace. We parse just enough to
confirm the required columns exist and at least one missense mutation is
present, then report what we found so the user can see their file was
understood before committing to a run.
"""

import os
import tempfile
import uuid
from typing import Dict, Any

from .tier1.maf_parser import load_maf

UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "cellspark_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

MAX_BYTES = 50 * 1024 * 1024   # 50 MB — a single-cohort MAF is well under this


def save_upload(filename: str, content: bytes) -> Dict[str, Any]:
    """
    Persist an uploaded file and report what was found in it.

    Returns an upload_id the client passes back when running the pipeline.
    """
    if len(content) > MAX_BYTES:
        raise ValueError(
            f"File is {len(content) // (1024*1024)} MB. The limit is "
            f"{MAX_BYTES // (1024*1024)} MB — try a single-cohort export."
        )

    if not content.strip():
        raise ValueError("File is empty.")

    upload_id = uuid.uuid4().hex[:12]
    safe_name = os.path.basename(filename) or "upload.maf"
    path = os.path.join(UPLOAD_DIR, f"{upload_id}_{safe_name}")

    with open(path, "wb") as fh:
        fh.write(content)

    # Parse now so problems surface here rather than mid-pipeline
    try:
        mutations = load_maf(path)
    except ValueError as e:
        os.remove(path)
        raise ValueError(str(e))
    except Exception as e:
        os.remove(path)
        raise ValueError(f"Could not parse this file: {e}")

    if not mutations:
        os.remove(path)
        raise ValueError(
            "No missense mutations found. CellSpark needs a MAF with a "
            "Variant_Classification column containing Missense_Mutation rows."
        )

    samples = sorted({m.sample_barcode for m in mutations})
    genes = sorted({m.gene for m in mutations})

    return {
        "upload_id": upload_id,
        "filename": safe_name,
        "size_bytes": len(content),
        "missense_mutations": len(mutations),
        "samples": samples[:20],
        "sample_count": len(samples),
        "distinct_genes": len(genes),
        "example_genes": genes[:8],
    }


def get_upload_path(upload_id: str) -> str:
    """Resolve an upload ID back to a file path."""
    for name in os.listdir(UPLOAD_DIR):
        if name.startswith(f"{upload_id}_"):
            return os.path.join(UPLOAD_DIR, name)
    raise FileNotFoundError(f"Upload {upload_id} not found — it may have expired.")