"""
Tier 2 — Peptide-MHC binding prediction.

Takes tumour-specific peptides from Tier 1 and predicts how tightly each one
binds the patient's HLA molecules, using MHCflurry 2.2 (PyTorch ensemble).

KEY CONCEPT: IC50 RUNS BACKWARDS.
Affinity is reported in nanomolar, and a LOWER number means TIGHTER binding.
Conventional thresholds:
    < 50 nM   strong binder
    < 500 nM  weak but plausible binder
    >= 500 nM below threshold
So the ranking sorts ASCENDING. This is the single most common
misinterpretation of neoantigen output, which is why the UI labels every
score in words as well as numbers.

AGRETOPICITY: we also score the wild-type version of each peptide. A good
neoantigen doesn't just bind well — it binds BETTER than the healthy
sequence it came from. If the wild-type binds equally well, the immune
system has already learned to tolerate that shape, so the mutation buys
nothing.
"""

from functools import lru_cache
from typing import List, Dict, Any


@lru_cache(maxsize=1)
def get_predictor():
    """
    Load the MHCflurry ensemble once per process.

    Loading takes 20-30 seconds and allocates a fair amount of memory, so it
    must not happen per request. lru_cache gives us a lazy singleton.
    """
    from mhcflurry import Class1PresentationPredictor
    return Class1PresentationPredictor.load()


def band_for(ic50: float) -> Dict[str, str]:
    """Human-readable interpretation of an affinity score."""
    if ic50 < 50:
        return {"label": "Strong binder", "tone": "ok"}
    if ic50 < 500:
        return {"label": "Weak binder", "tone": "warn"}
    return {"label": "Below threshold", "tone": "alert"}


def predict_binding(peptides: List[Dict[str, Any]], alleles: List[str],
                    top_n: int = 10) -> Dict[str, Any]:
    """
    Score candidate peptides against the patient's HLA alleles.

    `peptides` are dicts from Tier 1 (PeptideCandidate.to_dict()).
    Returns the top_n ranked by ascending IC50, plus summary statistics.
    """
    if not peptides:
        return {"implemented": True, "targets": [], "stats": {}}

    predictor = get_predictor()

    # MHCflurry only handles lengths 8-15. Tier 1 gives us 8-11, but guard
    # anyway so a bad input can't crash the whole request.
    valid = [p for p in peptides if 8 <= len(p["peptide"]) <= 15]

    mutant_seqs = [p["peptide"] for p in valid]
    wildtype_seqs = [p["wildtype_peptide"] for p in valid]

    mut_df = predictor.predict(peptides=mutant_seqs, alleles=alleles, verbose=0)
    wt_df = predictor.predict(peptides=wildtype_seqs, alleles=alleles, verbose=0)

    rows = []
    for i, cand in enumerate(valid):
        ic50 = float(mut_df.iloc[i]["affinity"])
        wt_ic50 = float(wt_df.iloc[i]["affinity"])
        band = band_for(ic50)

        rows.append({
            "peptide": cand["peptide"],
            "wildtype": cand["wildtype_peptide"],
            "gene": cand["gene"],
            "change": cand["protein_change"],
            "allele": str(mut_df.iloc[i]["best_allele"]),
            "ic50": round(ic50, 1),
            "wtIc50": round(wt_ic50, 1),
            # how much better the mutant binds than the healthy version
            "agretopicity": round(wt_ic50 / ic50, 2) if ic50 > 0 else 0,
            "mutPos": cand["mutation_offset"],
            "length": cand["length"],
            "band": band["label"],
            "tone": band["tone"],
        })

    rows.sort(key=lambda r: r["ic50"])          # ASCENDING — lower binds tighter
    top = rows[:top_n]
    for rank, row in enumerate(top, start=1):
        row["rank"] = rank

    return {
        "implemented": True,
        "predictor": "MHCflurry 2.2 (PyTorch)",
        "alleles": alleles,
        "stats": {
            "scored": len(rows),
            "strong_binders": sum(1 for r in rows if r["ic50"] < 50),
            "weak_binders": sum(1 for r in rows if 50 <= r["ic50"] < 500),
            "below_threshold": sum(1 for r in rows if r["ic50"] >= 500),
            "best_ic50": round(rows[0]["ic50"], 1) if rows else None,
        },
        "targets": top,
    }