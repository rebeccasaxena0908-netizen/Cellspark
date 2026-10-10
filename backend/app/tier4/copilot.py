"""
Tier 4 — Clinical copilot.

Answers questions about a pipeline run, grounded in two sources:
  1. the run's own JSON output (the patient-specific facts)
  2. retrieved PubMed abstracts (the general biomedical context)

WHY GROUNDING MATTERS HERE:
A language model answering a medical question from its parameters alone can
produce fluent, confident, wrong output. RAG changes the flow: retrieve first,
then answer only over what was retrieved, and cite it. The model reasons over
supplied evidence rather than recalling medicine from memory.

WITHOUT AN LLM API KEY this module still works — it composes answers from the
pipeline's own numbers and attaches the retrieved citations. That's a
deliberate design choice: the patient-specific facts (IC50 values, CAI, reject
counts) are the part a clinician most needs to be exactly right, and those
come from the pipeline, not from a model. The LLM adds fluency, not facts.
"""

import logging
import os
import re
from typing import Any, Dict, List, Optional

from . import llm, platform_facts
from .context import build_run_context
from .retriever import retrieve, retrieve_mentioning, corpus_info

logger = logging.getLogger(__name__)


def _facts(result: Dict[str, Any]) -> Dict[str, Any]:
    """Pull the numbers worth quoting out of a pipeline result."""
    t1 = result.get("tier1", {})
    t2 = result.get("tier2", {})
    t3 = result.get("tier3", {})
    targets = t2.get("targets", [])
    top = targets[0] if targets else None

    return {
        "mutations": t1.get("stats", {}).get("mutations"),
        "candidates": t1.get("stats", {}).get("candidates"),
        "rejected_self": t1.get("stats", {}).get("rejected_self"),
        "per_mutation": t1.get("stats", {}).get("peptides_per_mutation"),
        "proteins": t1.get("proteome", {}).get("proteins"),
        "algorithm": t1.get("algorithm"),
        "scored": t2.get("stats", {}).get("scored"),
        "strong": t2.get("stats", {}).get("strong_binders"),
        "weak": t2.get("stats", {}).get("weak_binders"),
        "top": top,
        "cai_before": t3.get("before", {}).get("cai"),
        "cai_after": t3.get("after", {}).get("cai"),
        "u_before": t3.get("before", {}).get("uracil"),
        "u_after": t3.get("after", {}).get("uracil"),
        "protein_unchanged": t3.get("protein_unchanged"),
    }


def _compose(question: str, f: Dict[str, Any]) -> str:
    """
    Build an answer from the run's own numbers.

    Deliberately templated rather than generated: these are the facts that
    must be exactly right, so they come straight from the pipeline output.
    """
    q = question.lower()
    top = f["top"]

    if any(w in q for w in ("ic50", "binding", "affinity", "nm", "score")):
        if not top:
            return "No targets were scored in this run, so there are no binding values to report."
        return (
            f"IC50 estimates binding strength in nanomolar, and it runs opposite to "
            f"intuition: lower means tighter. Under 50 nM is treated as a strong binder "
            f"and under 500 nM as weak but plausible. In this run {f['scored']} peptides "
            f"were scored, of which {f['strong']} came out strong and {f['weak']} weak. "
            f"The leading candidate, {top['peptide']} from {top['gene']} {top['change']}, "
            f"scores {top['ic50']} nM against {top['allele']} — that's {top['band'].lower()}. "
            f"Its healthy counterpart {top['wildtype']} scores {top['wtIc50']} nM, so the "
            f"mutation improves binding roughly {top['agretopicity']}-fold."
        )

    if any(w in q for w in ("codon", "cai", "translation", "ribosome")):
        return (
            f"Codon optimisation replaced rare codons with frequent ones, which reduces "
            f"how often the ribosome stalls waiting for scarce tRNA. CAI moved from "
            f"{f['cai_before']} to {f['cai_after']}, where 1.0 means every codon is the "
            f"most-used option for its amino acid. Crucially only synonymous substitutions "
            f"were made, so the encoded protein is unchanged — the pipeline verifies this "
            f"by back-translating, and it passed"
            f"{'' if f['protein_unchanged'] else ' — except it did not, which is a bug'}. "
            f"Worth noting that a CAI of exactly 1.0 comes from greedy per-codon selection; "
            f"production tools trade some CAI against secondary structure."
        )

    if any(w in q for w in ("uracil", "uridine", "inflam", "immune reaction")):
        return (
            f"Uracil content came down from {f['u_before']}% to {f['u_after']}%. Innate "
            f"immune sensors read uridine-rich single-stranded RNA as a viral signature, so "
            f"lowering it reduces the risk that the construct provokes inflammation against "
            f"itself. Again this used synonymous substitutions only. This is the "
            f"sequence-level half of the problem — manufactured mRNA vaccines also use "
            f"chemical modification such as N1-methylpseudouridine, which is outside what "
            f"this pipeline does."
        )

    if any(w in q for w in ("safe", "risk", "self", "autoimmun", "toleran")):
        return (
            f"Every candidate peptide was checked against a reference proteome of "
            f"{f['proteins']} proteins using {f['algorithm']} exact matching, and "
            f"{f['rejected_self']} were discarded because the same motif occurs in a healthy "
            f"protein — targeting those would risk attacking normal tissue. One real gap: "
            f"exact matching won't catch peptides that are merely similar to self, which "
            f"would need approximate matching to address."
        )

    if any(w in q for w in ("how many", "summary", "overview", "what did")):
        return (
            f"From {f['mutations']} missense mutations the pipeline built {f['candidates']} "
            f"candidate peptides — about {f['per_mutation']} per mutation, because the window "
            f"slides across each mutation site at four different lengths. After tolerance "
            f"screening, {f['scored']} were scored for HLA binding and the top ten kept. "
            f"The best candidate was then compiled into an mRNA sequence."
        )

    # fallback
    if top:
        return (
            f"This run processed {f['mutations']} mutations into {f['candidates']} candidate "
            f"peptides, scored {f['scored']} of them, and selected {top['peptide']} "
            f"({top['gene']} {top['change']}, {top['ic50']} nM) as the leading target. "
            f"These are computational predictions for prioritising laboratory work, not "
            f"clinical conclusions."
        )
    return "I don't have results loaded yet — run an analysis first."


# ---------------------------------------------------------------- generation

SNIPPET_CHARS = 400
HISTORY_TURNS = 6


def _snippet(text: str, title: str = "", limit: int = SNIPPET_CHARS) -> str:
    """
    Trim a retrieved document to a readable snippet, cut at a word boundary.

    The retriever indexes "title\\n\\nabstract" as one document, so the stored
    text repeats the title. We drop that prefix: the title is already carried
    as its own field, and repeating it inside the snippet wastes a chunk of a
    400-character budget that should be spent on the abstract.
    """
    body = (text or "").strip()
    if title and body.startswith(title):
        body = body[len(title):].lstrip("\n ").strip()

    if len(body) <= limit:
        return body

    cut = body[:limit]
    space = cut.rfind(" ")
    if space > limit * 0.6:      # only honour the boundary if it's not way back
        cut = cut[:space]
    return cut.rstrip(" ,;:.") + "..."


def _passages(sources: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The retrieved evidence, in the shape the frontend's citation panel reads."""
    return [{
        "pmid": s.get("pmid", ""),
        "title": s.get("title", ""),
        "journal": s.get("journal", ""),
        "year": str(s.get("year", "")),
        "snippet": _snippet(s.get("text", ""), s.get("title", "")),
        "score": s.get("similarity", 0.0),
    } for s in sources]


def _format_passages(sources: List[Dict[str, Any]]) -> str:
    """
    Render the retrieved abstracts as labelled evidence.

    Each one is tagged with its PMID so the model can cite it, and with its
    similarity score so it can tell a close hit from a marginal one — that is
    what lets it say "no supporting literature" instead of stretching an
    off-topic abstract to fit.
    """
    if not sources:
        return (
            "=== RETRIEVED LITERATURE ===\n\n"
            "Nothing was retrieved for this question. Answer from the run "
            "context alone and say that you have no supporting literature."
        )

    blocks = ["=== RETRIEVED LITERATURE (cite these as (PMID ...); no others) ==="]
    for i, s in enumerate(sources, start=1):
        blocks.append(
            "\n[{i}] PMID {pmid} — {title}\n"
            "    {journal} {year} | similarity {score}\n"
            "    {text}".format(
                i=i,
                pmid=s.get("pmid", "?"),
                title=s.get("title", ""),
                journal=s.get("journal", "") or "PubMed",
                year=s.get("year", ""),
                score=s.get("similarity", 0.0),
                # Full retrieved text here, not the trimmed snippet — the
                # model should reason over the whole abstract. The snippet is
                # for the UI, where space is the constraint.
                text=(s.get("text", "") or "").strip().replace("\n", "\n    "),
            )
        )
    return "\n".join(blocks)


def _format_history(history: Any) -> str:
    """
    Render the last few turns of conversation, if any.

    Shape-tolerant on purpose: the frontend does not send history yet, so this
    accepts the plausible shapes it might send (role/content messages, or
    question/answer pairs) rather than committing the backend to one and
    breaking when the other arrives.
    """
    if not history or not isinstance(history, (list, tuple)):
        return ""

    turns: List[str] = []
    for item in list(history)[-HISTORY_TURNS:]:
        if isinstance(item, dict):
            if item.get("role") is not None:
                is_user = str(item.get("role")).lower() in ("user", "human")
                role = "User" if is_user else "Copilot"
                turns.append(f"{role}: {item.get('content') or item.get('text') or ''}")
            else:
                q = item.get("question") or item.get("q")
                a = item.get("answer") or item.get("a")
                if q:
                    turns.append(f"User: {q}")
                if a:
                    turns.append(f"Copilot: {a}")
        elif isinstance(item, (list, tuple)) and len(item) == 2:
            turns.append(f"User: {item[0]}")
            turns.append(f"Copilot: {item[1]}")
        elif item:
            turns.append(f"User: {item}")

    turns = [t for t in turns if t.split(": ", 1)[-1].strip()]
    if not turns:
        return ""

    return (
        "=== EARLIER IN THIS CONVERSATION (most recent last) ===\n\n"
        + "\n\n".join(turns)
    )


def _build_user_prompt(question: str, result: Dict[str, Any],
                       sources: List[Dict[str, Any]], history: Any) -> str:
    """
    Assemble the user half of the prompt: run facts, evidence, history, question.

    Order matters. The run context and the literature come first so the model
    reads the evidence before it reads the question, and the question goes
    last so it is the freshest thing in context when generation starts.
    """
    parts = [build_run_context(result), _format_passages(sources)]

    hist = _format_history(history)
    if hist:
        parts.append(hist)

    parts.append(f"=== QUESTION ===\n\n{question}")
    return "\n\n\n".join(parts)


def answer(question: str, result: Dict[str, Any],
           history: Optional[List[Any]] = None, k: int = 5) -> Dict[str, Any]:
    """
    Answer a question about a pipeline run, grounded in retrieved literature.

    The flow is retrieve -> assemble -> generate -> fall back:

      1. Retrieve the k nearest abstracts to the question.
      2. Build a prompt from the platform description, the run's own numbers,
         those abstracts, and the recent conversation.
      3. Generate.
      4. If generation is unavailable for any reason, compose from templates
         instead — those are computed from the run's real numbers, so the
         fallback answer is still correct, just less fluent.

    `provider` in the response says which path ran, so the difference is
    visible rather than silent.
    """
    try:
        sources = retrieve(question, k=k)
    except Exception as e:
        # Retrieval down is not fatal: the run's own numbers still support an
        # answer, it just loses its citations.
        logger.warning("Retrieval failed: %s: %s", type(e).__name__, e)
        sources = []
        retrieval_error = str(e)
    else:
        retrieval_error = None

    text = None
    provider = "templates"

    try:
        generated = llm.generate(
            system_prompt=platform_facts.build_system_prompt(),
            user_prompt=_build_user_prompt(question, result, sources, history),
        )
    except Exception as e:
        # llm.generate is documented not to raise, but the fallback must hold
        # even if that contract is broken — this path is the whole reason the
        # templates are still here.
        logger.warning("LLM layer raised: %s: %s", type(e).__name__, e)
        generated = None

    if generated:
        text = generated
        provider = llm.model_name()
    else:
        text = _compose(question, _facts(result))
        if retrieval_error:
            text += f"\n\n(Literature retrieval unavailable: {retrieval_error})"

    return {
        "answer": text,
        "sources": [{
            "pmid": s["pmid"],
            "title": s["title"],
            "journal": s["journal"],
            "year": s["year"],
            "url": s["url"],
            "similarity": s["similarity"],
        } for s in sources],
        "grounded_in": {
            "pipeline_output": True,
            "literature": len(sources),
        },
        "provider": provider,
        "passages": _passages(sources),
    }


# ------------------------------------------------------------- cross-check

# How many retrieved passages must name the gene before we call it covered.
WELL_COVERED_MENTIONS = 3

# Terms that pull retrieval toward the cancer-target literature rather than
# whatever else a bare gene symbol happens to sit near in embedding space.
QUERY_BIAS_TERMS = "neoantigen oncogenic driver mutation immunotherapy"


def _corpus_size() -> int:
    """How many abstracts are indexed, read live so the caveat cannot go stale."""
    try:
        info = corpus_info()
        n = info.get("documents")
        if isinstance(n, int) and n > 0:
            return n
    except Exception:
        pass
    return 0


def _caveat(n_docs: int) -> str:
    """
    The standing disclaimer. Shown in every state, including a good one.

    It is not decoration. The whole feature reports on a 618-abstract index,
    and a reader who forgets that will over-read a hit just as easily as a
    miss.
    """
    size = f"{n_docs:,} abstracts" if n_docs else "a few hundred abstracts"
    return (
        f"This is a lookup against CellSpark's own index of {size}, not a "
        f"literature review and not clinical validation. PubMed holds millions "
        f"of papers; what this index contains is a small, fixed sample. Treat "
        f"what comes back as a pointer to reading, never as a judgement about "
        f"the gene."
    )


def _gene_mentions(gene: str, sources: List[Dict[str, Any]]) -> int:
    """
    How many retrieved passages actually name the gene.

    Case-SENSITIVE on purpose. Gene symbols are uppercase, and several are
    also ordinary English words — matching "MET" case-insensitively finds
    "criteria were not met" and reports coverage that does not exist. In this
    corpus that one change takes MET from 5 apparent hits down to its real 1.
    """
    if not gene:
        return 0
    pattern = re.compile(r"\b" + re.escape(gene.strip()) + r"\b")
    return sum(1 for s in sources if pattern.search(s.get("text", "") or ""))


def _classify_coverage(mentions: int) -> str:
    """
    Decide coverage in code, never by asking the model.

    A model asked "did retrieval work?" will answer from the vibe of the
    passages, and it has every incentive to be agreeable. Counting mentions is
    a fact we can compute, so we compute it.
    """
    if mentions == 0:
        return "not_covered"
    if mentions < WELL_COVERED_MENTIONS:
        return "thin"
    return "well_covered"


def _not_covered_summary(gene: str, change: str, n_docs: int) -> str:
    """
    What we say when the index has nothing. The careful wording is the point.

    This must not read as a verdict. A gene can be among the most studied in
    oncology and still be missing from a corpus this size — PIK3CA is exactly
    that case here. So this says what is true: our index does not cover it,
    which is a fact about our index.
    """
    size = f"{n_docs:,} abstracts" if n_docs else "the abstracts"
    target = f"{gene} {change}".strip()
    return (
        f"The indexed corpus does not cover {gene}. None of the {size} "
        f"CellSpark has indexed mention this gene, so there is nothing here to "
        f"summarise.\n\n"
        f"That is a statement about CellSpark's index, not about {gene}. This "
        f"corpus is a small fixed sample assembled for the project, while "
        f"PubMed holds millions of papers. A gene can be heavily studied, "
        f"well validated and clinically important and still be absent from a "
        f"collection this small, so its absence here means nothing about "
        f"whether it is a genuine target.\n\n"
        f"To find out what is actually known about {target}, search PubMed "
        f"directly rather than relying on this index."
    )


def _cross_check_prompt(gene: str, change: str, sources: List[Dict[str, Any]],
                        coverage: str, mentions: int) -> str:
    """The task prompt for a gene the corpus does say something about."""
    thin_note = ""
    if coverage == "thin":
        thin_note = (
            f"\nCOVERAGE IS THIN: only {mentions} of the retrieved passages "
            f"mention {gene} at all. Say so in your first sentence. Do not pad "
            f"a thin result into a confident one.\n"
        )

    return f"""{_format_passages(sources)}


=== TASK ===

Summarise what the retrieved abstracts above say about the gene {gene}, in the
context of the alteration {change} found in this run.
{thin_note}
Rules for this summary, which override any instinct to be helpful:

  - Summarise ONLY what the passages above actually say. If you know things
    about {gene} that are not in these passages, leave them out. Your own
    knowledge of this gene is not a source here.
  - Cite every claim inline by PMID, as (PMID 12345678), using only PMIDs from
    the passages above.
  - These passages were retrieved by semantic similarity, so some may mention
    {gene} only in passing or be about something else entirely. Say when a
    passage is only tangentially related rather than stretching it to fit.
  - The passages almost certainly do not discuss {change} specifically. Say
    that plainly where it applies. Do not infer what this particular
    alteration does from general statements about the gene.
  - Do not state or imply that {gene} is or is not a validated cancer target,
    a good vaccine target, or clinically actionable. This is a corpus lookup.
    Those conclusions are not available from it.
  - Two or three short paragraphs. Plain prose, no Markdown, as instructed
    above.

If the passages genuinely say little about {gene}, say that directly. A short
honest answer is correct; a padded one is not."""


def cross_check(gene: str, change: str, result: Dict[str, Any],
                k: int = 6) -> Dict[str, Any]:
    """
    Ask what the indexed corpus says about one gene and alteration.

    Deliberately NOT a verdict on the gene. The corpus is a few hundred
    abstracts, so a miss means the index is small, not that the gene is
    uninteresting — see _not_covered_summary. Coverage is decided by counting
    gene mentions in code before any model is involved, and when the count is
    zero no model is called at all: a model handed an empty retrieval and a
    question about a famous gene will answer from memory, which is the one
    failure this feature exists to avoid.
    """
    gene = (gene or "").strip()
    change = (change or "").strip()
    n_docs = _corpus_size()
    caveat = _caveat(n_docs)

    query = f"{gene} {change} {QUERY_BIAS_TERMS}".strip()

    try:
        # Symbol-filtered, similarity-ranked: the bias terms decide WHICH of
        # the gene's abstracts come back, while the filter guarantees they are
        # the gene's abstracts at all. Dense retrieval alone cannot do this —
        # see retrieve_mentioning for the measurement.
        sources = retrieve_mentioning(gene, query, k=k)
    except Exception as e:
        logger.warning("Cross-check retrieval failed: %s: %s", type(e).__name__, e)
        return {
            "gene": gene,
            "change": change,
            "coverage": "not_covered",
            "summary": (
                "Literature retrieval is unavailable, so the indexed corpus "
                "could not be searched for this gene. This is a CellSpark "
                "problem, not a statement about the gene."
            ),
            "passages": [],
            "provider": "unavailable",
            "caveat": caveat,
        }

    mentions = _gene_mentions(gene, sources)
    coverage = _classify_coverage(mentions)

    # Nothing to summarise, and nothing a model could add that would not be
    # recalled rather than retrieved. Return before the LLM.
    if coverage == "not_covered":
        return {
            "gene": gene,
            "change": change,
            "coverage": coverage,
            "summary": _not_covered_summary(gene, change, n_docs),
            # Deliberately empty. Showing the nearest unrelated abstracts under
            # a gene lookup invites exactly the misreading this feature guards
            # against — they would look like evidence about the gene.
            "passages": [],
            "provider": "retrieval-only",
            "caveat": caveat,
        }

    try:
        generated = llm.generate(
            system_prompt=platform_facts.build_system_prompt(),
            user_prompt=_cross_check_prompt(gene, change, sources, coverage, mentions),
        )
    except Exception as e:
        logger.warning("Cross-check LLM layer raised: %s: %s", type(e).__name__, e)
        generated = None

    if generated:
        return {
            "gene": gene,
            "change": change,
            "coverage": coverage,
            "summary": generated,
            "passages": _passages(sources),
            "provider": llm.model_name(),
            "caveat": caveat,
        }

    # Same fallback discipline as answer(): report the retrieval honestly
    # rather than failing the request.
    plural = "passage" if mentions == 1 else "passages"
    return {
        "gene": gene,
        "change": change,
        "coverage": coverage,
        "summary": (
            f"Answer generation is switched off, so this is the raw retrieval "
            f"result: {mentions} of the {len(sources)} abstracts retrieved for "
            f"{gene} {change} mention {gene} by name. The matching passages are "
            f"listed below — read them directly to see what the index holds. "
            f"No summary was generated and nothing here has been interpreted."
        ),
        "passages": _passages(sources),
        "provider": "templates",
        "caveat": caveat,
    }
