"""
File upload handling.

Accepts a MAF file from the clinician, validates it's parseable, and
stores it in a temp directory keyed by an upload ID. The pipeline then reads
from that path instead of the synthetic demo dataset.

WHY VALIDATE ON UPLOAD:
A malformed file should fail immediately with a clear message, not thirty
seconds into a pipeline run with a stack trace. We parse just enough to
confirm the required columns exist and at least one missense mutation is
present, then report what we found so the user can see their file was
understood before committing to a run.
"""

import hashlib
import os
import tempfile
import uuid
from typing import Dict, Any

from .tier1.maf_parser import load_maf

UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "cellspark_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

MAX_BYTES = 50 * 1024 * 1024   # 50 MB — a single-cohort MAF is well under this


def sha256_hex(content: bytes) -> str:
    """Content hash — what mutation_file deduplicates on, per researcher."""
    return hashlib.sha256(content).hexdigest()


def describe_upload(path: str, filename: str, size_bytes: int) -> Dict[str, Any]:
    """
    Parse a stored MAF and report what was found in it.

    Raises ValueError with a user-facing message if the file is unusable.
    Leaves the file where it is either way; the caller decides what to keep.
    """
    try:
        mutations = load_maf(path)
    except ValueError as e:
        raise ValueError(str(e))
    except Exception as e:
        raise ValueError(f"Could not parse this file: {e}")

    if not mutations:
        raise ValueError(
            "No missense mutations found. CellSpark needs a MAF with a "
            "Variant_Classification column containing Missense_Mutation rows."
        )

    samples = sorted({m.sample_barcode for m in mutations})
    genes = sorted({m.gene for m in mutations})

    return {
        "filename": filename,
        "size_bytes": size_bytes,
        "missense_mutations": len(mutations),
        "samples": samples[:20],
        "sample_count": len(samples),
        "distinct_genes": len(genes),
        "example_genes": genes[:8],
    }


def save_upload(filename: str, content: bytes, dest_path: str = None) -> Dict[str, Any]:
    """
    Persist an uploaded file and report what was found in it.

    Returns an upload_id the pipeline uses to find the file again, plus the
    stored path and SHA-256 for the mutation_file row. dest_path rewrites a
    known location instead of minting a new one; the upload route uses it
    when a deduplicated file has since been cleared out of the temp directory.
    """
    if len(content) > MAX_BYTES:
        raise ValueError(
            f"File is {len(content) // (1024*1024)} MB. The limit is "
            f"{MAX_BYTES // (1024*1024)} MB — try a single-cohort export."
        )

    if not content.strip():
        raise ValueError("File is empty.")

    safe_name = os.path.basename(filename or "") or "upload.maf"
    if dest_path is None:
        upload_id = uuid.uuid4().hex[:12]
        path = os.path.join(UPLOAD_DIR, f"{upload_id}_{safe_name}")
    else:
        path = dest_path
        upload_id = upload_id_for(dest_path)

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(content)

    # Parse now so problems surface here rather than mid-pipeline
    try:
        info = describe_upload(path, safe_name, len(content))
    except ValueError:
        os.remove(path)
        raise

    return {
        "upload_id": upload_id,
        **info,
        "stored_path": path,
        "sha256": sha256_hex(content),
    }


def upload_id_for(stored_path: str) -> str:
    """The upload_id a stored file was saved under — the prefix before '_'."""
    return os.path.basename(stored_path).split("_", 1)[0]


def get_upload_path(upload_id: str) -> str:
    """Resolve an upload ID back to a file path."""
    for name in os.listdir(UPLOAD_DIR):
        if name.startswith(f"{upload_id}_"):
            return os.path.join(UPLOAD_DIR, name)
    raise FileNotFoundError(f"Upload {upload_id} not found — it may have expired.")