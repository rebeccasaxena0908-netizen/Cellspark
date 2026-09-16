"""
Gene name to protein sequence index.

THE PROBLEM THIS SOLVES:
A MAF file tells us "TP53 has mutation p.R248W". To build peptide windows we
need TP53's actual amino acid sequence — the MAF doesn't carry it. UniProt
FASTA headers contain a GN= field with the gene symbol, so parsing that gives
us the mapping.

  >sp|P04637|P53_HUMAN Cellular tumor antigen p53 OS=Homo sapiens GN=TP53 ...
                                                                  ^^^^^^^

TWO REAL COMPLICATIONS, both worth knowing for the viva:

1. ISOFORMS. One gene can map to several UniProt entries. Restricting to
   reviewed (Swiss-Prot) entries mostly handles this, but where duplicates
   remain we keep the longest sequence, which is usually the canonical one.

2. POSITION MISMATCHES. A MAF's protein coordinates were computed against
   some specific transcript, which may not be UniProt's canonical isoform. So
   "position 248 is arginine" can simply be false for the sequence we hold.
   generate_peptide_windows() already checks this and skips on mismatch.
   Expect to lose 10-20% of mutations — that is normal, and we report it
   rather than hiding it.
"""

import os
import re
from functools import lru_cache
from typing import Dict, Optional, Tuple

from .proteome import read_fasta

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "data")
UNIPROT_PATH = os.path.join(DATA_DIR, "uniprot_human.fasta")

GN_RE = re.compile(r"\bGN=(\S+)")


def read_fasta_with_headers(path: str):
    """
    Like read_fasta, but yields the full description line too, so we can
    parse the GN= field out of it.

    Yields (accession, description, sequence).
    """
    acc, desc, chunks = None, "", []
    with open(path, "r") as fh:
        for line in fh:
            line = line.rstrip()
            if not line:
                continue
            if line.startswith(">"):
                if acc is not None:
                    yield acc, desc, "".join(chunks)
                header = line[1:]
                parts = header.split("|")
                acc = parts[1] if len(parts) >= 2 else header.split()[0]
                desc = header
                chunks = []
            else:
                chunks.append(line.strip())
    if acc is not None:
        yield acc, desc, "".join(chunks)


@lru_cache(maxsize=1)
def build_gene_index() -> Dict[str, Tuple[str, str]]:
    """
    gene_symbol -> (uniprot_accession, sequence)

    Built once per process and cached. Parsing 20,000 entries takes a couple
    of seconds, which is fine at startup but not per request.
    """
    if not os.path.exists(UNIPROT_PATH):
        raise FileNotFoundError(
            f"UniProt proteome not found at {UNIPROT_PATH}. "
            f"See data/README.md for the download command."
        )

    index: Dict[str, Tuple[str, str]] = {}

    for acc, desc, seq in read_fasta_with_headers(UNIPROT_PATH):
        m = GN_RE.search(desc)
        if not m:
            continue                      # some entries have no gene name
        gene = m.group(1).upper()

        existing = index.get(gene)
        # keep the longest sequence when a gene has several entries
        if existing is None or len(seq) > len(existing[1]):
            index[gene] = (acc, seq)

    return index


def lookup(gene: str) -> Optional[Tuple[str, str]]:
    """Return (accession, sequence) for a gene symbol, or None."""
    return build_gene_index().get(gene.upper())


def index_info() -> Dict[str, int]:
    """Summary for the API."""
    try:
        idx = build_gene_index()
        return {
            "available": True,
            "genes": len(idx),
            "residues": sum(len(s) for _, s in idx.values()),
        }
    except FileNotFoundError as e:
        return {"available": False, "error": str(e)}