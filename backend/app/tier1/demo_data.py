"""
Synthetic proteome and MAF generation.

Lets the API run end-to-end before real TCGA and UniProt files are
downloaded. Built once and cached in memory, so the first request is slow
and the rest are fast.
"""

import os
import random
import tempfile
from functools import lru_cache

AA = "ACDEFGHIKLMNPQRSTVWY"
GENES = ["TP53", "KRAS", "BRAF", "PIK3CA", "PTEN",
         "EGFR", "NRAS", "APC", "IDH1", "CTNNB1"]


@lru_cache(maxsize=1)
def build_demo_dataset(n_proteins: int = 1200, n_mutations: int = 30, seed: int = 42):
    """
    Returns (fasta_path, maf_path, proteins_dict, gene_change_to_accession).

    lru_cache means this runs once per server process. Files land in the
    system temp directory and are cleaned up by the OS.
    """
    random.seed(seed)
    tmpdir = tempfile.mkdtemp(prefix="cellspark_demo_")

    proteins = {}
    fasta_path = os.path.join(tmpdir, "proteome.fasta")
    with open(fasta_path, "w") as fh:
        for i in range(n_proteins):
            acc = f"SYN{i:05d}"
            seq = "".join(random.choice(AA) for _ in range(random.randint(180, 700)))
            proteins[acc] = seq
            fh.write(f">sp|{acc}|SYN{i}_HUMAN Synthetic protein {i}\n")
            for j in range(0, len(seq), 60):
                fh.write(seq[j:j + 60] + "\n")

    maf_path = os.path.join(tmpdir, "mutations.maf")
    chosen = random.sample(list(proteins), n_mutations)
    mapping = {}

    with open(maf_path, "w") as fh:
        fh.write("#version 2.4 synthetic\n")
        fh.write("Hugo_Symbol\tChromosome\tStart_Position\tVariant_Classification\t"
                 "Variant_Type\tTumor_Sample_Barcode\tHGVSp_Short\n")
        for k, acc in enumerate(chosen):
            seq = proteins[acc]
            pos = random.randint(20, len(seq) - 20)
            ref = seq[pos - 1]
            alt = random.choice([a for a in AA if a != ref])
            gene = GENES[k % len(GENES)]
            mapping[(gene, f"p.{ref}{pos}{alt}")] = acc
            fh.write(f"{gene}\t{random.randint(1, 22)}\t{random.randint(10**6, 10**8)}\t"
                     f"Missense_Mutation\tSNP\tTCGA-DEMO-0001-01A\tp.{ref}{pos}{alt}\n")
            fh.write(f"{gene}\t1\t{random.randint(10**6, 10**8)}\t"
                     f"Silent\tSNP\tTCGA-DEMO-0001-01A\tp.{ref}{pos}{ref}\n")

    return fasta_path, maf_path, proteins, mapping