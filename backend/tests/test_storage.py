"""
Object storage adapter.

Nothing here needs AWS. S3 behaviour is tested against a stand-in client, and
the one test that talks to a real bucket skips unless credentials and a bucket
are present in the environment.
"""
import os
import types

import pytest

from app import storage


class FakeS3:
    """Just enough of the boto3 S3 client."""

    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body):
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise _client_error("NoSuchKey")
        return {"Body": types.SimpleNamespace(read=lambda: self.objects[(Bucket, Key)])}

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.objects:
            raise _client_error("404")
        return {}

    def delete_object(self, Bucket, Key):
        self.objects.pop((Bucket, Key), None)

    def head_bucket(self, Bucket):
        return {}


class ExpiredS3(FakeS3):
    def put_object(self, **kw):
        raise _client_error("ExpiredToken", "FAKE-KEY-ID token=FAKE-TOKEN")

    get_object = head_object = delete_object = head_bucket = put_object


def _client_error(code, message="boom"):
    from botocore.exceptions import ClientError
    return ClientError({"Error": {"Code": code, "Message": message}}, "Op")


@pytest.fixture
def fake_s3(monkeypatch):
    fake = FakeS3()
    monkeypatch.setattr(storage, "_client", fake)
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    yield fake
    storage._reset_client()


# ------------------------------------------------------------------ local
def test_local_round_trip(tmp_path, monkeypatch):
    monkeypatch.delenv("STORAGE", raising=False)
    path = str(tmp_path / "sub" / "a.json")
    assert storage.save(path, b"hello") == path
    assert storage.exists(path)
    assert storage.load(path) == b"hello"
    assert not os.path.exists(path + ".part")
    storage.delete(path)
    assert not storage.exists(path)
    storage.delete(path)                     # deleting twice is not an error


def test_local_is_the_default(monkeypatch):
    monkeypatch.delenv("STORAGE", raising=False)
    assert storage.backend_name() == "local"
    monkeypatch.setenv("STORAGE", "")
    assert storage.backend_name() == "local"


def test_invalid_storage_value_is_a_readable_error(monkeypatch):
    monkeypatch.setenv("STORAGE", "gcs")
    with pytest.raises(storage.StorageError, match="STORAGE must be"):
        storage.backend_name()


# ---------------------------------------------------------------- routing
def test_s3_locator_routes_to_s3_even_when_storage_is_local(fake_s3, monkeypatch):
    monkeypatch.setenv("STORAGE", "local")
    fake_s3.objects[("test-bucket", "results/run_1.json")] = b"{}"
    loc = "s3://test-bucket/results/run_1.json"
    assert storage.exists(loc)
    assert storage.load(loc) == b"{}"
    storage.delete(loc)
    assert not storage.exists(loc)


def test_filesystem_path_routes_to_disk_even_when_storage_is_s3(fake_s3, tmp_path, monkeypatch):
    legacy = tmp_path / "old.json"
    legacy.write_bytes(b"legacy")
    monkeypatch.setenv("STORAGE", "s3")
    assert storage.exists(str(legacy))
    assert storage.load(str(legacy)) == b"legacy"
    assert fake_s3.objects == {}             # S3 was never consulted
    storage.delete(str(legacy))
    assert not legacy.exists()


def test_s3_save_returns_locator_and_round_trips(fake_s3, monkeypatch):
    monkeypatch.setenv("STORAGE", "s3")
    loc = storage.save("results/run_9.json", b"data")
    assert loc == "s3://test-bucket/results/run_9.json"
    assert storage.load(loc) == b"data"


def test_missing_s3_object_is_file_not_found(fake_s3):
    with pytest.raises(FileNotFoundError):
        storage.load("s3://test-bucket/nope.json")


def test_key_for_keeps_paths_locally_and_prefixes_on_s3(tmp_path, monkeypatch):
    p = str(tmp_path / "uploads" / "7" / "abc_f.maf")
    monkeypatch.setenv("STORAGE", "local")
    assert storage.key_for(p, str(tmp_path / "uploads"), "uploads") == p
    monkeypatch.setenv("STORAGE", "s3")
    assert storage.key_for(p, str(tmp_path / "uploads"), "uploads") == "uploads/7/abc_f.maf"


# --------------------------------------------------------------- failures
def test_s3_failure_is_a_readable_message_without_secrets(monkeypatch):
    monkeypatch.setattr(storage, "_client", ExpiredS3())
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    monkeypatch.setenv("STORAGE", "s3")
    try:
        with pytest.raises(storage.StorageError) as exc:
            storage.save("results/x.json", b"1")
        msg = str(exc.value)
        assert msg == storage.UNAVAILABLE
        assert "Set STORAGE=local" in msg
        assert "FAKE-" not in msg
        assert exc.value.__cause__ is None   # no chained AWS error to leak
        with pytest.raises(storage.StorageError):
            storage.load("s3://test-bucket/x")
    finally:
        storage._reset_client()


def test_storage_error_reaches_the_client_as_a_503_with_the_message():
    from fastapi.testclient import TestClient
    from app.main import app

    def boom():
        raise storage.StorageError()
    app.add_api_route("/api/_test_storage_boom", boom)
    try:
        r = TestClient(app).get("/api/_test_storage_boom")
    finally:
        app.router.routes.pop()
    assert r.status_code == 503
    assert r.json() == {"detail": storage.UNAVAILABLE}
    assert "Traceback" not in r.text


# ------------------------------------------------------- result documents
def test_result_documents_round_trip_through_s3(fake_s3, tmp_path, monkeypatch):
    from app import records
    monkeypatch.setattr(records, "RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setenv("STORAGE", "s3")
    loc = records.write_result(5, {"a": 1})
    assert loc == "s3://test-bucket/results/run_5.json"
    run = types.SimpleNamespace(run_id=5, result_path=loc)
    assert records.load_result(run) == {"a": 1}
    records.remove_result_file(loc)
    assert records.load_result(run) is None
    assert not (tmp_path / "results").exists()      # nothing leaked to disk


def test_remove_result_file_refuses_foreign_s3_objects(fake_s3):
    from app import records
    fake_s3.objects[("other-bucket", "results/run_1.json")] = b"{}"
    fake_s3.objects[("test-bucket", "uploads/1/x.maf")] = b"m"
    records.remove_result_file("s3://other-bucket/results/run_1.json")
    records.remove_result_file("s3://test-bucket/uploads/1/x.maf")
    assert len(fake_s3.objects) == 2


def test_s3_upload_is_fetched_to_a_local_copy(fake_s3, tmp_path, monkeypatch):
    from app import upload
    monkeypatch.setattr(upload, "UPLOAD_DIR", str(tmp_path / "uploads"))
    fake_s3.objects[("test-bucket", "uploads/3/abcdef012345_f.maf")] = b"maf"
    path = upload.local_copy("s3://test-bucket/uploads/3/abcdef012345_f.maf")
    assert open(path, "rb").read() == b"maf"
    assert upload.get_upload_path("abcdef012345") == path
    assert upload.upload_id_for("s3://test-bucket/uploads/3/abcdef012345_f.maf") == "abcdef012345"


# --------------------------------------------------------------- health
def test_health_storage_has_no_secrets(monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app
    client = TestClient(app)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "FAKE-KEY-ID-FOR-TEST")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fakesecretvalue123")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "faketokenvalue456")
    r = client.get("/api/health/storage")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"database", "storage", "serving_frontend", "instance"}
    assert body["storage"]["backend"] == "local"
    assert body["instance"] == "local"
    text = r.text
    for secret in ("FAKE-KEY-ID-FOR-TEST", "fakesecretvalue123", "faketokenvalue456",
                   os.environ.get("MYSQL_PASSWORD") or "\0never"):
        assert secret not in text


# ------------------------------------------------------------ real bucket
@pytest.mark.skipif(
    not (os.environ.get("S3_BUCKET") and os.environ.get("AWS_ACCESS_KEY_ID")
         and os.environ.get("AWS_SESSION_TOKEN")),
    reason="no AWS credentials / S3_BUCKET in the environment")
def test_real_bucket_round_trip(monkeypatch):
    monkeypatch.setenv("STORAGE", "s3")
    storage._reset_client()
    loc = storage.save("tests/cellspark_roundtrip.txt", b"ok")
    try:
        assert storage.load(loc) == b"ok"
    finally:
        storage.delete(loc)


# ------------------------------------------------------- upload -> run (S3)
def test_upload_and_run_through_s3(client, db, fake_s3, tmp_path, monkeypatch):
    from app import main, records, upload
    from app.models import MutationFile, PipelineRun
    from tests.test_records import ALLELES, do_upload, me_id, sign_up

    monkeypatch.setattr(records, "RESULTS_DIR", str(tmp_path / "results"))
    monkeypatch.setattr(upload, "UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("STORAGE", "s3")

    seen = {}

    def fake_run(**kw):
        seen["path"] = upload.get_upload_path(kw["upload_id"])   # must resolve locally
        return {"targets": [], "mrna": None, "timings": {}}
    monkeypatch.setattr(main, "run_pipeline", fake_run)

    sign_up(client)
    rid = me_id(client)
    first = do_upload(client)
    assert first.status_code == 200, first.text
    again = do_upload(client, name="renamed.maf")
    assert again.json()["reused"] is True

    row = db.get(MutationFile, first.json()["file_id"])
    assert row.stored_path.startswith(f"s3://test-bucket/uploads/{rid}/")
    assert (("test-bucket", f"uploads/{rid}/" + row.stored_path.rsplit("/", 1)[1])) in fake_s3.objects
    assert not (tmp_path / "uploads" / str(rid)).exists()        # nothing written to disk

    r = client.post("/api/pipeline/run",
                    json={"alleles": ALLELES, "upload_id": str(row.file_id)})
    assert r.status_code == 200, r.text
    assert open(seen["path"], "rb").read() == fake_s3.objects[
        ("test-bucket", row.stored_path.split("/", 3)[3])]

    run = db.get(PipelineRun, r.json()["run_id"])
    assert run.result_path.startswith("s3://test-bucket/results/run_")
    assert client.get(f"/api/runs/{run.run_id}").json()["result_available"] is True

    assert client.delete(f"/api/runs/{run.run_id}").status_code == 200
    assert ("test-bucket", f"results/run_{run.run_id}.json") not in fake_s3.objects
