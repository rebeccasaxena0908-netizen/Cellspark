"""
Tier 4 — Run context for the prompt.

Flattens a pipeline result into a compact text block the model can read.

WHY NOT JUST SEND THE JSON:
A full result carries the entire candidate peptide list — hundreds of entries
on a real upload — and the complete mRNA construct, which runs to thousands of
nucleotides. Both would dominate the context window while adding nothing: the
model is being asked about the ranked targets and the design metrics, not
asked to read every 9-mer the window slider produced.

So this is a deliberate projection. Every number a question is likely to touch
is here; the two unbounded fields are excluded by design, and the whole block
is hard-capped so one unusual run cannot crowd out the retrieved literature
further down the prompt.
"""

from typing import Any, Dict, List, Optional

# ~1500 tokens. English runs about 4 characters per token, and this block is
# number-dense, so the real token count sits under the cap rather than over it.
MAX_CHARS = 6000

CONSTRUCT_PREVIEW_NT = 90
TOP_TARGETS = 10


def _band(ic50: Optional[float]) -> str:
    """
    Binding band from IC50. Lower is tighter — the thresholds run downward.

    Recomputed here rather than trusting the stored label, so the band always
    agrees with the number printed next to it.
    """
    if ic50 is None:
        return "unknown"
    try:
        v = float(ic50)
    except (TypeError, ValueError):
        return "unknown"
    if v < 50:
        return "strong binder"
    if v < 500:
        return "weak binder"
    return "below threshold"


def _fmt(value: Any, dash: str = "not reported") -> str:
    """Render a value for the prompt, making absence explicit."""
    if value is None or value == "":
        return dash
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def build_run_context(result: Dict[str, Any]) -> str:
    """
    Build the RUN CONTEXT block for the LLM prompt.

    Tolerant of partial results: a run where Tier 2 failed still produces a
    usable block, because each tier is read defensively and missing sections
    are stated as missing. The model needs to know a tier did not run — that
    is itself an answer to "why is there no construct?".
    """
    result = result or {}
    t1 = result.get("tier1") or {}
    t2 = result.get("tier2") or {}
    t3 = result.get("tier3") or {}

    lines: List[str] = ["=== RUN CONTEXT (this run's own numbers) ==="]

    # ---------------------------------------------------------------- inputs
    alleles = result.get("alleles") or []
    lines += [
        "",
        "INPUT",
        f"  source: {_fmt(result.get('source') or t1.get('source'))}"
        " (demo = synthetic dataset, upload = user's own file)",
        f"  file name: {_fmt(result.get('file_name'))}",
        f"  HLA alleles: {', '.join(alleles) if alleles else 'not reported'}",
        f"  string-matching algorithm: {_fmt(t1.get('algorithm'))}",
    ]

    # ------------------------------------------------------- tier 1
    lines += ["", "TIER 1 — candidate generation and tolerance screening"]
    if not t1:
        lines.append("  did not run — no Tier 1 section in the result")
    else:
        proteome = t1.get("proteome") or {}
        lines += [
            f"  reference proteome: {_fmt(proteome.get('proteins'))} proteins, "
            f"{_fmt(proteome.get('residues'))} residues "
            f"({_fmt(proteome.get('reference'))})",
            f"  screening stage: {_fmt(t1.get('screening_stage'))}",
            "  stats:",
        ]
        stats = t1.get("stats") or {}
        if stats:
            # The full stats block, verbatim — the brief's point is that the
            # model should see every count, including the awkward ones.
            for key, value in stats.items():
                lines.append(f"    {key}: {_fmt(value)}")
        else:
            lines.append("    not reported")

        if t1.get("warning"):
            lines.append(f"  WARNING from this run: {t1['warning']}")

    # ------------------------------------------------------- tier 2
    lines += ["", "TIER 2 — HLA binding prediction"]
    targets = t2.get("targets") or []
    if not t2.get("implemented", bool(t2)):
        lines.append(
            f"  did not run: {_fmt(t2.get('error') or t2.get('note'), 'no reason reported')}"
        )
    else:
        lines.append(f"  predictor: {_fmt(t2.get('predictor'))}")
        t2stats = t2.get("stats") or {}
        if t2stats:
            lines.append(
                "  scored: {scored}, strong (<50 nM): {strong}, "
                "weak (<500 nM): {weak}, below threshold: {below}, "
                "best IC50: {best}".format(
                    scored=_fmt(t2stats.get("scored")),
                    strong=_fmt(t2stats.get("strong_binders")),
                    weak=_fmt(t2stats.get("weak_binders")),
                    below=_fmt(t2stats.get("below_threshold")),
                    best=_fmt(t2stats.get("best_ic50")),
                )
            )
        if t2.get("rejected_self") is not None:
            lines.append(
                f"  rejected from the shortlist as self-matching: "
                f"{_fmt(t2.get('rejected_self'))} of "
                f"{_fmt(t2.get('screened_shortlist'))} screened"
            )

    if targets:
        lines += [
            "",
            f"  TOP {min(len(targets), TOP_TARGETS)} TARGETS "
            "(IC50 in nM, lower binds tighter; agretopicity = wild-type IC50 / "
            "mutant IC50, higher means the mutation created the epitope)",
        ]
        for t in targets[:TOP_TARGETS]:
            lines.append(
                "    #{rank} {peptide} | {gene} {change} | {allele} | "
                "IC50 {ic50} nM | wild-type {wt_pep} {wt} nM | "
                "agretopicity {agreto} | {band}".format(
                    rank=_fmt(t.get("rank"), "?"),
                    peptide=_fmt(t.get("peptide"), "?"),
                    gene=_fmt(t.get("gene"), "?"),
                    change=_fmt(t.get("change"), "?"),
                    allele=_fmt(t.get("allele"), "?"),
                    ic50=_fmt(t.get("ic50"), "?"),
                    wt_pep=_fmt(t.get("wildtype"), "?"),
                    wt=_fmt(t.get("wtIc50"), "?"),
                    agreto=_fmt(t.get("agretopicity"), "?"),
                    band=_band(t.get("ic50")),
                )
            )
    elif t2.get("implemented"):
        lines.append("  no targets survived to the shortlist")

    # ------------------------------------------------------- tier 3
    lines += ["", "TIER 3 — mRNA construct design (for the top-ranked target only)"]
    if not t3.get("implemented", bool(t3)):
        lines.append(
            f"  did not run: {_fmt(t3.get('error') or t3.get('note'), 'no reason reported')}"
        )
    else:
        before = t3.get("before") or {}
        after = t3.get("after") or {}
        target = t3.get("target") or {}
        lines += [
            f"  designed for: {_fmt(target.get('peptide'))} "
            f"({_fmt(target.get('gene'))} {_fmt(target.get('change'))})",
            f"  CAI: {_fmt(before.get('cai'))} before -> {_fmt(after.get('cai'))} after "
            "(1.0 = every codon is the most-used option for its amino acid)",
            f"  uracil: {_fmt(before.get('uracil'))}% before -> "
            f"{_fmt(after.get('uracil'))}% after",
            f"  GC content: {_fmt(after.get('gc'))}%",
            f"  coding sequence length: {_fmt(after.get('length'))} nt",
            f"  protein unchanged after optimisation: "
            f"{_fmt(t3.get('protein_unchanged'))}"
            " (must be yes — synonymous substitutions only; no means a bug)",
        ]

        construct = t3.get("full_construct") or ""
        if construct:
            # Preview only. The full construct is thousands of nucleotides and
            # the model cannot do anything useful with the tail of it.
            lines += [
                f"  full construct: {len(construct)} nt total "
                f"(5' UTR + CDS + 3' UTR + poly-A)",
                f"  first {CONSTRUCT_PREVIEW_NT} nt: "
                f"{construct[:CONSTRUCT_PREVIEW_NT]}...",
                "  (the remaining nucleotides are not included in this context)",
            ]

    lines += [
        "",
        "NOT INCLUDED: the full candidate peptide list and the full construct "
        "sequence. If a question needs either, say it is not in the context "
        "rather than guessing at it.",
    ]

    text = "\n".join(lines)

    if len(text) > MAX_CHARS:
        marker = "\n\n[RUN CONTEXT TRUNCATED — the rest was too long to include]"
        text = text[: MAX_CHARS - len(marker)].rstrip() + marker

    return text
