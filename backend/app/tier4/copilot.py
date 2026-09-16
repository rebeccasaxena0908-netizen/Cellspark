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

import os
from typing import Any, Dict, List

from .retriever import retrieve, corpus_info


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


def answer(question: str, result: Dict[str, Any], k: int = 3) -> Dict[str, Any]:
    """
    Answer a question about a pipeline run.

    Returns the composed answer plus the retrieved literature that supports
    the general claims, so every statement is traceable.
    """
    facts = _facts(result)
    text = _compose(question, facts)

    try:
        sources = retrieve(question, k=k)
    except Exception as e:
        sources = []
        text += f"\n\n(Literature retrieval unavailable: {e})"

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
    }