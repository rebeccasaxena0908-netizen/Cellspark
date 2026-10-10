"""
Tier 4 copilot tests.

The point of these is the fallback. Generation is the nice path, but the
copilot's contract is that it always returns a usable, correctly-numbered
answer — with no API key, with a dead provider, with an LLM layer that
misbehaves and raises when it promised not to. Each of those is a test here.

No API key appears in this file, and nothing here makes a network call: every
test either switches the provider off or monkeypatches generation.
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.tier4 import context, copilot, llm


# --------------------------------------------------------------- fixtures
def make_result(n_candidates: int = 12, n_targets: int = 10) -> dict:
    """
    A pipeline result shaped like the real one.

    Mirrors the keys produced by pipeline.run_pipeline / tier2.predict_binding
    / tier3.design_mrna, because the context builder reads those exact names.
    """
    targets = []
    for i in range(n_targets):
        ic50 = 12.5 * (i + 1)
        targets.append({
            "rank": i + 1,
            "peptide": f"SLYNTVAT{'ACDEFGHIK'[i % 9]}",
            "wildtype": f"SLYNTVATL",
            "gene": ["TP53", "KRAS", "BRAF"][i % 3],
            "change": f"p.R{100 + i}H",
            "allele": "HLA-A*02:01",
            "ic50": round(ic50, 1),
            "wtIc50": round(ic50 * 8, 1),
            "agretopicity": 8.0,
            "mutPos": i % 9,
            "length": 9,
            "band": "Strong binder" if ic50 < 50 else "Weak binder",
            "tone": "ok",
        })

    return {
        "file_name": "sample_patient.maf",
        "alleles": ["HLA-A*02:01"],
        "source": "demo",
        "tier1": {
            "implemented": True,
            "algorithm": "kmp",
            "source": "demo",
            "screening_stage": "pre_ranking",
            "proteome": {
                "proteins": 20431,
                "residues": 11400000,
                "reference": "UniProt Swiss-Prot human",
            },
            "stats": {
                "mutations": 30,
                "candidates": n_candidates,
                "tumour_specific": max(0, n_candidates - 4),
                "rejected_self": 4,
                "unmapped_genes": 2,
                "position_mismatch": 1,
                "peptides_per_mutation": 38.0,
            },
            "warning": "Of 30 mutations: 2 gene(s) not found in the reference proteome.",
            # The two fields the context builder must NOT copy wholesale.
            "peptides": [
                {"peptide": f"PEPTIDE{i:04d}", "gene": "TP53", "wildtype_peptide": "X"}
                for i in range(n_candidates)
            ],
        },
        "tier2": {
            "implemented": True,
            "predictor": "MHCflurry 2.2 (PyTorch)",
            "alleles": ["HLA-A*02:01"],
            "stats": {
                "scored": n_candidates,
                "strong_binders": 3,
                "weak_binders": 5,
                "below_threshold": 2,
                "best_ic50": 12.5,
            },
            "targets": targets,
        },
        "tier3": {
            "implemented": True,
            "target": {"peptide": "SLYNTVATA", "gene": "TP53", "change": "p.R100H"},
            "full_construct": "AUG" + "GCC" * 500 + "A" * 120,
            "protein_unchanged": True,
            "before": {"length": 1500, "cai": 0.72, "uracil": 24.1, "gc": 48.0},
            "after": {"length": 1500, "cai": 1.0, "uracil": 11.3, "gc": 61.2},
        },
    }


@pytest.fixture
def llm_off(monkeypatch):
    """Provider switched off — the documented no-key configuration."""
    monkeypatch.setenv("CELLSPARK_LLM", "off")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    return None


@pytest.fixture
def fake_retrieval(monkeypatch):
    """
    Stub the retriever so tests don't depend on a built Chroma index.

    Returns the retriever's real shape, including "text" as
    "title\\n\\nabstract", which is what _snippet has to strip.
    """
    hits = [
        {
            "pmid": "16111635",
            "title": "Suppression of RNA recognition by Toll-like receptors",
            "journal": "Immunity",
            "year": "2005",
            "text": (
                "Suppression of RNA recognition by Toll-like receptors\n\n"
                + "Nucleoside modifications suppress the immunostimulatory "
                "potential of single-stranded RNA. " * 12
            ),
            "similarity": 0.71,
            "url": "https://pubmed.ncbi.nlm.nih.gov/16111635/",
        },
        {
            "pmid": "31602019",
            "title": "MHCflurry 2.0: improved pan-allele prediction",
            "journal": "Cell Systems",
            "year": "2020",
            "text": (
                "MHCflurry 2.0: improved pan-allele prediction\n\n"
                "Antigen processing predictions improve MHC ligand prediction."
            ),
            "similarity": 0.64,
            "url": "https://pubmed.ncbi.nlm.nih.gov/31602019/",
        },
    ]
    monkeypatch.setattr(copilot, "retrieve", lambda query, k=5: hits[:k])
    return hits


# --------------------------------------------------------------- tests
def test_answer_falls_back_to_templates_when_llm_off(llm_off, fake_retrieval):
    """With CELLSPARK_LLM=off: a template answer, no exception, provider says so."""
    out = copilot.answer("What does the IC50 mean here?", make_result())

    assert out["provider"] == "templates"
    assert out["answer"].strip()
    # The template path quotes the run's real numbers rather than generating.
    assert "12.5" in out["answer"]
    assert out["grounded_in"]["pipeline_output"] is True


def test_run_context_stays_under_cap_with_300_candidates():
    """A result with 300 candidates must not blow the context budget."""
    text = context.build_run_context(make_result(n_candidates=300))

    assert len(text) <= context.MAX_CHARS

    # Under the cap because the unbounded fields were excluded, not because
    # the whole block got truncated away.
    assert "PEPTIDE0200" not in text
    assert "GCCGCCGCCGCC" not in text or len(text) < context.MAX_CHARS
    assert "TIER 3" in text


def test_run_context_excludes_full_construct_but_keeps_preview():
    result = make_result()
    text = context.build_run_context(result)
    construct = result["tier3"]["full_construct"]

    assert construct[: context.CONSTRUCT_PREVIEW_NT] in text
    assert construct not in text
    assert str(len(construct)) in text


def test_run_context_truncates_with_a_marker_when_oversized(monkeypatch):
    """The cap is enforced by truncation, and the truncation is announced."""
    monkeypatch.setattr(context, "MAX_CHARS", 400)
    text = context.build_run_context(make_result())

    assert len(text) <= 400
    assert "TRUNCATED" in text


def test_answer_returns_passages_when_retriever_has_hits(llm_off, fake_retrieval):
    """passages is populated whenever retrieval returns anything."""
    out = copilot.answer("Why lower the uracil content?", make_result())

    assert len(out["passages"]) == len(fake_retrieval)

    p = out["passages"][0]
    assert p["pmid"] == "16111635"
    assert p["title"] and p["journal"] and p["year"]
    assert p["snippet"]
    assert len(p["snippet"]) <= copilot.SNIPPET_CHARS + 3   # +3 for the ellipsis
    # The title is carried as its own field, not repeated inside the snippet.
    assert not p["snippet"].startswith(p["title"])
    assert isinstance(p["score"], float)

    # sources keeps its original shape — the frontend reads it.
    assert out["sources"][0]["url"].endswith("/16111635/")
    assert out["grounded_in"]["literature"] == len(fake_retrieval)


def test_fallback_holds_when_llm_generate_raises(monkeypatch, fake_retrieval):
    """
    llm.generate promises never to raise. If it breaks that promise anyway,
    the copilot must still answer rather than 500.
    """
    def boom(*args, **kwargs):
        raise RuntimeError("provider exploded")

    monkeypatch.setattr(copilot.llm, "generate", boom)

    out = copilot.answer("How many mutations were processed?", make_result())

    assert out["provider"] == "templates"
    assert out["answer"].strip()
    assert "30" in out["answer"]          # the run's real mutation count
    assert out["passages"]                 # retrieval still contributed


def test_answer_uses_generated_text_when_generation_succeeds(monkeypatch, fake_retrieval):
    """The happy path: generated text is returned and provider names the model."""
    captured = {}

    def fake_generate(system_prompt, user_prompt):
        captured["system"] = system_prompt
        captured["user"] = user_prompt
        return "Generated answer citing (PMID 16111635)."

    monkeypatch.setattr(copilot.llm, "generate", fake_generate)
    monkeypatch.setattr(copilot.llm, "model_name", lambda: "test-model-x")

    out = copilot.answer("Why lower the uracil content?", make_result())

    assert out["answer"] == "Generated answer citing (PMID 16111635)."
    assert out["provider"] == "test-model-x"

    # The retrieved passages actually reach the prompt — the thing that was
    # broken before: retrieval used to have no influence on the answer text.
    assert "16111635" in captured["user"]
    assert "Toll-like receptors" in captured["user"]
    # ...and so do the run's own numbers.
    assert "12.5" in captured["user"]
    assert "RUN CONTEXT" in captured["user"]
    assert "CellSpark" in captured["system"]


def test_history_reaches_the_prompt_and_is_capped(monkeypatch, fake_retrieval):
    """History is optional, shape-tolerant, and limited to the last few turns."""
    captured = {}

    def fake_generate(system_prompt, user_prompt):
        captured["user"] = user_prompt
        return "ok"

    monkeypatch.setattr(copilot.llm, "generate", fake_generate)

    history = [{"role": "user", "content": f"turn {i}"} for i in range(20)]
    copilot.answer("And now?", make_result(), history=history)

    assert "turn 19" in captured["user"]
    assert "turn 0" not in captured["user"]        # dropped by the cap


def test_answer_keeps_working_without_history_argument(llm_off, fake_retrieval):
    """The frontend calls answer(question, result) positionally — don't break it."""
    out = copilot.answer("Give me a summary", make_result())
    assert out["answer"].strip()
    assert "passages" in out and "provider" in out


def test_answer_survives_retrieval_failure(llm_off, monkeypatch):
    """No index built? Still answer, with an empty passages list."""
    def boom(query, k=5):
        raise RuntimeError("chroma not initialised")

    monkeypatch.setattr(copilot, "retrieve", boom)

    out = copilot.answer("What does IC50 mean?", make_result())

    assert out["answer"].strip()
    assert out["passages"] == []
    assert out["sources"] == []
    assert out["provider"] == "templates"


def test_answer_handles_an_empty_result(llm_off, fake_retrieval):
    """A question asked before any run completes must not crash."""
    out = copilot.answer("What did you find?", {})
    assert out["answer"].strip()
    assert out["provider"] == "templates"


# --------------------------------------------- real pipeline result fixture
FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "result_full.json")


def load_fixture():
    """
    A real end-to-end run, MHCflurry scores and all.

    Everything above this point is hand-built, which means it only proves the
    context builder handles the shapes the tests themselves invent. This
    fixture is the genuine article — the state that is actually on screen in a
    demo — so the assertions below are about real target rows, not a mock of
    them. Regenerate with:

        venv/bin/python -c "import json; from app.pipeline import run_pipeline; \\
            json.dump(run_pipeline(alleles=['HLA-A*02:01']), \\
                      open('tests/fixtures/result_full.json','w'))"
    """
    if not os.path.exists(FIXTURE):
        pytest.skip(f"fixture missing: {FIXTURE} (see load_fixture docstring to regenerate)")
    with open(FIXTURE) as fh:
        return json.load(fh)


def test_run_context_includes_target_table_for_real_tier2():
    """
    The headline assertion: with tier2.implemented true, the ranked targets
    reach the prompt.

    2A was only ever verified against a result whose tier2 was the exception
    branch, so the table path had never run against real scores. If the
    builder were reading a key that only exists on the failure branch, this is
    where it would show.
    """
    result = load_fixture()
    assert result["tier2"]["implemented"] is True
    targets = result["tier2"]["targets"]
    assert targets, "fixture has no targets — regenerate it"

    text = context.build_run_context(result)

    # The table itself, and the header that explains what the columns mean.
    assert "TOP 10 TARGETS" in text
    assert "agretopicity" in text

    # Every target's real numbers, not a placeholder.
    for t in targets:
        assert t["peptide"] in text
        assert str(t["ic50"]) in text
        assert str(t["wtIc50"]) in text
        assert str(t["agretopicity"]) in text
        assert t["gene"] in text

    # And it must not claim the tier failed.
    assert "did not run" not in text.split("TIER 3")[0]
    assert str(result["tier2"]["stats"]["scored"]) in text


def test_run_context_bands_real_targets_by_ic50():
    """Bands are recomputed from IC50, so they always agree with the number shown."""
    result = load_fixture()
    text = context.build_run_context(result)

    for t in result["tier2"]["targets"]:
        expected = (
            "strong binder" if t["ic50"] < 50
            else "weak binder" if t["ic50"] < 500
            else "below threshold"
        )
        line = next(l for l in text.splitlines() if l.strip().startswith(f"#{t['rank']} "))
        assert line.endswith(expected), f"rank {t['rank']} banded as {line!r}"


def test_real_fixture_context_stays_under_cap():
    """A real run with 1,140 candidates must still fit the budget."""
    result = load_fixture()
    assert len(result["tier1"]["peptides"]) > 1000
    text = context.build_run_context(result)

    assert len(text) <= context.MAX_CHARS
    # Under the cap because the peptide list was excluded, not truncated away.
    assert "TRUNCATED" not in text
    assert "TIER 3" in text


def test_context_reports_tiers_that_did_not_run():
    """A failed tier is stated as failed — that's an answer in itself."""
    result = make_result()
    result["tier2"] = {"implemented": False, "error": "MHCflurry unavailable"}
    result["tier3"] = {"implemented": False, "note": "No targets available"}

    text = context.build_run_context(result)

    assert "MHCflurry unavailable" in text
    assert "No targets available" in text


# --------------------------------------------------------------- llm layer
def test_llm_generate_returns_none_when_off(monkeypatch):
    monkeypatch.setenv("CELLSPARK_LLM", "off")
    assert llm.generate("sys", "user") is None


def test_llm_generate_returns_none_without_a_key(monkeypatch):
    monkeypatch.setenv("CELLSPARK_LLM", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    assert llm.generate("sys", "user") is None


def test_llm_generate_returns_none_for_unknown_provider(monkeypatch):
    monkeypatch.setenv("CELLSPARK_LLM", "something-else")
    assert llm.generate("sys", "user") is None


def test_llm_model_name_defaults_and_overrides(monkeypatch):
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    assert llm.model_name() == llm.DEFAULT_MODEL
    assert "1.5" not in llm.model_name()        # the retired model is not the default

    monkeypatch.setenv("GEMINI_MODEL", "gemini-test-model")
    assert llm.model_name() == "gemini-test-model"


def test_llm_redacts_the_api_key(monkeypatch):
    """A key must never reach a log line, even via an echoed provider error."""
    monkeypatch.setenv("GEMINI_API_KEY", "SUPERSECRETKEYVALUE123")
    msg = llm._redact("request failed for key=SUPERSECRETKEYVALUE123 at host")

    assert "SUPERSECRETKEYVALUE123" not in msg
    assert "REDACTED" in msg


# ------------------------------------------------------------- cross-check
#
# Coverage facts these tests rely on, measured against data/corpus.json with a
# case-sensitive word-boundary match:
#   KRAS   8 abstracts   -> well_covered
#   BRAF   2 abstracts   -> thin
#   PIK3CA 0 abstracts   -> not_covered  (and it is rank 1 in the fixture)
#   MET    1 abstract    -> thin, but 5 if matched case-insensitively

def test_not_covered_never_calls_the_llm(monkeypatch, fake_retrieval):
    """
    A gene the corpus does not mention must not reach the model.

    This is the whole safety property of the feature. An LLM handed an empty
    retrieval and asked about a famous gene will answer from memory, which is
    precisely the fabrication this is built to avoid — so llm.generate is
    booby-trapped here and the call must still succeed.
    """
    def boom(*a, **k):
        raise AssertionError("llm.generate must not be called for an uncovered gene")

    monkeypatch.setattr(copilot.llm, "generate", boom)
    monkeypatch.setattr(copilot, "retrieve_mentioning", lambda symbol, query, k=6: [])

    out = copilot.cross_check("PIK3CA", "p.V151I", {})

    assert out["coverage"] == "not_covered"
    assert out["passages"] == []
    assert out["summary"].strip()
    assert out["caveat"].strip()


def test_not_covered_wording_makes_no_claim_about_the_gene():
    """
    The wording is the deliverable. It must report on the index, not the gene.

    PIK3CA is the live example: one of the most-mutated genes in cancer, zero
    abstracts in this corpus. Any phrasing that reads as a verdict would be
    flatly wrong here.
    """
    text = copilot._not_covered_summary("PIK3CA", "p.V151I", 618).lower()

    for banned in ("no evidence", "not a known", "is a known", "unlikely to be",
                   "not a validated", "no support", "not supported"):
        assert banned not in text, f"verdict-like phrasing: {banned!r}"

    # And it must say what it IS saying.
    assert "index" in text
    assert "pubmed" in text
    assert "618" in text


def test_coverage_is_classified_in_code_not_by_the_model():
    """Classification is a counting function, reachable without any model."""
    assert copilot._classify_coverage(0) == "not_covered"
    assert copilot._classify_coverage(1) == "thin"
    assert copilot._classify_coverage(2) == "thin"
    assert copilot._classify_coverage(3) == "well_covered"
    assert copilot._classify_coverage(6) == "well_covered"


def test_gene_mention_counting_is_case_sensitive():
    """
    MET is a gene and also an ordinary English word.

    Matching case-insensitively reports coverage that does not exist — in this
    corpus it turns MET's single real abstract into five.
    """
    passages = [
        {"text": "Criteria were not met in this cohort."},
        {"text": "Metabolic reprogramming in tumours."},
        {"text": "MET amplification drives resistance."},
    ]
    assert copilot._gene_mentions("MET", passages) == 1
    assert copilot._gene_mentions("KRAS", passages) == 0


def test_caveat_is_populated_in_every_coverage_state(monkeypatch):
    """Including when coverage is good — a hit is as over-readable as a miss."""
    hits = [{
        "pmid": "123", "title": "KRAS review", "journal": "J", "year": "2020",
        "text": "KRAS is discussed here. " * 10, "similarity": 0.5,
        "url": "https://pubmed.ncbi.nlm.nih.gov/123/",
    }]
    monkeypatch.setattr(copilot.llm, "generate", lambda **k: "summary text")

    for n, expected in [(0, "not_covered"), (2, "thin"), (4, "well_covered")]:
        monkeypatch.setattr(copilot, "retrieve_mentioning",
                            lambda symbol, query, k=6, _n=n: hits * _n)
        out = copilot.cross_check("KRAS", "p.G12D", {})
        assert out["coverage"] == expected
        assert out["caveat"].strip(), f"empty caveat for {expected}"
        assert "not clinical validation" in out["caveat"]
        assert out["gene"] == "KRAS" and out["change"] == "p.G12D"


def test_cross_check_falls_back_when_generation_is_off(monkeypatch):
    """LLM off: still return the passages and the coverage state, not an error."""
    hits = [{
        "pmid": "456", "title": "BRAF in melanoma", "journal": "J", "year": "2021",
        "text": "BRAF V600E is a driver. " * 10, "similarity": 0.6,
        "url": "https://pubmed.ncbi.nlm.nih.gov/456/",
    }] * 2
    monkeypatch.setattr(copilot, "retrieve_mentioning", lambda symbol, query, k=6: hits)
    monkeypatch.setattr(copilot.llm, "generate", lambda **k: None)

    out = copilot.cross_check("BRAF", "p.V600E", {})

    assert out["coverage"] == "thin"
    assert out["provider"] == "templates"
    assert len(out["passages"]) == 2
    assert out["passages"][0]["pmid"] == "456"
    assert "generation is switched off" in out["summary"].lower()
    assert out["caveat"].strip()


def test_cross_check_survives_retrieval_failure(monkeypatch):
    """A dead index reports itself as a CellSpark problem, not a gene finding."""
    def boom(symbol, query, k=6):
        raise RuntimeError("chroma down")

    monkeypatch.setattr(copilot, "retrieve_mentioning", boom)
    out = copilot.cross_check("KRAS", "p.G12D", {})

    assert out["coverage"] == "not_covered"
    assert out["passages"] == []
    assert "not a statement about the gene" in out["summary"].lower()
    assert out["caveat"].strip()


def test_answer_is_unchanged_by_cross_check(llm_off, fake_retrieval):
    """2C is additive — answer() keeps its exact contract."""
    out = copilot.answer("What does IC50 mean here?", make_result())
    assert set(["answer", "sources", "grounded_in", "provider", "passages"]).issubset(out)
    assert out["provider"] == "templates"
    assert out["answer"].strip()


# --- these touch the real corpus, so they skip if it has not been built ---
def corpus_or_skip():
    from app.tier4 import retriever
    info = retriever.corpus_info()
    if not info.get("available"):
        pytest.skip(f"corpus/index unavailable: {info.get('error')}")
    return info


def test_real_corpus_classifies_known_genes(monkeypatch):
    """
    Against the real index: a gene it holds, and one it does not.

    KRAS and PIK3CA were chosen by counting the corpus, not by assumption —
    see the table at the top of this section.
    """
    corpus_or_skip()
    monkeypatch.setattr(copilot.llm, "generate", lambda **k: None)  # no network

    covered = copilot.cross_check("KRAS", "p.G12D", {})
    assert covered["coverage"] == "well_covered"
    assert covered["passages"]
    assert all("KRAS" in p["snippet"] or "KRAS" in p["title"] for p in covered["passages"][:1])

    absent = copilot.cross_check("PIK3CA", "p.V151I", {})
    assert absent["coverage"] == "not_covered"
    assert absent["passages"] == []
    assert absent["provider"] == "retrieval-only"
