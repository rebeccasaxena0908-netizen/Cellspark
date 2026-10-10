/**
 * Sequence alphabets and the target quality metric.
 *
 * Data and pure functions only — kept out of the component file so React Fast
 * Refresh can do its job, and so these can be unit-tested without rendering.
 */

/** The 20 standard amino acids, grouped by the property that matters here. */
export const AMINO_GROUPS = [
  {
    name: "Hydrophobic",
    gloss: "Repel water, so they tend to face inward, away from the watery surroundings.",
    residues: [
      ["A", "Ala", "Alanine"],
      ["V", "Val", "Valine"],
      ["L", "Leu", "Leucine"],
      ["I", "Ile", "Isoleucine"],
      ["M", "Met", "Methionine"],
      ["F", "Phe", "Phenylalanine"],
      ["W", "Trp", "Tryptophan"],
      ["P", "Pro", "Proline"],
      ["G", "Gly", "Glycine"],
    ],
  },
  {
    name: "Polar",
    gloss: "Mix with water but carry no overall charge. Often sit on the surface.",
    residues: [
      ["S", "Ser", "Serine"],
      ["T", "Thr", "Threonine"],
      ["C", "Cys", "Cysteine"],
      ["Y", "Tyr", "Tyrosine"],
      ["N", "Asn", "Asparagine"],
      ["Q", "Gln", "Glutamine"],
    ],
  },
  {
    name: "Acidic",
    gloss: "Carry a negative charge, so they attract anything positively charged.",
    residues: [
      ["D", "Asp", "Aspartic acid"],
      ["E", "Glu", "Glutamic acid"],
    ],
  },
  {
    name: "Basic",
    gloss: "Carry a positive charge, so they attract anything negatively charged.",
    residues: [
      ["K", "Lys", "Lysine"],
      ["R", "Arg", "Arginine"],
      ["H", "His", "Histidine"],
    ],
  },
];

/** letter -> { code, name, group }, built once from the groups above. */
export const AMINO_ACIDS = Object.fromEntries(
  AMINO_GROUPS.flatMap((g) =>
    g.residues.map(([letter, code, name]) => [letter, { code, name, group: g.name }])
  )
);

export const RNA_BASES = {
  A: { code: "A", name: "Adenine", group: "RNA base" },
  U: { code: "U", name: "Uracil", group: "RNA base" },
  G: { code: "G", name: "Guanine", group: "RNA base" },
  C: { code: "C", name: "Cytosine", group: "RNA base" },
};

/** Human-readable name for one letter, used as the title text. */
export function describe(letter, kind) {
  const table = kind === "rna" ? RNA_BASES : AMINO_ACIDS;
  const hit = table[letter?.toUpperCase?.()];
  if (!hit) return letter;
  return kind === "rna"
    ? `${letter} — ${hit.name}`
    : `${letter} — ${hit.code}, ${hit.name} (${hit.group.toLowerCase()})`;
}


/**
 * How much the mutation improved binding, as wild-type IC50 over mutant IC50.
 *
 * The backend supplies this on real targets; the simulated set does not, so
 * fall back to computing it from the two IC50s that are always present.
 * Returns null when neither is available, so callers can render a dash rather
 * than NaN.
 */
export function agretopicityOf(t) {
  if (typeof t?.agretopicity === "number") return t.agretopicity;
  if (t?.ic50 > 0 && typeof t?.wtIc50 === "number") return t.wtIc50 / t.ic50;
  return null;
}
