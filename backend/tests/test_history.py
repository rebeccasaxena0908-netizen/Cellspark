"""
Phase 3: the history dashboard's API, and the permanent upload store.

Runs are seeded straight through records.start_run / complete_run where the
test is about reading history back — twenty pipeline requests would test
nothing extra. Runs that need a real request (copilot, delete) go through the
route with the fake pipeline from test_records.
"""
import json
import os

import pytest
from sqlalchemy import event, func, select, text, update

from app import records, upload
from app.models import (
    ChatMessage,
    CrossCheckLookup,
    MessageCitation,
    MutationFile,
    PipelineRun,
    PredictedTarget,
    RunAllele,
)

# Shared fakes and helpers from the Phase 2 tests. isolated_dirs is autouse:
# importing it here makes it apply to this module too.
from test_records import (  # noqa: F401
    ALLELES,
    act_as,
    count,
    do_upload,
    fake_copilot,
    fake_pipeline,
    fake_result,
    isolated_dirs,
    me_id,
    run_demo,
    sign_up,
)


# --------------------------------------------------------------- helpers
def seed_runs(db, researcher_id, n, file_id=None):
    """n completed runs, returned oldest first."""
    if file_id is None:
        f, _ = records.add_file(db, researcher_id, "seed.maf", "/nonexistent/seed.maf",
                                os.urandom(32).hex(), 10, 1)
        file_id = f.file_id
    ids = []
    for _ in range(n):
        run = records.start_run(db, researcher_id, file_id, "kmp", ALLELES)
        result = fake_result(ALLELES)
        result["run_id"] = run.run_id
        path = records.write_result(run.run_id, result)
        records.complete_run(db, run, result, path, duration_ms=1234)
        ids.append(run.run_id)
    db.flush()
    return ids


class QueryCounter:
    """Counts SELECTs sent to MySQL while active."""

    def __init__(self, engine):
        self.engine = engine
        self.selects = []

    def _hook(self, conn, cursor, statement, params, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            self.selects.append(statement)

    def __enter__(self):
        event.listen(self.engine, "before_cursor_execute", self._hook)
        return self

    def __exit__(self, *exc):
        event.remove(self.engine, "before_cursor_execute", self._hook)


# --------------------------------------------------------------- /api/runs
def test_list_is_own_runs_newest_first_and_paginated(client, db):
    sign_up(client)
    other = me_id(client)
    seed_runs(db, other, 2)

    sign_up(client)
    rid = me_id(client)
    ids = seed_runs(db, rid, 5)

    # Make started_at disagree with insertion order, so the test proves the
    # sort is on started_at and not merely on run_id.
    db.execute(update(PipelineRun).where(PipelineRun.run_id == ids[0])
               .values(started_at=func.timestampadd(text("HOUR"), 1, func.now())))
    db.flush()
    expected = [ids[0]] + list(reversed(ids[1:]))

    body = client.get("/api/runs").json()
    assert body["total"] == 5
    assert [r["run_id"] for r in body["runs"]] == expected

    page = client.get("/api/runs", params={"limit": 2, "offset": 1}).json()
    assert [r["run_id"] for r in page["runs"]] == expected[1:3]
    assert page["total"] == 5 and page["limit"] == 2 and page["offset"] == 1

    row = body["runs"][0]
    assert row["file_name"] == "seed.maf"
    assert row["file_available"] is False
    assert row["status"] == "completed"
    assert row["targets_returned"] == 3
    assert row["best_ic50_nm"] == 10.0
    assert row["cai_after"] == 0.912
    assert row["duration_ms"] == 1234
    assert sorted(row["alleles"]) == sorted(ALLELES)
    assert row["top_gene"] == "TP53" and row["top_peptide"] == "KLMVWSAWA"


def test_new_researcher_gets_an_empty_list(client):
    sign_up(client)
    r = client.get("/api/runs")
    assert r.status_code == 200
    assert r.json() == {"total": 0, "limit": 20, "offset": 0, "runs": []}


def test_limit_is_bounded(client):
    sign_up(client)
    assert client.get("/api/runs", params={"limit": 0}).status_code == 422
    assert client.get("/api/runs", params={"limit": 101}).status_code == 422
    assert client.get("/api/runs", params={"offset": -1}).status_code == 422


@pytest.mark.parametrize("n", [1, 20])
def test_list_query_count_does_not_grow(client, db, engine, n):
    sign_up(client)
    seed_runs(db, me_id(client), n)

    with QueryCounter(engine) as qc:
        body = client.get("/api/runs", params={"limit": 20}).json()
    assert len(body["runs"]) == n

    # 1 session lookup + 1 page + 1 total, however many runs
    print(f"\n/api/runs with {n} run(s): {len(qc.selects)} SELECTs")
    assert len(qc.selects) == 3, qc.selects


# --------------------------------------------------------------- /api/runs/{id}
def test_detail_returns_full_result(client, db):
    sign_up(client)
    run_id = seed_runs(db, me_id(client), 1)[0]

    body = client.get(f"/api/runs/{run_id}").json()
    assert body["result_available"] is True
    assert body["result"]["run_id"] == run_id
    assert len(body["result"]["tier2"]["targets"]) == 3
    assert body["file_name"] == "seed.maf"


def test_missing_result_file_still_returns_targets(client, db):
    sign_up(client)
    run_id = seed_runs(db, me_id(client), 1)[0]
    os.remove(db.get(PipelineRun, run_id).result_path)

    r = client.get(f"/api/runs/{run_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["result_available"] is False
    assert body["result"] is None
    assert [t["rank_position"] for t in body["targets"]] == [1, 2, 3]
    assert body["targets"][0]["wildtype"] == "KLMVWSAAA"
    assert body["targets_returned"] == 3


# --------------------------------------------------------------- messages
def test_messages_in_order_with_citations_on_answers(client, fake_pipeline, fake_copilot):
    sign_up(client)
    run_id = run_demo(client)["run_id"]
    other_run = run_demo(client)["run_id"]
    client.post("/api/copilot/ask", json={"run_id": run_id, "question": "One?"})
    client.post("/api/copilot/ask", json={"run_id": other_run, "question": "Elsewhere?"})
    client.post("/api/copilot/ask", json={"run_id": run_id, "question": "Two?"})

    msgs = client.get(f"/api/runs/{run_id}/messages").json()["messages"]
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "One?"), ("assistant", "Answer to: One?"),
        ("user", "Two?"), ("assistant", "Answer to: Two?"),
    ]
    assert msgs[0]["citations"] == []
    assert msgs[1]["provider"] == "test-model-1"
    assert [c["pmid"] for c in msgs[1]["citations"]] == ["111", "222"]
    assert msgs[1]["citations"][0]["year"] == 2021


def test_reopened_citation_snippet_matches_corpus(client, db, fake_pipeline, monkeypatch):
    """A real PMID gets its snippet rebuilt the way the copilot first trimmed it."""
    from app.tier4.copilot import _snippet
    from app.tier4.retriever import CORPUS_PATH
    with open(CORPUS_PATH, encoding="utf-8") as fh:
        doc = json.load(fh)[0]
    monkeypatch.setattr("app.main.copilot_answer", lambda q, r, history=None: {
        "answer": "a", "provider": "p", "passages": [],
        "sources": [{"pmid": doc["pmid"], "title": doc["title"], "journal": "",
                     "year": 2020, "similarity": 0.5}],
    })
    sign_up(client)
    run_id = run_demo(client)["run_id"]
    client.post("/api/copilot/ask", json={"run_id": run_id, "question": "q"})

    cite = client.get(f"/api/runs/{run_id}/messages").json()["messages"][1]["citations"][0]
    assert cite["snippet"] == _snippet(f"{doc['title']}\n\n{doc['abstract']}", doc["title"])
    assert cite["snippet"]


# --------------------------------------------------------------- ownership
def test_other_researchers_run_is_404_everywhere(client, db, fake_pipeline):
    sign_up(client)
    run_id = run_demo(client)["run_id"]

    sign_up(client)
    assert client.get(f"/api/runs/{run_id}").status_code == 404
    assert client.get(f"/api/runs/{run_id}/messages").status_code == 404
    assert client.delete(f"/api/runs/{run_id}").status_code == 404
    assert client.get("/api/runs").json()["runs"] == []

    # B's DELETE did nothing
    assert db.get(PipelineRun, run_id) is not None


# --------------------------------------------------------------- delete
def test_delete_cascades_and_keeps_the_file(client, db, fake_pipeline, fake_copilot, monkeypatch):
    monkeypatch.setattr("app.main.copilot_cross_check", lambda g, c, r: {
        "gene": g, "change": c, "coverage": "thin", "summary": "s", "provider": "p",
        "passages": [], "caveat": ""})
    sign_up(client)
    fid = do_upload(client).json()["file_id"]
    run = lambda: client.post("/api/pipeline/run",
                              json={"alleles": ALLELES, "upload_id": str(fid)}).json()["run_id"]
    doomed, kept = run(), run()
    for rid in (doomed, kept):
        client.post("/api/copilot/ask", json={"run_id": rid, "question": "q"})
        client.post("/api/copilot/cross-check", json={"run_id": rid, "gene": "KRAS"})

    result_path = db.get(PipelineRun, doomed).result_path
    msg_ids = db.execute(select(ChatMessage.message_id)
                         .where(ChatMessage.run_id == doomed)).scalars().all()
    assert count(db, PredictedTarget, run_id=doomed) == 3
    assert msg_ids and os.path.exists(result_path)

    r = client.delete(f"/api/runs/{doomed}")
    assert r.status_code == 200
    db.expire_all()

    assert db.get(PipelineRun, doomed) is None
    for model in (RunAllele, PredictedTarget, ChatMessage, CrossCheckLookup):
        assert count(db, model, run_id=doomed) == 0, model.__name__
    assert db.execute(select(func.count()).select_from(MessageCitation)
                      .where(MessageCitation.message_id.in_(msg_ids))).scalar_one() == 0
    assert not os.path.exists(result_path)

    # the upload, and the other run on it, are untouched
    assert db.get(MutationFile, fid) is not None
    assert count(db, PredictedTarget, run_id=kept) == 3
    assert count(db, ChatMessage, run_id=kept) == 2
    assert client.get(f"/api/runs/{doomed}").status_code == 404


def test_result_file_outside_results_dir_is_never_deleted(tmp_path):
    outside = tmp_path / "elsewhere.json"
    outside.write_text("{}")
    records.remove_result_file(str(outside))
    assert outside.exists()


# --------------------------------------------------------------- stats
def test_stats(client, db, fake_pipeline, fake_copilot):
    sign_up(client)
    assert client.get("/api/me/stats").json() == {
        "total_runs": 0, "distinct_files": 0, "total_targets": 0,
        "best_ic50_nm": None, "copilot_messages": 0,
    }
    run_id = run_demo(client)["run_id"]
    run_demo(client)
    client.post("/api/copilot/ask", json={"run_id": run_id, "question": "q"})

    assert client.get("/api/me/stats").json() == {
        "total_runs": 2, "distinct_files": 1, "total_targets": 6,
        "best_ic50_nm": 10.0, "copilot_messages": 2,
    }


# --------------------------------------------------------------- storage
def test_upload_lands_in_the_researchers_folder(client, db):
    sign_up(client)
    rid = me_id(client)
    fid = do_upload(client).json()["file_id"]
    path = db.get(MutationFile, fid).stored_path
    assert os.path.dirname(path) == os.path.join(upload.UPLOAD_DIR, str(rid))
    assert upload.get_upload_path(upload.upload_id_for(path)) == path


def test_upload_id_must_look_like_one():
    with pytest.raises(FileNotFoundError):
        upload.get_upload_path("*")


def test_demo_file_has_a_permanent_path_and_stale_rows_are_repointed(client, db, fake_pipeline):
    sign_up(client)
    rid = me_id(client)
    run_demo(client)
    row = db.execute(select(MutationFile).where(MutationFile.researcher_id == rid)).scalar_one()
    assert row.stored_path == records.demo_path()
    assert os.path.exists(row.stored_path)

    row.stored_path = "/var/folders/gone/cellspark_demo_x/mutations.maf"   # pre-Phase-3 row
    db.flush()
    run_demo(client)
    db.refresh(row)
    assert row.stored_path == records.demo_path()
    assert count(db, MutationFile, researcher_id=rid) == 1
