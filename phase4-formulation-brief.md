# Tier 5 — Formulation and delivery worksheet

Takes the optimised mRNA construct from Tier 3 and works out what it would
take to physically formulate it as a lipid nanoparticle: molecular weight,
lipid masses at a given nitrogen-to-phosphate ratio, a dose at an assumed
loading, and microfluidic mixing parameters.

Branch: continue on `feature/auth-db`, or a new `feature/formulation`.

---

# The rule this module is built around

**Every number on the output carries its provenance, and the UI shows it.**
Three classes:

| Class | What it is | Examples |
|---|---|---|
| `computed` | Derived from this run's own sequence. Reproducible from the data. | Molecular weight, base counts, phosphate moles, lipid masses |
| `constant` | Taken from a published formulation. Cited. | Molar ratios, lipid molecular weights, flow parameters |
| `assumption` | Supplied by the user. An input, not a result. | µg/kg loading, patient weight, concentration, N/P ratio, schedule |

This matters because the obvious version of this feature produces a sheet
reading "Calculated Dose: 35.0 µg — Route: Intramuscular" which looks like
clinical guidance. It is not. It is `weight × an assumed µg/kg`, and no
CellSpark output has been through any trial, animal study or toxicology
screen.

So:

- **The dose per kg is an editable input field, shown in the inputs section**,
  never printed as a recommendation. Default 0.5 µg/kg, labelled as an
  assumption with no clinical basis in this system.
- **The schedule and route are selectable inputs**, defaulting to values
  copied from published trial designs, with the source named. They are not
  derived from anything.
- **The sheet's title is "Formulation Worksheet", not "Clinical Spec Sheet"**,
  and it carries a standing line: *computational worksheet for research and
  manufacturing planning; not a clinical protocol and not validated for human
  use.*
- The copilot's existing answering rules already forbid dosing advice. Do not
  weaken them. The worksheet shows arithmetic; the copilot still refuses to
  recommend.

---

# Read first

- `backend/schema_formulation.sql` — apply as root before coding
- `backend/app/tier3/optimise.py` — where the construct comes from
- `backend/app/records.py`, `models.py`, `main.py`
- `backend/schema.sql` — match its conventions
- `frontend/src/components/MrnaPanel.jsx`, `ResultsStep.jsx`, `SequenceLegend.jsx`

---

# Backend

## `backend/app/tier5/constants.py`

Published values, each with a `citation` field. **Verify every number against
its source before committing** — do not take these on trust from this brief.

Two presets:

```
sm102_moderna   SM-102 : DSPC : cholesterol : PEG2000-DMG
                50 : 10 : 38.5 : 1.5  molar
alc0315_pfizer  ALC-0315 : DSPC : cholesterol : ALC-0159
                46.3 : 9.4 : 42.7 : 1.6  molar
```

These are different systems with different ratios — do not present them as
interchangeable options sharing one ratio.

Lipid molecular weights to verify: SM-102 710.18, ALC-0315 766.3, DSPC
790.15, cholesterol 386.65, PEG2000-DMG 2509.2, ALC-0159 2425.

RNA residue masses (standard ssRNA calculation): A 329.21, U 306.17,
C 305.18, G 345.21, plus 159.0 for the 5′ triphosphate.

Microfluidic defaults: aqueous:organic 3:1, total flow 12 mL/min, staggered
herringbone mixer, RNA in 50 mM citrate pH 4.0, lipids in ethanol.

Target particle size: record as the **typical range for the formulation**
(roughly 80–100 nm), described as what this lipid system produces. Do **not**
claim that size directs the dose to lymph nodes — biodistribution is governed
far more by the ionizable lipid's pKa and surface chemistry, and an
intramuscular LNP largely remains near the injection site with partial
lymphatic drainage. Overstating this is the kind of claim a biology examiner
will challenge.

## `backend/app/tier5/formulate.py`

```python
def formulate(sequence: str, patient_weight_kg: float, dose_per_kg_mcg: float,
              concentration_mcg_ml: float, np_ratio: float,
              preset_key: str) -> dict
```

The chain, in order:

1. Count A, U, G, C in the construct. Reject any character outside AUGC with
   a clear error — a DNA sequence containing T must not silently score.
2. `MW = ΣA·329.21 + ΣU·306.17 + ΣC·305.18 + ΣG·345.21 + 159.0`
3. `dose_µg = weight_kg × dose_per_kg_µg`
4. `moles_mRNA = (dose_µg × 1e-6) / MW`
5. `moles_phosphate = moles_mRNA × nucleotide_length` — one phosphate per
   nucleotide
6. `moles_ionizable = moles_phosphate × np_ratio`
7. `moles_total_lipid = moles_ionizable / (ionizable_molar_pct / 100)`
8. For each lipid: `moles = moles_total × pct/100`, `mass_mg = moles × MW × 1000`
9. `injection_volume_ml = dose_µg / concentration_µg_per_ml`

Return every value tagged with its provenance class, so the API response
carries it rather than the UI having to know which is which.

## Database

Apply `schema_formulation.sql` as root. Two tables: `formulation_spec` and
`formulation_lipid`. Map them in `models.py`; no `create_all`.

The lipid molar percentages and molecular weights are **snapshot** into
`formulation_lipid` at calculation time rather than referenced live, so a
later correction to a published constant cannot silently change a saved
worksheet.

## API

| Method | Path | |
|---|---|---|
| POST | `/api/runs/{run_id}/formulation` | compute and save; returns the full worksheet |
| GET | `/api/runs/{run_id}/formulations` | saved worksheets for that run |
| GET | `/api/formulations/{id}/export.json` | machine-readable protocol |

Ownership enforced as everywhere else — another researcher's `run_id`
returns 404. A run with no Tier 3 construct returns 409 with a clear reason.

---

# Frontend

## `FormulationPanel.jsx`

Appears in the results view beneath the mRNA panel, collapsed until opened.

**Inputs section, clearly labelled as inputs:** patient weight, µg/kg
(default 0.5), concentration (default 100 µg/mL), N/P ratio (default 6.0),
preset, route, schedule. Each shows its default's origin. Recalculates on
change.

**Worksheet section**, with a visible provenance marker on every value —
reuse the badge pattern from the copilot's provider badge:

- Sequence: length, base composition, molecular weight → `computed`
- Lipid table: name, molar %, µmol, mg per lipid, total → `computed` from
  `constant` ratios, with the citation shown
- Dose, volume → `computed` from `assumption` inputs
- Mixing parameters, size range → `constant`, cited

**Export:** JSON, and a print-friendly view (`window.print()` with a print
stylesheet — no PDF library, no new dependency). Both carry the
not-for-clinical-use line and the input values used.

Match existing tokens and `.cs-*` utilities. Keyboard operable, visible focus
rings, no horizontal overflow at 390px.

---

# Constraints

- Do not change `schema.sql` or the nine original tables.
- Do not change Tiers 1–4, the retriever, or `platform_facts.py` — except to
  add a short Tier 5 section describing this module and restating that it
  does not produce clinical recommendations.
- No new dependencies.
- All 93 existing tests must pass.

# Tests

Use this worked example as a fixture — it has been verified independently:

```
sequence  AUGAAGCUGGUGGUGGUGGGCGCCGACGGCGUGUGA   (36 nt)
MW        11,993.1 Da
weight 70 kg, 0.5 µg/kg, N/P 6.0, sm102_moderna preset
dose      35.0 µg
mRNA      2.9183 nmol
phosphate 0.1051 µmol
SM-102    0.6304 µmol   0.4477 mg
DSPC      0.1261 µmol   0.0996 mg
Cholest.  0.4854 µmol   0.1877 mg
PEG2000   0.0189 µmol   0.0475 mg
total                   0.7824 mg
```

Also assert:

- Lipid µmol are in the preset's molar ratio to within rounding.
- Doubling the dose doubles every lipid mass.
- A sequence containing `T` is rejected, not scored.
- An empty or whitespace sequence is rejected.
- Molar percentages of a preset sum to 100.
- Every returned value has a provenance class; none is missing.
- Saving writes one `formulation_spec` and exactly four `formulation_lipid`
  rows.
- Researcher B gets 404 for researcher A's run.
- A run with no Tier 3 result returns 409.

# Verify

1. Run the pipeline, open the formulation panel, compute with defaults.
2. Change patient weight; confirm dose and all four lipid masses scale
   linearly and the molar ratio is unchanged.
3. Switch preset; confirm the lipid names, ratios and citation all change.
4. Export JSON; confirm it contains the inputs used, not just the outputs.
5. Print preview: the worksheet is legible and carries the not-for-clinical-
   use line.
6. Confirm the four rows in `formulation_lipid` and one in
   `formulation_spec`.
7. 390px, no horizontal scroll.

Report what changed per file, which constants you verified and against what
sources, and anything the brief did not cover.
