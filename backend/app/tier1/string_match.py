"""
Exact string matching — Knuth-Morris-Pratt and Boyer-Moore.

WHY THESE ARE HERE (know this for the viva):
TCGA MAF files already contain called variants, so there is no mutation
"finding" left to do — that happened upstream in the sequencing pipeline.

Our search layer does SELF-TOLERANCE SCREENING instead: given a candidate
mutated peptide, verify that exact motif does NOT occur anywhere in the
healthy human proteome (~20,400 proteins, ~11.4 million amino acids).

If it does occur in a healthy protein, we discard the candidate — a vaccine
against it would risk attacking normal tissue. This is what makes the target
tumour-exclusive, which is the entire safety argument for neoantigen vaccines.
"""

from typing import List


# -------------------------------------------------------------------------------- KMP
def kmp_failure_function(pattern: str) -> List[int]:
    """
    Build the LPS array (Longest Proper Prefix which is also Suffix).

    lps[i] = length of the longest proper prefix of pattern[0..i] that is
             also a suffix of pattern[0..i]

    This is what lets KMP avoid backtracking in the text: on a mismatch at
    pattern position j, resume at lps[j-1] instead of restarting, because
    those characters are already known to match.

    Time: O(m)
    """
    m = len(pattern)
    lps = [0] * m
    length = 0
    i = 1

    while i < m:
        if pattern[i] == pattern[length]:
            length += 1
            lps[i] = length
            i += 1
        elif length != 0:
            length = lps[length - 1]   # fall back, do NOT advance i
        else:
            lps[i] = 0
            i += 1

    return lps


def kmp_search(text: str, pattern: str, find_all: bool = False) -> List[int]:
    """
    Returns 0-based start indices where pattern occurs in text.
    find_all=False stops at the first hit — enough for tolerance screening,
    where we only need to know whether it exists.

    Time:  O(n + m), never backtracks in the text
    Space: O(m)
    """
    n, m = len(text), len(pattern)
    if m == 0 or m > n:
        return []

    lps = kmp_failure_function(pattern)
    matches = []
    i = j = 0

    while i < n:
        if text[i] == pattern[j]:
            i += 1
            j += 1
            if j == m:
                matches.append(i - m)
                if not find_all:
                    return matches
                j = lps[j - 1]
        elif j != 0:
            j = lps[j - 1]      # shift the pattern; text pointer stays put
        else:
            i += 1

    return matches

# --------------------------------------------------------- Boyer-Moore
def build_bad_character_table(pattern: str) -> dict:
    """
    Bad character heuristic — last occurrence index of each character.

    On a mismatch against text character c, shift the pattern so that the
    rightmost c in the pattern lines up with it. If c isn't in the pattern
    at all, skip past it entirely.

    NOTE FOR THE VIVA: this heuristic is weakest on small alphabets.
    Proteins use 20 amino acids and DNA only 4, versus natural language
    which has 26+ letters plus punctuation and far more variety. With a
    small alphabet, a mismatched character is likely to appear somewhere
    in the pattern, so shifts are shorter. This is exactly why we benchmark
    rather than assume Boyer-Moore always wins.
    """
    return {ch: i for i, ch in enumerate(pattern)}


def build_good_suffix_table(pattern: str) -> List[int]:
    """
    Good suffix heuristic.

    If a suffix of the pattern matched before the mismatch, shift so that
    another occurrence of that suffix lines up — or failing that, so a
    prefix of the pattern matches a suffix of what matched.

    Time: O(m)
    """
    m = len(pattern)
    shift = [0] * (m + 1)
    border = [0] * (m + 1)

    # Case 1: the matching suffix occurs elsewhere in the pattern
    i, j = m, m + 1
    border[i] = j
    while i > 0:
        while j <= m and pattern[i - 1] != pattern[j - 1]:
            if shift[j] == 0:
                shift[j] = j - i
            j = border[j]
        i -= 1
        j -= 1
        border[i] = j

    # Case 2: only part of the matching suffix occurs, as a prefix
    j = border[0]
    for i in range(m + 1):
        if shift[i] == 0:
            shift[i] = j
        if i == j:
            j = border[j]

    return shift


def boyer_moore_search(text: str, pattern: str, find_all: bool = False) -> List[int]:
    """
    Boyer-Moore using both heuristics, taking the larger shift of the two.

    Scans the pattern RIGHT TO LEFT, which is what allows whole blocks of
    text to be skipped without ever being examined.

    Time:  O(n/m) best case (sublinear), O(nm) worst case
    Space: O(m + alphabet)
    """
    n, m = len(text), len(pattern)
    if m == 0 or m > n:
        return []

    bad_char = build_bad_character_table(pattern)
    good_suffix = build_good_suffix_table(pattern)

    matches = []
    s = 0   # how far the pattern is shifted along the text

    while s <= n - m:
        j = m - 1
        while j >= 0 and pattern[j] == text[s + j]:   # right to left
            j -= 1

        if j < 0:
            matches.append(s)
            if not find_all:
                return matches
            s += good_suffix[0]
        else:
            bc_shift = j - bad_char.get(text[s + j], -1)
            gs_shift = good_suffix[j + 1]
            s += max(1, bc_shift, gs_shift)

    return matches


# ------------------------------------------------------------ baseline
def naive_search(text: str, pattern: str, find_all: bool = False) -> List[int]:
    """Brute force O(nm). Here only as a benchmark control."""
    n, m = len(text), len(pattern)
    matches = []
    for s in range(n - m + 1):
        k = 0
        while k < m and text[s + k] == pattern[k]:
            k += 1
        if k == m:
            matches.append(s)
            if not find_all:
                return matches
    return matches


ALGORITHMS = {
    "kmp": kmp_search,
    "boyer_moore": boyer_moore_search,
    "naive": naive_search,
}