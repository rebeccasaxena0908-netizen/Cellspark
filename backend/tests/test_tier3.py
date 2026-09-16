"""
Tier 3 verification.

The critical property: optimisation must never change the encoded protein.
Everything else is a performance metric; this one is correctness.
"""
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.tier3.optimise import (
    design_mrna, translate, calculate_cai, optimise_codons,
    deplete_uridine, naive_encode, CODON_USAGE
)

AA = "ACDEFGHIKLMNPQRSTVWY"


def test_protein_preserved():
    """The whole approach depends on this. Test it hard."""
    random.seed(42)
    for _ in range(200):
        pep = "".join(random.choice(AA) for _ in range(random.randint(8, 40)))
        naive = "AUG" + naive_encode(pep) + "UAA"
        out = deplete_uridine(optimise_codons(naive))
        assert translate(naive) == translate(out), f"protein changed for {pep}"
    print("  protein preserved across 200 random peptides OK")


def test_cai_improves():
    random.seed(7)
    improved = 0
    for _ in range(50):
        pep = "".join(random.choice(AA) for _ in range(20))
        r = design_mrna(pep)
        if r["after"]["cai"] > r["before"]["cai"]:
            improved += 1
    assert improved >= 48, f"CAI improved in only {improved}/50"
    print(f"  CAI improved in {improved}/50 sequences OK")


def test_uracil_reduced():
    random.seed(11)
    reduced = 0
    for _ in range(50):
        pep = "".join(random.choice(AA) for _ in range(20))
        r = design_mrna(pep)
        if r["after"]["uracil"] <= r["before"]["uracil"]:
            reduced += 1
    assert reduced >= 45, f"uracil reduced in only {reduced}/50"
    print(f"  uracil reduced or held in {reduced}/50 sequences OK")


def test_cai_bounds():
    """CAI must sit in (0, 1]. A fully optimised sequence should hit 1.0."""
    pep = "MKVLAAGIVGLNLQ"
    naive = "AUG" + naive_encode(pep) + "UAA"
    best = optimise_codons(naive)
    c_naive, c_best = calculate_cai(naive), calculate_cai(best)
    assert 0 < c_naive <= 1, c_naive
    assert abs(c_best - 1.0) < 1e-6, f"fully optimised CAI should be 1.0, got {c_best}"
    print(f"  CAI bounds OK (naive {c_naive} -> optimised {c_best})")


def test_construct_assembly():
    r = design_mrna("SIINFEKLM", gene="TP53", change="p.R248W")
    c = r["components"]
    expected = c["utr5"] + c["cds"] + c["utr3"] + c["polyA"]
    assert len(r["full_construct"]) == expected
    assert r["full_construct"].endswith("A" * 120)
    assert r["protein_unchanged"]
    print(f"  construct assembled: {expected} nt total OK")


def demo():
    r = design_mrna("KMVWSAWGI", gene="PIK3CA", change="p.V151I")
    print("\n  Worked example — KMVWSAWGI (PIK3CA p.V151I)")
    print(f"    protein encoded : {r['protein']}")
    print(f"    protein unchanged: {r['protein_unchanged']}")
    print(f"    CAI   {r['before']['cai']} -> {r['after']['cai']}  "
          f"(+{r['improvement']['cai_percent']}%)")
    print(f"    uracil {r['before']['uracil']}% -> {r['after']['uracil']}%")
    print(f"    coding sequence : {r['coding_sequence']}")
    print(f"    full construct  : {len(r['full_construct'])} nt")


if __name__ == "__main__":
    print("Running Tier 3 tests...\n")
    test_protein_preserved()
    test_cai_improves()
    test_uracil_reduced()
    test_cai_bounds()
    test_construct_assembly()
    demo()
    print("\nAll tests passed.")
    