"""
Object storage for uploaded MAF files and result documents.

One small interface, two backends:

    save(key, data) -> locator
    load(locator)   -> bytes
    exists(locator) -> bool
    delete(locator) -> None

WRITES follow the STORAGE environment variable: "local" (the default) or "s3".
READS DO NOT. load/exists/delete look at the locator itself: "s3://bucket/key"
goes to S3, anything else is a filesystem path. A row written before S3 was
switched on holds a local path and must still open when STORAGE=s3, and the
reverse holds too.

S3 is additive, never load-bearing. With STORAGE unset nothing here touches
the network, boto3 is not imported, and behaviour is exactly what it was when
the application wrote straight to disk. If S3 becomes unreachable (Learner Lab
credentials are temporary), the caller gets StorageError with a readable
message and the fix is to set STORAGE=local.

Credentials come from the environment (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
AWS_SESSION_TOKEN, AWS_REGION) and are never logged, echoed or put in an error.
"""

import logging
import os
from typing import Optional

from . import db as _db   # noqa: F401  (importing it loads backend/.env)

logger = logging.getLogger("cellspark.storage")

S3_SCHEME = "s3://"

UNAVAILABLE = (
    "Object storage is unavailable (AWS credentials may have expired). "
    "Set STORAGE=local to continue."
)


class StorageError(OSError):
    """
    Object storage could not be reached or refused the request.

    An OSError subclass on purpose: every caller already treats a failed
    file operation as OSError, so a dead S3 degrades the same way a full disk
    does. str() is always the fixed readable message — never the AWS error.
    """

    def __init__(self, message: str = UNAVAILABLE):
        super().__init__(message)

    def __str__(self) -> str:
        return self.args[0]


# ---------------------------------------------------------------- selection
def backend_name() -> str:
    """Where new data is written: 'local' or 's3'."""
    name = (os.environ.get("STORAGE") or "local").strip().lower()
    if name not in ("local", "s3"):
        raise StorageError(f"STORAGE must be 'local' or 's3', not {name!r}.")
    return name


def bucket_name() -> Optional[str]:
    return os.environ.get("S3_BUCKET") or None


def is_s3(locator: str) -> bool:
    return bool(locator) and locator.startswith(S3_SCHEME)


def key_for(local_path: str, local_root: str, prefix: str) -> str:
    """
    The key to hand to save() for a file whose local home is local_path.

    Local storage keeps the real path, so folders are exactly where they have
    always been. S3 gets prefix/<path relative to local_root>, which keeps the
    per-researcher layout (uploads/<researcher_id>/<upload_id>_<name>).
    """
    if backend_name() == "local":
        return local_path
    rel = os.path.relpath(os.path.abspath(local_path), os.path.abspath(local_root))
    return f"{prefix}/{rel.replace(os.sep, '/')}"


# -------------------------------------------------------------------- local
def _local_save(path: str, data: bytes) -> str:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    # Temp name then rename, so a crash never leaves a truncated file.
    tmp = path + ".part"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, path)
    return path


def _local_load(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()


# ----------------------------------------------------------------------- s3
_client = None


def _reset_client() -> None:
    """Forget the cached client (tests, or after new credentials are exported)."""
    global _client
    _client = None


def _s3():
    global _client
    if _client is None:
        try:
            import boto3
            from botocore.config import Config
        except ImportError as e:
            raise StorageError("boto3 is not installed. Set STORAGE=local to continue.") from e
        # Short timeouts: an unreachable endpoint should fail in seconds,
        # not hang a request. Credentials are read from the environment by
        # boto3 itself; they are not passed through this code.
        _client = boto3.client(
            "s3",
            region_name=os.environ.get("AWS_REGION") or None,
            config=Config(connect_timeout=5, read_timeout=15, retries={"max_attempts": 2}),
        )
    return _client


def _split(locator: str):
    bucket, _, key = locator[len(S3_SCHEME):].partition("/")
    if not bucket or not key:
        raise StorageError(f"Malformed storage locator: {locator!r}")
    return bucket, key


def _fail(op: str, exc: Exception) -> "StorageError":
    """
    Log what went wrong without leaking anything, and return the readable
    error. Only the exception type and the AWS error code are logged: the
    message text of a botocore error can carry request details.
    """
    code = ""
    try:
        code = exc.response.get("Error", {}).get("Code", "")     # type: ignore[attr-defined]
    except Exception:
        pass
    logger.warning("S3 %s failed: %s %s", op, type(exc).__name__, code)
    return StorageError()


def _is_missing(exc: Exception) -> bool:
    try:
        return exc.response.get("Error", {}).get("Code", "") in (   # type: ignore[attr-defined]
            "NoSuchKey", "404", "NotFound")
    except Exception:
        return False


def _s3_save(key: str, data: bytes, bucket: Optional[str] = None) -> str:
    bucket = bucket or bucket_name()
    if not bucket:
        raise StorageError("S3_BUCKET is not set. Set STORAGE=local to continue.")
    try:
        _s3().put_object(Bucket=bucket, Key=key, Body=data)
    except StorageError:
        raise
    except Exception as e:
        raise _fail("put", e) from None
    return f"{S3_SCHEME}{bucket}/{key}"


def _s3_load(locator: str) -> bytes:
    bucket, key = _split(locator)
    try:
        return _s3().get_object(Bucket=bucket, Key=key)["Body"].read()
    except StorageError:
        raise
    except Exception as e:
        if _is_missing(e):
            raise FileNotFoundError(f"No such object: {locator}") from None
        raise _fail("get", e) from None


def _s3_exists(locator: str) -> bool:
    bucket, key = _split(locator)
    try:
        _s3().head_object(Bucket=bucket, Key=key)
        return True
    except StorageError:
        raise
    except Exception as e:
        if _is_missing(e):
            return False
        raise _fail("head", e) from None


def _s3_delete(locator: str) -> None:
    bucket, key = _split(locator)
    try:
        _s3().delete_object(Bucket=bucket, Key=key)
    except StorageError:
        raise
    except Exception as e:
        raise _fail("delete", e) from None


# ---------------------------------------------------------------- interface
def save(key: str, data: bytes) -> str:
    """Store data under key on the configured backend; returns its locator."""
    if backend_name() == "s3":
        return _s3_save(key, data)
    return _local_save(key, data)


def save_at(locator: str, data: bytes) -> str:
    """Rewrite a known location: dispatches on the locator, like load()."""
    if is_s3(locator):
        bucket, key = _split(locator)
        return _s3_save(key, data, bucket)
    return _local_save(locator, data)


def load(locator: str) -> bytes:
    return _s3_load(locator) if is_s3(locator) else _local_load(locator)


def exists(locator: str) -> bool:
    return _s3_exists(locator) if is_s3(locator) else os.path.exists(locator)


def delete(locator: str) -> None:
    """Remove an object. A missing local file is not an error."""
    if is_s3(locator):
        _s3_delete(locator)
        return
    try:
        os.remove(locator)
    except FileNotFoundError:
        pass


def reachable() -> bool:
    """Can the configured backend be used right now? Never raises."""
    if backend_name() == "local":
        return True
    bucket = bucket_name()
    if not bucket:
        return False
    try:
        _s3().head_bucket(Bucket=bucket)
        return True
    except Exception as e:
        _fail("head_bucket", e)
        return False
