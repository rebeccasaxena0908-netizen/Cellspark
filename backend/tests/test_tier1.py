"""
Tier 1 integration test with synthetic data — no downloads needed.

Builds a fake proteome and MAF, runs the full flow, and checks the shape
of what comes out.
"""
import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.tier1.maf_parser import (
    load_maf, generate_peptide_windows, screen_candidates, PEPTIDE_LENGTHS
)
from app.tier1.proteome import ProteomeIndex

AA = "ACDEFGHIKLMNPQRSTVWY"


def build_synthetic(tmpdir, n_proteins=300, n_mutations=15, seed=42):
    random.seed(seed)
    proteins = {}
    fasta = os.path.join(tmpdir, "proteome.fasta")

    with open(fasta, "w") as fh:
        for i in range(n_proteins):
            acc = f"SYN{i:05d}"
            seq = "".join(random.choice(AA) for _ in range(random.randint(150, 600)))
            proteins[acc] = seq
            fh.write(f">sp|{acc}|SYN{i}_HUMAN Synthetic protein {i}\n{seq}\n")

    genes = ["TP53", "KRAS", "BRAF", "EGFR", "PTEN"]
    maf = os.path.join(tmpdir, "mutations.maf")
    chosen = random.sample(list(proteins), n_mutations)
    mapping = {}

    with open(maf, "w") as fh:
        fh.write("#version 2.4 synthetic\n")
        fh.write("Hugo_Symbol\tChromosome\tStart_Position\tVariant_Classification\t"
                 "Variant_Type\tTumor_Sample_Barcode\tHGVSp_Short\n")
        for k, acc in enumerate(chosen):
            seq = proteins[acc]
            pos = random.randint(20, len(seq) - 20)
            ref = seq[pos - 1]
            alt = random.choice([a for a in AA if a != ref])
            gene = genes[k % len(genes)]
            mapping[(gene, f"p.{ref}{pos}{alt}")] = acc
            fh.write(f"{gene}\t1\t{1000+k}\tMissense_Mutation\tSNP\t"
                     f"TCGA-DEMO-0001\tp.{ref}{pos}{alt}\n")
            # a silent mutation too, to prove filtering works
            fh.write(f"{gene}\t1\t{2000+k}\tSilent\tSNP\t"
                     f"TCGA-DEMO-0001\tp.{ref}{pos}{ref}\n")

    return fasta, maf, proteins, mapping


def main():
    with tempfile.TemporaryDirectory() as tmp:
        fasta, maf, proteins, mapping = build_synthetic(tmp)

        print("Loading proteome...")
        index = ProteomeIndex(fasta)
        print(f"  {index}")

        print("\nParsing MAF...")
        muts = load_maf(maf)
        print(f"  {len(muts)} missense mutations (silent ones filtered out)")
        assert len(muts) == 15, f"expected 15 missense, got {len(muts)}"

        print("\nGenerating peptide windows...")
        allc = []
        for m in muts:
            acc = mapping.get((m.gene, m.protein_change))
            allc.extend(generate_peptide_windows(proteins[acc], m, uniprot_id=acc))
        print(f"  {len(allc)} candidates from {len(muts)} mutations")
        print(f"  average {len(allc)/len(muts):.1f} peptides per mutation  <- the 1:N relationship")
        assert len(allc) > 0

        print("\nSelf-tolerance screening...")
        kept, rejected = screen_candidates(index, allc, algorithm="kmp")
        print(f"  tumour-specific: {len(kept)}")
        print(f"  rejected (found in healthy proteome): {len(rejected)}")

        # cross-check: both algorithms must agree
        kept_bm, _ = screen_candidates(index, allc, algorithm="boyer_moore")
        assert len(kept) == len(kept_bm), "KMP and Boyer-Moore disagree!"
        print("  KMP and Boyer-Moore agree")

        print("\nTier 1 works.")


if __name__ == "__main__":
    main()