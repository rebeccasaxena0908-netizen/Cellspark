export const HLA_OPTIONS = [
  "HLA-A*02:01", "HLA-A*01:01", "HLA-A*03:01", "HLA-A*24:02",
  "HLA-B*07:02", "HLA-B*08:01", "HLA-B*44:02", "HLA-C*07:01",
];

export const TIERS = [
  { id: 1, name: "Genomic search",    detail: "Reading variants, screening against healthy proteome" },
  { id: 2, name: "Target selection",  detail: "Scoring peptide–HLA binding with MHCflurry" },
  { id: 3, name: "mRNA optimisation", detail: "Codon optimisation and uridine depletion" },
  { id: 4, name: "Clinical summary",  detail: "Drafting the report from retrieved literature" },
];