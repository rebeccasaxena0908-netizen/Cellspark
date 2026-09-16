"""
Reference proteome index for self-tolerance screening.

Holds the healthy human proteome in memory so candidate peptides can be
checked against it repeatedly.

DESIGN NOTE (good viva material):
We concatenate all ~20,400 protein sequences into ONE large string, joined
by a sentinel character that can never appear in a real peptide. So each
peptide needs one search pass over one big text, rather than 20,400 separate
searches with 20,400 function-call overheads.

The sentinel matters: without it, a peptide could "match" across a boundary
between two proteins — a sequence that exists in neither. The sentinel makes
that impossible, because no real peptide contains it.
"""

import bisect
from typing import Iterator, List, Tuple

from .string_match import kmp_search, boyer_moore_search, naive_search

_ALGOS = {
    "kmp": kmp_search,
    "boyer_moore": boyer_moore_search,
    "naive": naive_search,
}


def read_fasta(path: str) -> Iterator[Tuple[str, str]]:
    """
    Minimal FASTA reader — yields (accession, sequence).

    UniProt headers look like:
      >sp|P04637|P53_HUMAN Cellular tumor antigen p53 OS=Homo sapiens GN=TP53
    We keep the accession in the middle (P04637).

    Written by hand rather than using Biopython so Tier 1 has one fewer
    dependency. FASTA is a simple enough format that this is safe; we use
    Biopython later for VCF, where the parsing genuinely is non-trivial.
    """
    header, chunks = None, []
    with open(path, "r") as fh:
        for line in fh:
            line = line.rstrip()
            if not line:
                continue
            if line.startswith(">"):
                if header is not None:
                    yield header, "".join(chunks)
                parts = line[1:].split("|")
                header = parts[1] if len(parts) >= 2 else line[1:].split()[0]
                chunks = []
            else:
                chunks.append(line.strip())
    if header is not None:
        yield header, "".join(chunks)


class ProteomeIndex:
    """Searchable in-memory index of the healthy human proteome."""

    SENTINEL = "|"

    def __init__(self, fasta_path: str, limit: int = None):
        self.ids: List[str] = []
        self.offsets: List[int] = []
        parts = []
        cursor = 0

        for n, (pid, seq) in enumerate(read_fasta(fasta_path)):
            if limit and n >= limit:
                break
            self.ids.append(pid)
            self.offsets.append(cursor)
            parts.append(seq)
            cursor += len(seq) + 1          # +1 for the sentinel

        self.text = self.SENTINEL.join(parts)
        self.n_proteins = len(self.ids)
        self.n_residues = sum(len(p) for p in parts)

    def __repr__(self):
        return (f"<ProteomeIndex {self.n_proteins:,} proteins, "
                f"{self.n_residues:,} residues>")

    def locate(self, index: int) -> str:
        """
        Map a character offset in the concatenated text back to the protein
        that contains it. Binary search over the offsets — O(log n).
        """
        i = bisect.bisect_right(self.offsets, index) - 1
        return self.ids[i] if 0 <= i < len(self.ids) else "?"

    def contains(self, peptide: str, algorithm: str = "kmp") -> bool:
        """Does this exact peptide occur anywhere in the healthy proteome?"""
        return len(_ALGOS[algorithm](self.text, peptide, find_all=False)) > 0

    def find_source(self, peptide: str, algorithm: str = "kmp"):
        """Which healthy protein contains it? Returns None if tumour-specific."""
        hits = _ALGOS[algorithm](self.text, peptide, find_all=False)
        return self.locate(hits[0]) if hits else None