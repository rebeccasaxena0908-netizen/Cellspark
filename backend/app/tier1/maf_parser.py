"""
MAF parsing and mutated peptide generation.

A MAF (Mutation Annotation Format) file is TCGA's tab-delimited table of
called somatic mutations. The columns we care about:

  Hugo_Symbol             gene name, e.g. TP53
  Variant_Classification  Missense_Mutation, Silent, Nonsense_Mutation, ...
  Tumor_Sample_Barcode    which patient
  HGVSp_Short             protein change, e.g. p.R248W

WHY MISSENSE ONLY (expect this question):
  - Silent mutations don't change the protein, so there's no new peptide
    and therefore no neoantigen.
  - Nonsense mutations truncate the protein; the cell usually degrades the
    result before it can be displayed.
  - Missense swaps one amino acid, creating a genuinely novel peptide that
    has never existed in the patient's healthy tissue. That novelty is
    exactly what we want the immune system to recognise.

Frameshift indels also produce strong neoantigens — often the strongest —
but they need the full downstream reading frame to reconstruct. Deferred to
Future Scope, and worth saying so out loud rather than leaving unexplained.
"""

import re
from dataclasses import dataclass, asdict
from typing import List, Optional

import pandas as pd


# MHC Class I displays peptides of roughly 8-11 residues. 9 is most common.
PEPTIDE_LENGTHS = (8, 9, 10, 11)

HGVSP_RE = re.compile(r"^p\.([A-Z])(\d+)([A-Z])$")

AA3_TO_1 = {
    'Ala': 'A', 'Arg': 'R', 'Asn': 'N', 'Asp': 'D', 'Cys': 'C',
    'Gln': 'Q', 'Glu': 'E', 'Gly': 'G', 'His': 'H', 'Ile': 'I',
    'Leu': 'L', 'Lys': 'K', 'Met': 'M', 'Phe': 'F', 'Pro': 'P',
    'Ser': 'S', 'Thr': 'T', 'Trp': 'W', 'Tyr': 'Y', 'Val': 'V',
}


@dataclass
class Mutation:
    gene: str
    sample_barcode: str
    protein_change: str      # "p.R248W"
    ref_aa: str              # R
    position: int            # 248, 1-based protein coordinate
    alt_aa: str              # W
    chromosome: str = ""
    start_position: int = 0

    def to_dict(self):
        return asdict(self)


@dataclass
class PeptideCandidate:
    gene: str
    sample_barcode: str
    protein_change: str
    peptide: str             # mutated sequence
    wildtype_peptide: str    # same window, original residue
    length: int
    mutation_offset: int     # 0-based index of the mutated residue
    uniprot_id: str = ""

    def to_dict(self):
        return asdict(self)


def parse_hgvsp(hgvsp: str) -> Optional[tuple]:
    """
    Parse a protein change into (ref_aa, position, alt_aa).
    Handles 1-letter (p.R248W) and 3-letter (p.Arg248Trp) forms.
    Returns None for anything that isn't a simple substitution.
    """
    if not isinstance(hgvsp, str) or not hgvsp.startswith("p."):
        return None

    m = HGVSP_RE.match(hgvsp.strip())
    if m:
        return m.group(1), int(m.group(2)), m.group(3)

    m3 = re.match(r"^p\.([A-Z][a-z]{2})(\d+)([A-Z][a-z]{2})$", hgvsp.strip())
    if m3:
        ref = AA3_TO_1.get(m3.group(1))
        alt = AA3_TO_1.get(m3.group(3))
        if ref and alt:
            return ref, int(m3.group(2)), alt

    return None


def load_maf(path: str, sample_barcode: Optional[str] = None,
             max_mutations: Optional[int] = None) -> List[Mutation]:
    """
    Read a MAF file and return its missense mutations.

    comment='#' is required — MAF files open with '#version' header lines.
    Column capitalisation varies between TCGA releases, so we look them up
    case-insensitively rather than assuming.
    """
    df = pd.read_csv(path, sep="\t", comment="#", low_memory=False,
                     dtype=str, on_bad_lines="skip")

    cols = {c.lower(): c for c in df.columns}
    col = lambda name: cols.get(name.lower())

    c_gene = col("Hugo_Symbol")
    c_class = col("Variant_Classification")
    c_sample = col("Tumor_Sample_Barcode")
    c_hgvsp = (col("HGVSp_Short") or col("HGVSp")
               or col("Protein_Change") or col("amino_acid_change"))
    c_chrom = col("Chromosome")
    c_start = col("Start_Position") or col("Start_position")

    missing = [n for n, c in [("Hugo_Symbol", c_gene),
                              ("Variant_Classification", c_class),
                              ("HGVSp_Short", c_hgvsp)] if c is None]
    if missing:
        raise ValueError(f"MAF missing required columns: {missing}\n"
                         f"Found: {list(df.columns)[:25]}")

    df = df[df[c_class] == "Missense_Mutation"]
    if sample_barcode and c_sample:
        df = df[df[c_sample].astype(str).str.startswith(sample_barcode)]

    mutations = []
    for _, row in df.iterrows():
        parsed = parse_hgvsp(row.get(c_hgvsp, ""))
        if parsed is None:
            continue
        ref_aa, pos, alt_aa = parsed
        mutations.append(Mutation(
            gene=str(row[c_gene]),
            sample_barcode=str(row[c_sample]) if c_sample else "UNKNOWN",
            protein_change=str(row[c_hgvsp]),
            ref_aa=ref_aa, position=pos, alt_aa=alt_aa,
            chromosome=str(row[c_chrom]) if c_chrom else "",
            start_position=int(row[c_start]) if c_start and str(row[c_start]).isdigit() else 0,
        ))
        if max_mutations and len(mutations) >= max_mutations:
            break

    return mutations

def generate_peptide_windows(protein_seq: str, mutation: Mutation,
                             lengths=PEPTIDE_LENGTHS,
                             uniprot_id: str = "") -> List[PeptideCandidate]:
    """
    Slide a window of each length across the mutation site.

    THE KEY CONCEPT (this is the 1:N in your ER diagram, made concrete):
    A single mutation produces MANY candidate peptides. For a 9-mer, the
    mutated residue can sit at any of 9 positions in the window, so there
    are up to 9 distinct 9-mers containing it. Across lengths 8 to 11 that
    is up to 38 candidates from ONE mutation.

    We don't know in advance which window the patient's MHC will actually
    display, so we generate them all and let Tier 2's binding predictor
    decide.

    We also build the matching wild-type peptide, so Tier 2 can check the
    mutation genuinely improves binding rather than merely binding well.
    """
    idx = mutation.position - 1          # MAF is 1-based, Python is 0-based

    if idx < 0 or idx >= len(protein_seq):
        return []

    # Sanity check: does the reference residue actually match the annotation?
    # Mismatches happen when the MAF refers to a different protein isoform
    # than UniProt's canonical entry. Expect to lose 10-20% of mutations
    # this way — that's normal, and worth reporting rather than hiding.
    if protein_seq[idx] != mutation.ref_aa:
        return []

    mutated_protein = protein_seq[:idx] + mutation.alt_aa + protein_seq[idx + 1:]

    candidates = []
    for L in lengths:
        for offset in range(L):
            start = idx - offset
            end = start + L
            if start < 0 or end > len(mutated_protein):
                continue

            pep = mutated_protein[start:end]
            wt = protein_seq[start:end]

            # skip anything with stop codons or unknown residues
            if len(pep) != L or "*" in pep or "X" in pep:
                continue

            candidates.append(PeptideCandidate(
                gene=mutation.gene,
                sample_barcode=mutation.sample_barcode,
                protein_change=mutation.protein_change,
                peptide=pep,
                wildtype_peptide=wt,
                length=L,
                mutation_offset=offset,
                uniprot_id=uniprot_id,
            ))

    return candidates

def screen_candidates(index, candidates: List[PeptideCandidate],
                      algorithm: str = "kmp"):
    """
    Self-tolerance screen. Splits candidates into (tumour_specific, rejected).

    Only the tumour-specific list proceeds to Tier 2. Anything whose exact
    motif appears in a healthy protein is discarded — targeting it would
    risk autoimmunity.
    """
    kept, rejected = [], []
    for c in candidates:
        if index.contains(c.peptide, algorithm):
            rejected.append(c)
        else:
            kept.append(c)
    return kept, rejected