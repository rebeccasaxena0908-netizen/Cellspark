"""
Algorithm benchmark. Produces the comparison table for the report.

This is the empirical justification for implementing the algorithms by hand
rather than calling a library function.
"""
import os
import random
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.tier1.proteome import ProteomeIndex
from app.tier1.string_match import kmp_search, boyer_moore_search, naive_search

AA = "ACDEFGHIKLMNPQRSTVWY"


def build_proteome(path, n=2000, seed=1):
    random.seed(seed)
    with open(path, "w") as fh:
        for i in range(n):
            seq = "".join(random.choice(AA) for _ in range(random.randint(200, 800)))
            fh.write(f">sp|BM{i:05d}|BM{i}_HUMAN benchmark protein\n{seq}\n")


def run(index, peptides, label):
    algos = {
        "Knuth-Morris-Pratt": kmp_search,
        "Boyer-Moore": boyer_moore_search,
        "Naive baseline": naive_search,
    }
    print(f"\n{label}")
    print(f"  {'Algorithm':<22} {'Total (s)':>10} {'ms/peptide':>12}")
    print(f"  {'-'*22} {'-'*10} {'-'*12}")

    results = {}
    for name, fn in algos.items():
        t0 = time.perf_counter()
        for p in peptides:
            fn(index.text, p, find_all=False)
        el = time.perf_counter() - t0
        results[name] = el
        print(f"  {name:<22} {el:>10.4f} {1000*el/len(peptides):>12.3f}")

    # Python's built-in 'in' — CPython's two-way algorithm, written in C.
    # Included for honesty: it will crush our pure-Python code. That compares
    # IMPLEMENTATIONS, not algorithms, and saying so is stronger than
    # quietly omitting the row.
    t0 = time.perf_counter()
    for p in peptides:
        p in index.text
    el = time.perf_counter() - t0
    print(f"  {'Python built-in (C)':<22} {el:>10.4f} {1000*el/len(peptides):>12.3f}")

    nv = results["Naive baseline"]
    print(f"\n  KMP vs naive         : {nv/results['Knuth-Morris-Pratt']:.2f}x")
    print(f"  Boyer-Moore vs naive : {nv/results['Boyer-Moore']:.2f}x")
    faster = min(("Knuth-Morris-Pratt", "Boyer-Moore"), key=lambda k: results[k])
    print(f"  Faster of the two    : {faster}")
    return results


def main():
    with tempfile.TemporaryDirectory() as tmp:
        fa = os.path.join(tmp, "bm.fasta")
        print("Building benchmark proteome...")
        build_proteome(fa)
        index = ProteomeIndex(fa)
        print(f"  {index}")

        random.seed(99)
        peps9 = ["".join(random.choice(AA) for _ in range(9)) for _ in range(150)]
        run(index, peps9, "PROTEIN ALPHABET (20 chars), 9-mers, 150 peptides")

        peps20 = ["".join(random.choice(AA) for _ in range(20)) for _ in range(150)]
        run(index, peps20, "PROTEIN ALPHABET (20 chars), 20-mers, 150 peptides")

        # DNA: 4-char alphabet is the hard case for the bad character heuristic
        dna_text = "".join(random.choice("ACGT") for _ in range(400000))
        class Fake: pass
        fake = Fake(); fake.text = dna_text
        peps_dna = ["".join(random.choice("ACGT") for _ in range(15)) for _ in range(150)]
        run(fake, peps_dna, "DNA ALPHABET (4 chars), 15-mers, 150 peptides")


if __name__ == "__main__":
    main()