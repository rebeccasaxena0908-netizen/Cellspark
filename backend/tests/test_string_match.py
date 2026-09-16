"""
Correctness tests for KMP and Boyer-Moore.

Strategy: both must agree with the naive baseline on every input. Naive is
obviously correct because it checks every position, so it's a trustworthy
oracle. Any disagreement means one of the clever algorithms has a bug.

Run from the backend/ folder:
    python tests/test_string_match.py
"""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.tier1.string_match import kmp_search, boyer_moore_search, naive_search


def check(text, pattern, label=""):
    expected = naive_search(text, pattern, find_all=True)
    got_kmp = kmp_search(text, pattern, find_all=True)
    got_bm = boyer_moore_search(text, pattern, find_all=True)
    assert got_kmp == expected, f"KMP failed {label}: {got_kmp} != {expected} (pattern={pattern!r})"
    assert got_bm == expected, f"BM failed {label}: {got_bm} != {expected} (pattern={pattern!r})"


def test_basic():
    check("ABABDABACDABABCABAB", "ABABCABAB", "classic KMP example")
    check("AAAAAA", "AA", "overlapping matches")
    check("ABCDEF", "XYZ", "no match")
    check("ABC", "ABC", "whole string")
    check("ABC", "ABCD", "pattern longer than text")
    check("", "A", "empty text")
    print("  basic cases OK")


def test_protein_alphabet():
    """20 amino acids — the real UniProt case."""
    aa = "ACDEFGHIKLMNPQRSTVWY"
    random.seed(42)
    text = "".join(random.choice(aa) for _ in range(20000))

    for _ in range(20):                     # patterns that DO exist
        start = random.randint(0, len(text) - 9)
        check(text, text[start:start + 9], "embedded 9mer")

    for _ in range(20):                     # patterns that almost certainly don't
        check(text, "".join(random.choice(aa) for _ in range(12)), "random 12mer")

    print("  protein alphabet (20 chars) OK")


def test_dna_alphabet():
    """4 characters — the hardest case for the bad character heuristic."""
    random.seed(7)
    text = "".join(random.choice("ACGT") for _ in range(20000))
    for _ in range(20):
        start = random.randint(0, len(text) - 15)
        check(text, text[start:start + 15], "embedded 15mer")
    for _ in range(10):
        check(text, "".join(random.choice("ACGT") for _ in range(25)), "random 25mer")
    print("  DNA alphabet (4 chars) OK")


def test_pathological():
    """Repetitive text — worst case for naive and Boyer-Moore."""
    check("A" * 500, "A" * 50, "all-A repetition")
    check("AB" * 250, "ABAB" * 5, "period-2 repetition")
    check("A" * 300 + "B", "A" * 50 + "B", "repetition with terminal mismatch")
    print("  pathological cases OK")


def test_find_first():
    """find_all=False must return only the first match."""
    assert kmp_search("AAAA", "AA", find_all=False) == [0]
    assert boyer_moore_search("AAAA", "AA", find_all=False) == [0]
    assert len(kmp_search("AAAA", "AA", find_all=True)) == 3
    print("  find-first semantics OK")


if __name__ == "__main__":
    print("Running string matching tests...\n")
    test_basic()
    test_protein_alphabet()
    test_dna_alphabet()
    test_pathological()
    test_find_first()
    print("\nAll tests passed.")