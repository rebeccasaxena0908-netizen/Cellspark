"""
Human codon usage frequencies.

Source: Kazusa Codon Usage Database, Homo sapiens (GenBank release 160),
expressed as frequency per thousand codons.

WHY THIS MATTERS:
The genetic code is redundant — 64 codons encode only 20 amino acids plus
stop. Most amino acids have several SYNONYMOUS codons that produce exactly
the same residue. But human cells don't use them equally: each codon needs a
matching tRNA, and some tRNAs are abundant while others are scarce. A
sequence full of rare codons makes the ribosome stall waiting for tRNA, so
the protein is produced slowly and inefficiently.

Codon optimisation swaps rare codons for frequent ones. The amino acid
sequence is IDENTICAL afterwards — only the DNA/RNA spelling changes.
"""

# codon -> (amino acid, frequency per thousand)
CODON_USAGE = {
    # Alanine
    "GCU": ("A", 18.4), "GCC": ("A", 27.7), "GCA": ("A", 15.8), "GCG": ("A", 7.4),
    # Arginine
    "CGU": ("R", 4.5),  "CGC": ("R", 10.4), "CGA": ("R", 6.2),  "CGG": ("R", 11.4),
    "AGA": ("R", 12.2), "AGG": ("R", 12.0),
    # Asparagine
    "AAU": ("N", 17.0), "AAC": ("N", 19.1),
    # Aspartic acid
    "GAU": ("D", 21.8), "GAC": ("D", 25.1),
    # Cysteine
    "UGU": ("C", 10.6), "UGC": ("C", 12.6),
    # Glutamine
    "CAA": ("Q", 12.3), "CAG": ("Q", 34.2),
    # Glutamic acid
    "GAA": ("E", 29.0), "GAG": ("E", 39.6),
    # Glycine
    "GGU": ("G", 10.8), "GGC": ("G", 22.2), "GGA": ("G", 16.5), "GGG": ("G", 16.5),
    # Histidine
    "CAU": ("H", 10.9), "CAC": ("H", 15.1),
    # Isoleucine
    "AUU": ("I", 16.0), "AUC": ("I", 20.8), "AUA": ("I", 7.5),
    # Leucine
    "UUA": ("L", 7.7),  "UUG": ("L", 12.9), "CUU": ("L", 13.2),
    "CUC": ("L", 19.6), "CUA": ("L", 7.2),  "CUG": ("L", 39.6),
    # Lysine
    "AAA": ("K", 24.4), "AAG": ("K", 31.9),
    # Methionine (start)
    "AUG": ("M", 22.0),
    # Phenylalanine
    "UUU": ("F", 17.6), "UUC": ("F", 20.3),
    # Proline
    "CCU": ("P", 17.5), "CCC": ("P", 19.8), "CCA": ("P", 16.9), "CCG": ("P", 6.9),
    # Serine
    "UCU": ("S", 15.2), "UCC": ("S", 17.7), "UCA": ("S", 12.2),
    "UCG": ("S", 4.4),  "AGU": ("S", 12.1), "AGC": ("S", 19.5),
    # Threonine
    "ACU": ("T", 13.1), "ACC": ("T", 18.9), "ACA": ("T", 15.1), "ACG": ("T", 6.1),
    # Tryptophan
    "UGG": ("W", 13.2),
    # Tyrosine
    "UAU": ("Y", 12.2), "UAC": ("Y", 15.3),
    # Valine
    "GUU": ("V", 11.0), "GUC": ("V", 14.5), "GUA": ("V", 7.1), "GUG": ("V", 28.1),
    # Stop codons
    "UAA": ("*", 1.0),  "UAG": ("*", 0.8),  "UGA": ("*", 1.6),
}


def build_synonymous_map():
    """amino acid -> list of (codon, frequency), sorted most frequent first."""
    syn = {}
    for codon, (aa, freq) in CODON_USAGE.items():
        syn.setdefault(aa, []).append((codon, freq))
    for aa in syn:
        syn[aa].sort(key=lambda x: -x[1])
    return syn


SYNONYMOUS = build_synonymous_map()

# The most frequent codon for each amino acid — the reference point for CAI.
BEST_CODON = {aa: codons[0][0] for aa, codons in SYNONYMOUS.items()}

# Highest frequency available per amino acid, used as the CAI denominator.
MAX_FREQ = {aa: codons[0][1] for aa, codons in SYNONYMOUS.items()}