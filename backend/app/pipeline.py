
import os

from .tier1.demo_data import build_demo_dataset
from .tier1.gene_index import (
    UNIPROT_PATH,
    index_info as gene_index_info,
    lookup as gene_lookup,
)
from .tier1.maf_parser import load_maf, generate_peptide_windows, screen_candidates
from .tier1.proteome import ProteomeIndex
from .tier2.binding import predict_binding
from .tier3.optimise import design_mrna
from .upload import get_upload_path

# Built once per process — loading a proteome is the expensive part.
_index = None
_dataset = None
_real_index = None


def _get_demo():
    """Synthetic proteome and MAF, used when no file is uploaded."""
    global _index, _dataset
    if _dataset is None:
        _dataset = build_demo_dataset()
        _index = ProteomeIndex(_dataset[0])
    return _index, _dataset


def _get_real_index():
    """
    ProteomeIndex over the real UniProt human proteome.

    Built lazily and cached — 20,431 proteins and 11.4M residues take several
    seconds to index, so this must not happen per request.
    """
    global _real_index
    if _real_index is None:
        _real_index = ProteomeIndex(UNIPROT_PATH)
    return _real_index


def run_tier1(algorithm: str = "kmp", max_mutations: int = 400,
              upload_id: str = None, sample_barcode: str = None,
              screen_now: bool = None):
    """
    Parse mutations and build peptide windows.

    With no upload_id, runs on the synthetic demo dataset, which ships its own
    protein sequences and is small enough to screen exhaustively here. With
    one, resolves each gene symbol against the real UniProt human proteome and
    defers screening until after ranking (see module docstring).

    Two failure modes are counted separately on real uploads, because they
    mean different things:
      - unmapped_genes: the gene symbol isn't in UniProt at all
      - position_mismatch: the gene was found, but the MAF's reference amino
        acid disagrees with UniProt's canonical sequence — almost always an
        isoform difference
    """
    index, (fasta_path, maf_path, proteins, mapping) = _get_demo()

    using_upload = bool(upload_id)
    if using_upload:
        maf_path = get_upload_path(upload_id)
        # Real uploads screen against the real proteome; the demo screens
        # against its own synthetic one.
        if os.path.exists(UNIPROT_PATH):
            index = _get_real_index()

    # Demo datasets are small enough to screen up front. Real uploads defer.
    if screen_now is None:
        screen_now = not using_upload

    mutations = load_maf(
        maf_path,
        sample_barcode=sample_barcode,
        max_mutations=max_mutations,
    )

    candidates = []
    unmapped = 0            # gene not found in the reference proteome
    position_mismatch = 0   # gene found, but the reference residue disagrees

    for m in mutations:
        if using_upload:
            # Real file: resolve the gene symbol against UniProt
            hit = gene_lookup(m.gene)
            if not hit:
                unmapped += 1
                continue
            acc, seq = hit
        else:
            # Demo dataset ships its own sequences
            acc = mapping.get((m.gene, m.protein_change))
            if not acc:
                unmapped += 1
                continue
            seq = proteins[acc]

        windows = generate_peptide_windows(seq, m, uniprot_id=acc)
        if not windows and using_upload:
            # generate_peptide_windows returns [] when the reference residue
            # doesn't match the annotation — an isoform difference between the
            # MAF's transcript and UniProt's canonical sequence.
            position_mismatch += 1
        candidates.extend(windows)

    if screen_now:
        kept, rejected = screen_candidates(index, candidates, algorithm=algorithm)
    else:
        # Screening is deferred to after ranking — see run_pipeline
        kept, rejected = candidates, []

    out = {
        "implemented": True,
        "algorithm": algorithm,
        "source": "upload" if using_upload else "demo",
        "screening_stage": "pre_ranking" if screen_now else "post_ranking",
        "proteome": {
            "proteins": index.n_proteins,
            "residues": index.n_residues,
            "reference": "UniProt Swiss-Prot human" if using_upload else "synthetic demo",
        },
        "gene_index": gene_index_info() if using_upload else None,
        "stats": {
            "mutations": len(mutations),
            "candidates": len(candidates),
            "tumour_specific": len(kept),
            "rejected_self": len(rejected),
            "unmapped_genes": unmapped,
            "position_mismatch": position_mismatch,
            "peptides_per_mutation": round(len(candidates) / max(1, len(mutations)), 1),
        },
        "mutations": [m.to_dict() for m in mutations[:20]],
        "peptides": [c.to_dict() for c in kept],
    }

    if using_upload and (unmapped or position_mismatch):
        parts = []
        if unmapped:
            parts.append(f"{unmapped} gene(s) not found in the reference proteome")
        if position_mismatch:
            parts.append(
                f"{position_mismatch} mutation(s) where the reference amino acid "
                f"disagreed with UniProt's canonical sequence — usually an "
                f"isoform difference"
            )
        out["warning"] = f"Of {len(mutations)} mutations: " + "; ".join(parts) + "."

    return out


def run_pipeline(alleles=None, file_name="sample_patient.maf", algorithm="kmp",
                 upload_id=None, sample_barcode=None):
    """
    Full pipeline run.

    Each tier is wrapped so one failure degrades that section rather than
    taking down the whole request. The frontend reads the "implemented" flags
    to label what's real.
    """
    alleles = alleles or ["HLA-A*02:01"]
    using_upload = bool(upload_id)

    tier1 = run_tier1(
        algorithm=algorithm,
        upload_id=upload_id,
        sample_barcode=sample_barcode,
    )

    # MHCflurry batches efficiently, so scoring thousands is cheap relative to
    # string screening. Still capped to bound worst-case memory.
    MAX_TO_SCORE = 15000
    to_score = tier1["peptides"][:MAX_TO_SCORE]

    # --- Tier 2: binding prediction -------------------------------------
    try:
        # Ask for extra candidates so the tolerance screen has replacements
        # available if any of the top ranks are rejected.
        want = 30 if using_upload else 10
        tier2 = predict_binding(to_score, alleles, top_n=want)
        tier2["scored_subset"] = len(to_score)
        tier2["available"] = tier1["stats"]["candidates"]
    except Exception as e:
        # A failed model load shouldn't take down the whole request — report
        # it and let Tier 1 results still reach the user.
        tier2 = {
            "implemented": False,
            "error": str(e),
            "note": "MHCflurry unavailable; check model weights are downloaded",
        }

    # --- Tolerance screening on the ranked shortlist ---------------------
    # Done here rather than in Tier 1 so we screen the peptides we actually
    # intend to propose, not an arbitrary slice of the candidate pool.
    if using_upload and tier2.get("targets"):
        index = _get_real_index() if os.path.exists(UNIPROT_PATH) else _get_demo()[0]

        surviving, self_matching = [], []
        for t in tier2["targets"]:
            if index.contains(t["peptide"], algorithm):
                t["self_match"] = index.find_source(t["peptide"], algorithm)
                self_matching.append(t)
            else:
                surviving.append(t)

        # renumber after removals so ranks stay contiguous
        surviving = surviving[:10]
        for i, t in enumerate(surviving, start=1):
            t["rank"] = i

        tier2["targets"] = surviving
        tier2["screened_shortlist"] = len(tier2.get("targets", [])) + len(self_matching)
        tier2["rejected_self"] = len(self_matching)
        tier2["rejected_peptides"] = [
            {"peptide": t["peptide"], "gene": t["gene"], "found_in": t.get("self_match")}
            for t in self_matching
        ]
        # surface it where the UI already reads screening numbers
        tier1["stats"]["rejected_self"] = len(self_matching)
        tier1["stats"]["screened"] = len(surviving) + len(self_matching)

    # --- Tier 3: design the mRNA for the top-ranked target ---------------
    try:
        targets = tier2.get("targets", [])
        if targets:
            top = targets[0]
            tier3 = design_mrna(
                peptide=top["peptide"],
                gene=top.get("gene", ""),
                change=top.get("change", ""),
            )
        else:
            tier3 = {"implemented": False, "note": "No targets available to design from"}
    except Exception as e:
        tier3 = {"implemented": False, "error": str(e)}

    return {
        "file_name": file_name,
        "alleles": alleles,
        "source": tier1["source"],
        "tier1": tier1,
        "tier2": tier2,
        "tier3": tier3,
        # Tier 4 is request-driven, not part of a run — see /api/copilot/ask
        "tier4": {
            "implemented": True,
            "note": "Copilot answers on demand via /api/copilot/ask",
        },
    }