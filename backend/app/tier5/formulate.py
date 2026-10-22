"""
Tier 5 — the formulation worksheet calculation.

WHAT THIS IS
Arithmetic. Given a sequence and a set of inputs, it works out how much of
each lipid you would weigh out to formulate that much mRNA at that N/P ratio.
Nothing here is a recommendation and nothing here is predictive: there is no
model, no fit and no trial data anywhere in this file. Every output is either
a sum over the sequence, a published ratio, or a number the user typed.

WHY EVERY VALUE IS WRAPPED
The obvious version of this feature returns a flat dict of numbers, and the
sheet that renders it reads like a clinical specification — "Dose: 35.0 ug,
Route: Intramuscular" — when in fact the dose is body weight multiplied by a
figure the user chose with no clinical basis. So no bare numbers leave this
module. Each one is wrapped by `computed`, `constant` or `assumption`, which
attach the provenance class, the unit and, for the latter two, the citation or
the statement of what the input actually rests on. The API passes those
envelopes through unchanged and the UI renders the class as a badge, so the
distinction cannot be lost in transit or quietly dropped by a caller that
only wanted the numbers.

THE CHAIN
    MW            = sum of residue masses + end correction
    dose_ug       = weight_kg * ug/kg                  (both assumptions)
    moles_mRNA    = dose_g / MW
    moles_PO4     = moles_mRNA * nucleotide_length     (one phosphate per nt)
    moles_ionizable = moles_PO4 * N/P
    moles_total   = moles_ionizable / (ionizable mol% / 100)
    per lipid     = moles_total * mol%/100, mass = moles * MW
    volume_ml     = dose_ug / concentration_ug_per_ml

The N/P ratio is defined on the ionizable lipid's nitrogen against the RNA's
phosphate, which is why the total lipid is reached THROUGH the ionizable
lipid's molar percentage rather than the other way round.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    CONCENTRATION_BASIS,
    DEFAULT_PRESET,
    DOSE_PER_KG_BASIS,
    MIXING,
    NOT_FOR_CLINICAL_USE,
    NP_RATIO_CITATION,
    PRESETS,
    RNA_END_CORRECTION_DA,
    RNA_MASS_CITATION,
    RNA_RESIDUE_MASS_DA,
    ROUTE_BASIS,
    ROUTE_OPTIONS,
    SCHEDULE_BASIS,
    SCHEDULE_OPTIONS,
    VALID_BASES,
    WEIGHT_BASIS,
    Preset,
)

# Provenance classes. The strings are part of the API contract and the UI
# switches on them, so they live here as names rather than being typed out.
COMPUTED = "computed"
CONSTANT = "constant"
ASSUMPTION = "assumption"

PROVENANCE_CLASSES = (COMPUTED, CONSTANT, ASSUMPTION)


class FormulationError(ValueError):
    """
    A bad input the caller can fix and should be told about precisely.

    Separate from ValueError so the route can map it to a 400 with the
    message shown to the user, while a genuine bug still surfaces as a 500.
    """


# ---------------------------------------------------------------- envelopes
def computed(value: Any, unit: str = "", label: str = "", note: str = "") -> Dict[str, Any]:
    """A value derived from this run's own sequence. Reproducible from it."""
    out = {"value": value, "provenance": COMPUTED, "unit": unit, "label": label}
    if note:
        out["note"] = note
    return out


def constant(value: Any, citation: str, unit: str = "", label: str = "",
             note: str = "") -> Dict[str, Any]:
    """A published value. The citation is required, not optional."""
    out = {
        "value": value,
        "provenance": CONSTANT,
        "unit": unit,
        "label": label,
        "citation": citation,
    }
    if note:
        out["note"] = note
    return out


def assumption(value: Any, basis: str, unit: str = "", label: str = "") -> Dict[str, Any]:
    """
    A value the user supplied.

    `basis` says what the default rests on — which for the dosing inputs is
    nothing clinical, and says so. It is required for the same reason the
    citation is required on a constant.
    """
    return {
        "value": value,
        "provenance": ASSUMPTION,
        "unit": unit,
        "label": label,
        "basis": basis,
    }


def walk_values(node: Any):
    """
    Yield every provenance envelope in a worksheet, at any depth.

    The tests use this to assert that nothing escapes unclassified, and the
    route uses it for the same check before saving. An envelope is any dict
    carrying a "value" key.
    """
    if isinstance(node, dict):
        if "value" in node:
            yield node
            return
        for child in node.values():
            yield from walk_values(child)
    elif isinstance(node, (list, tuple)):
        for child in node:
            yield from walk_values(child)


# ---------------------------------------------------------------- sequence
def clean_sequence(sequence: str) -> str:
    """
    Strip whitespace and upper-case, then insist on AUGC.

    Internal whitespace goes because a sequence pasted out of a FASTA file or
    off a web page arrives wrapped across lines, and rejecting that would be
    pedantry. Every other character is fatal:

    A DNA sequence must not silently score. T is not U, and a construct
    containing T has either not been transcribed or has come from the wrong
    column of a file; either way its base counts and therefore its entire
    lipid table would be wrong. Returning a number for it would be worse than
    refusing, because the number would look fine.
    """
    if sequence is None:
        raise FormulationError("No sequence was supplied.")

    cleaned = "".join(sequence.split()).upper()
    if not cleaned:
        raise FormulationError(
            "The sequence is empty. Run the Tier 3 optimiser first, or paste "
            "an RNA sequence."
        )

    bad = sorted({c for c in cleaned if c not in VALID_BASES})
    if bad:
        shown = ", ".join(repr(c) for c in bad[:6])
        hint = ""
        if "T" in bad:
            hint = (
                " This looks like DNA: RNA uses U where DNA uses T. Transcribe "
                "it before formulating, because the base counts and every "
                "lipid mass below depend on which it is."
            )
        raise FormulationError(
            f"The sequence contains {len(bad)} character(s) that are not A, U, "
            f"G or C: {shown}.{hint}"
        )
    return cleaned


def molecular_weight(cleaned: str) -> float:
    """
    Molecular weight of a single-stranded RNA, in daltons.

    Sum of published residue masses plus the table's end correction. See
    RNA_END_CORRECTION_DA on what that term assumes about the 5' end.
    """
    return sum(RNA_RESIDUE_MASS_DA[base] for base in cleaned) + RNA_END_CORRECTION_DA


# ---------------------------------------------------------------- the worksheet
def _positive(value: Any, name: str, unit: str, limit: float) -> float:
    """One numeric input, checked. Rejects NaN by the comparison failing."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise FormulationError(f"{name} must be a number.") from None
    if not number > 0:
        raise FormulationError(f"{name} must be greater than zero.")
    if not number <= limit:
        raise FormulationError(f"{name} must be {limit:g} {unit} or less.")
    return number


def formulate(sequence: str,
              patient_weight_kg: float,
              dose_per_kg_mcg: float,
              concentration_mcg_ml: float,
              np_ratio: float,
              preset_key: str = DEFAULT_PRESET,
              route: Optional[str] = None,
              schedule: Optional[str] = None) -> Dict[str, Any]:
    """
    Work one formulation and return it fully provenance-tagged.

    Raises FormulationError on any bad input. Nothing is written to the
    database here; persistence is the caller's business.
    """
    preset: Optional[Preset] = PRESETS.get(preset_key)
    if preset is None:
        known = ", ".join(sorted(PRESETS))
        raise FormulationError(
            f"Unknown formulation preset {preset_key!r}. Available: {known}."
        )

    cleaned = clean_sequence(sequence)

    # The DECIMAL widths in schema_formulation.sql are the real ceilings here;
    # these limits keep an absurd input from reaching the database and being
    # rejected there with a driver error instead of a readable message.
    weight_kg = _positive(patient_weight_kg, "Body weight", "kg", 999.99)
    dose_per_kg = _positive(dose_per_kg_mcg, "Dose per kg", "ug/kg", 999.999)
    concentration = _positive(concentration_mcg_ml, "Concentration", "ug/mL", 999999.99)
    np_value = _positive(np_ratio, "N/P ratio", "", 999.99)

    route_value = route or ROUTE_OPTIONS[0]
    if route_value not in ROUTE_OPTIONS:
        raise FormulationError(
            f"Unknown route {route_value!r}. Available: {', '.join(ROUTE_OPTIONS)}."
        )
    schedule_value = schedule or SCHEDULE_OPTIONS[0]
    if schedule_value not in SCHEDULE_OPTIONS:
        raise FormulationError(
            f"Unknown schedule {schedule_value!r}. "
            f"Available: {', '.join(SCHEDULE_OPTIONS)}."
        )

    # ---- the sequence itself -------------------------------------------
    length = len(cleaned)
    counts = {base: cleaned.count(base) for base in "AUGC"}
    mw_da = molecular_weight(cleaned)

    # ---- dose and moles ------------------------------------------------
    dose_mcg = weight_kg * dose_per_kg
    moles_mrna = (dose_mcg * 1e-6) / mw_da          # ug -> g, then g / (g/mol)
    moles_phosphate = moles_mrna * length           # one phosphate per nucleotide
    moles_ionizable = moles_phosphate * np_value

    ionizable = preset.ionizable
    moles_total_lipid = moles_ionizable / (ionizable.molar_pct / 100.0)

    injection_volume_ml = dose_mcg / concentration

    # ---- per lipid -----------------------------------------------------
    lipid_rows: List[Dict[str, Any]] = []
    total_mass_mg = 0.0
    for lipid in preset.lipids:
        moles = moles_total_lipid * (lipid.molar_pct / 100.0)
        mass_mg = moles * lipid.molecular_weight_da * 1000.0
        total_mass_mg += mass_mg

        mw_note = lipid.mw_note
        lipid_rows.append({
            "role": lipid.role,
            "name": lipid.name,
            # The ratio and the weight are published; the amounts are ours.
            "molar_pct": constant(
                round(lipid.molar_pct, 2), preset.citation,
                unit="mol%", label="Molar percentage",
            ),
            "molecular_weight_da": constant(
                lipid.molecular_weight_da, lipid.citation,
                unit="Da", label="Molecular weight",
                note=mw_note or (
                    "Computed from the molecular formula "
                    f"{lipid.formula}." if lipid.formula else ""
                ),
            ),
            "micromoles": computed(
                round(moles * 1e6, 6), unit="umol", label="Amount",
            ),
            "mass_mg": computed(
                round(mass_mg, 4), unit="mg", label="Mass to weigh out",
            ),
            "mw_is_nominal": lipid.mw_is_nominal,
            "formula": lipid.formula,
        })

    # ---- assemble ------------------------------------------------------
    worksheet: Dict[str, Any] = {
        "title": "Formulation Worksheet",
        "not_for_clinical_use": NOT_FOR_CLINICAL_USE,
        "preset": {
            "key": preset.key,
            "label": preset.label,
            "citation": preset.citation,
        },

        # Everything the user chose, gathered in one place and labelled as
        # input. The UI renders this section as the form it came from, so a
        # reader cannot mistake any of it for a result.
        "inputs": {
            "patient_weight_kg": assumption(
                round(weight_kg, 2), WEIGHT_BASIS, unit="kg", label="Body weight",
            ),
            "dose_per_kg_mcg": assumption(
                round(dose_per_kg, 3), DOSE_PER_KG_BASIS,
                unit="ug/kg", label="Dose per kg",
            ),
            "concentration_mcg_ml": assumption(
                round(concentration, 2), CONCENTRATION_BASIS,
                unit="ug/mL", label="Formulated concentration",
            ),
            "np_ratio": assumption(
                round(np_value, 2), NP_RATIO_CITATION,
                unit="", label="N/P ratio",
            ),
            "route": assumption(route_value, ROUTE_BASIS, label="Route"),
            "schedule": assumption(schedule_value, SCHEDULE_BASIS, label="Schedule"),
        },

        "sequence": {
            "nucleotide_length": computed(length, unit="nt", label="Length"),
            "count_a": computed(counts["A"], unit="nt", label="Adenine"),
            "count_u": computed(counts["U"], unit="nt", label="Uracil"),
            "count_g": computed(counts["G"], unit="nt", label="Guanine"),
            "count_c": computed(counts["C"], unit="nt", label="Cytosine"),
            "molecular_weight_da": computed(
                round(mw_da, 2), unit="Da", label="Molecular weight",
                note=(
                    "Sum of published residue masses plus a 159.0 Da end "
                    "correction for a 5' triphosphate. A capped, tailed "
                    "therapeutic construct differs by a few hundred daltons "
                    "at the ends; the lipid ratios below are unaffected."
                ),
            ),
            "residue_masses": constant(
                dict(RNA_RESIDUE_MASS_DA), RNA_MASS_CITATION,
                unit="Da", label="Residue masses used",
            ),
        },

        "amounts": {
            "dose_mcg": computed(
                round(dose_mcg, 3), unit="ug", label="mRNA per dose",
                note=(
                    "Body weight multiplied by the dose-per-kg input above. "
                    "Not a recommended dose - it is whatever those two "
                    "numbers make."
                ),
            ),
            "injection_volume_ml": computed(
                round(injection_volume_ml, 3), unit="mL",
                label="Volume at the stated concentration",
            ),
            "mrna_nanomoles": computed(
                round(moles_mrna * 1e9, 6), unit="nmol", label="mRNA",
            ),
            "phosphate_micromoles": computed(
                round(moles_phosphate * 1e6, 6), unit="umol",
                label="RNA phosphate",
                note="One phosphate per nucleotide.",
            ),
            "ionizable_micromoles": computed(
                round(moles_ionizable * 1e6, 6), unit="umol",
                label="Ionizable lipid nitrogen",
                note="RNA phosphate multiplied by the N/P ratio input.",
            ),
            "total_lipid_micromoles": computed(
                round(moles_total_lipid * 1e6, 6), unit="umol",
                label="Total lipid",
            ),
            "total_lipid_mass_mg": computed(
                round(total_mass_mg, 4), unit="mg", label="Total lipid mass",
            ),
        },

        "lipids": lipid_rows,

        "process": {
            key: constant(
                spec["value"], spec["citation"], label=spec["label"],
            )
            for key, spec in MIXING.items()
        },

        "particle_size": {
            "target_size_nm_min": constant(
                preset.target_size_nm[0], preset.size_citation,
                unit="nm", label="Typical diameter, low",
            ),
            "target_size_nm_max": constant(
                preset.target_size_nm[1], preset.size_citation,
                unit="nm", label="Typical diameter, high",
            ),
        },

        "notes": [
            "Every figure is arithmetic on the sequence and the inputs above. "
            "No model, no fit and no trial data is involved.",
            "The lipid masses are what you would weigh out for one dose at "
            "this N/P ratio, before any overage for process losses.",
            "Encapsulation is assumed complete. A real preparation loses "
            "mRNA to incomplete encapsulation, so the delivered amount is "
            "lower than the amount formulated.",
            "The typical particle size is what this lipid system tends to "
            "produce. It is not a prediction for this construct and it says "
            "nothing about where the particle goes in the body.",
        ],
    }

    # A value that reached the response without a provenance class would
    # defeat the point of the module, so this is checked rather than trusted
    # — the same argument as Tier 3 asserting its protein is unchanged.
    for envelope in walk_values(worksheet):
        if envelope.get("provenance") not in PROVENANCE_CLASSES:
            raise AssertionError(
                f"Worksheet value {envelope.get('label') or envelope} has no "
                "provenance class"
            )

    return worksheet


# ---------------------------------------------------------------- export
def _lipid_citation(name: str) -> Optional[str]:
    """The live citation for a lipid name, if it is still one we know."""
    for preset in PRESETS.values():
        for lipid in preset.lipids:
            if lipid.name == name:
                return lipid.citation
    return None


def export_document(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    A saved worksheet as a machine-readable protocol.

    Built from the STORED row, not by recomputing. That is the whole reason
    the molar percentages and molecular weights are snapshot into
    formulation_lipid: an export of a sheet saved last month must show the
    numbers it was actually computed with, even if a published constant has
    been corrected since. Recomputing here would reintroduce exactly the
    silent drift the snapshot exists to prevent.

    The inputs are carried alongside the outputs, so the document says what it
    was given as well as what it worked out. Without them a reader cannot tell
    a 35 ug dose that came from 70 kg at 0.5 ug/kg from any other 35 ug.
    """
    inputs = {
        "patient_weight_kg": assumption(
            row["patient_weight_kg"], WEIGHT_BASIS, unit="kg", label="Body weight"),
        "dose_per_kg_mcg": assumption(
            row["dose_per_kg_mcg"], DOSE_PER_KG_BASIS,
            unit="ug/kg", label="Dose per kg"),
        "concentration_mcg_ml": assumption(
            row["concentration_mcg_ml"], CONCENTRATION_BASIS,
            unit="ug/mL", label="Formulated concentration"),
        "np_ratio": assumption(
            row["np_ratio"], NP_RATIO_CITATION, unit="", label="N/P ratio"),
        "route": assumption(row["route"], ROUTE_BASIS, label="Route"),
        "schedule": assumption(row["schedule_label"], SCHEDULE_BASIS, label="Schedule"),
    }

    lipids = []
    for lipid in row["lipids"]:
        citation = _lipid_citation(lipid["name"])
        lipids.append({
            "role": lipid["role"],
            "name": lipid["name"],
            "molar_pct": constant(
                lipid["molar_pct"], row["preset_citation"],
                unit="mol%", label="Molar percentage",
                note="Snapshot at the time this worksheet was saved.",
            ),
            "molecular_weight_da": constant(
                lipid["molecular_weight_da"],
                citation or "Snapshot value; this lipid is no longer in the "
                            "preset list, so no live citation could be resolved.",
                unit="Da", label="Molecular weight",
                note="Snapshot at the time this worksheet was saved."
                     + ("" if citation else " Citation unresolved."),
            ),
            "micromoles": computed(lipid["micromoles"], unit="umol", label="Amount"),
            "mass_mg": computed(lipid["mass_mg"], unit="mg", label="Mass to weigh out"),
        })

    return {
        "title": "Formulation Worksheet",
        "not_for_clinical_use": NOT_FOR_CLINICAL_USE,
        "formulation_id": row["formulation_id"],
        "run_id": row["run_id"],
        "created_at": row["created_at"],
        "preset": {
            "key": row["preset_key"],
            "label": row["preset_label"],
            "citation": row["preset_citation"],
        },
        "inputs": inputs,
        "sequence": {
            "nucleotide_length": computed(
                row["nucleotide_length"], unit="nt", label="Length"),
            "molecular_weight_da": computed(
                row["molecular_weight_da"], unit="Da", label="Molecular weight"),
        },
        "amounts": {
            "dose_mcg": computed(row["dose_mcg"], unit="ug", label="mRNA per dose"),
            "injection_volume_ml": computed(
                row["injection_volume_ml"], unit="mL",
                label="Volume at the stated concentration"),
            "total_lipid_mass_mg": computed(
                row["total_lipid_mass_mg"], unit="mg", label="Total lipid mass"),
        },
        "lipids": lipids,
        "process": {
            key: constant(spec["value"], spec["citation"], label=spec["label"])
            for key, spec in MIXING.items()
        },
    }
