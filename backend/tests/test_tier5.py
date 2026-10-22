"""
Tier 5 — formulation worksheet.

The worked example in the brief was computed independently of this code, so
it is the anchor: if `test_worked_example_*` fails, the implementation is
wrong, not the fixture.

The rest fall into three groups: the arithmetic's own properties (ratios hold,
masses scale), input rejection (a DNA sequence must not silently score), and
the provenance contract (nothing reaches a caller unclassified). The database
tests need MySQL and skip without it, like every other DB test here.
"""

import pytest

from app.tier5 import constants as C
from app.tier5.formulate import (
    ASSUMPTION,
    COMPUTED,
    CONSTANT,
    PROVENANCE_CLASSES,
    FormulationError,
    clean_sequence,
    export_document,
    formulate,
    molecular_weight,
    walk_values,
)

# The fixture from the brief, verified independently.
FIXTURE_SEQ = "AUGAAGCUGGUGGUGGUGGGCGCCGACGGCGUGUGA"
FIXTURE_ARGS = dict(
    patient_weight_kg=70.0,
    dose_per_kg_mcg=0.5,
    concentration_mcg_ml=100.0,
    np_ratio=6.0,
    preset_key="sm102_moderna",
)


@pytest.fixture
def sheet():
    return formulate(FIXTURE_SEQ, **FIXTURE_ARGS)


def value(node):
    """The number out of a provenance envelope."""
    return node["value"]


# ---------------------------------------------------------------- the fixture
def test_worked_example_sequence(sheet):
    seq = sheet["sequence"]
    assert value(seq["nucleotide_length"]) == 36
    assert value(seq["count_a"]) == 5
    assert value(seq["count_u"]) == 7
    assert value(seq["count_c"]) == 6
    assert value(seq["count_g"]) == 18
    assert value(seq["molecular_weight_da"]) == pytest.approx(11993.1, abs=0.05)


def test_worked_example_amounts(sheet):
    amt = sheet["amounts"]
    assert value(amt["dose_mcg"]) == pytest.approx(35.0, abs=0.001)
    assert value(amt["mrna_nanomoles"]) == pytest.approx(2.9183, abs=0.0001)
    assert value(amt["phosphate_micromoles"]) == pytest.approx(0.1051, abs=0.0001)
    assert value(amt["injection_volume_ml"]) == pytest.approx(0.35, abs=0.001)
    assert value(amt["total_lipid_mass_mg"]) == pytest.approx(0.7824, abs=0.0001)


@pytest.mark.parametrize("name, micromoles, mass_mg", [
    ("SM-102",      0.6304, 0.4477),
    ("DSPC",        0.1261, 0.0996),
    ("Cholesterol", 0.4854, 0.1877),
    ("PEG2000-DMG", 0.0189, 0.0475),
])
def test_worked_example_lipids(sheet, name, micromoles, mass_mg):
    row = next(l for l in sheet["lipids"] if l["name"] == name)
    assert value(row["micromoles"]) == pytest.approx(micromoles, abs=0.0001)
    assert value(row["mass_mg"]) == pytest.approx(mass_mg, abs=0.0001)


# ---------------------------------------------------------------- properties
def test_lipid_micromoles_hold_the_preset_molar_ratio(sheet):
    """
    Every lipid's share of the total moles equals its molar percentage.

    This is the property the lipid table rests on, so it is checked against
    the preset rather than against the four numbers above — those could all
    be wrong together in the same direction.
    """
    total = value(sheet["amounts"]["total_lipid_micromoles"])
    preset = C.PRESETS["sm102_moderna"]
    for lipid in preset.lipids:
        row = next(l for l in sheet["lipids"] if l["name"] == lipid.name)
        share = 100.0 * value(row["micromoles"]) / total
        assert share == pytest.approx(lipid.molar_pct, abs=0.01)


def test_doubling_the_dose_doubles_every_lipid_mass(sheet):
    doubled = formulate(FIXTURE_SEQ, **{**FIXTURE_ARGS, "dose_per_kg_mcg": 1.0})

    assert value(doubled["amounts"]["dose_mcg"]) == pytest.approx(70.0, abs=0.001)
    for one in sheet["lipids"]:
        two = next(l for l in doubled["lipids"] if l["name"] == one["name"])
        # Amounts are reported to 6 dp and masses to 4, so the doubled value
        # can differ from twice the rounded one by up to a rounding quantum.
        # The tolerances are that quantum, not slack for a scaling error.
        assert value(two["micromoles"]) == pytest.approx(
            2 * value(one["micromoles"]), abs=2e-6)
        assert value(two["mass_mg"]) == pytest.approx(
            2 * value(one["mass_mg"]), abs=2e-4)
    assert value(doubled["amounts"]["total_lipid_mass_mg"]) == pytest.approx(
        2 * value(sheet["amounts"]["total_lipid_mass_mg"]), abs=2e-4)


def test_doubling_the_weight_leaves_the_molar_ratio_unchanged(sheet):
    """Scaling the dose must move the amounts without moving the ratio."""
    heavier = formulate(FIXTURE_SEQ, **{**FIXTURE_ARGS, "patient_weight_kg": 140.0})
    for one in sheet["lipids"]:
        two = next(l for l in heavier["lipids"] if l["name"] == one["name"])
        assert value(two["mass_mg"]) == pytest.approx(
            2 * value(one["mass_mg"]), abs=2e-4)

    total = value(heavier["amounts"]["total_lipid_micromoles"])
    for lipid in C.PRESETS["sm102_moderna"].lipids:
        row = next(l for l in heavier["lipids"] if l["name"] == lipid.name)
        assert 100.0 * value(row["micromoles"]) / total == pytest.approx(
            lipid.molar_pct, abs=0.01)


def test_np_ratio_scales_the_lipid_but_not_the_dose(sheet):
    """N/P is lipid per phosphate: it must not touch the mRNA amount."""
    doubled_np = formulate(FIXTURE_SEQ, **{**FIXTURE_ARGS, "np_ratio": 12.0})
    assert value(doubled_np["amounts"]["dose_mcg"]) == pytest.approx(
        value(sheet["amounts"]["dose_mcg"]))
    assert value(doubled_np["amounts"]["mrna_nanomoles"]) == pytest.approx(
        value(sheet["amounts"]["mrna_nanomoles"]))
    assert value(doubled_np["amounts"]["total_lipid_mass_mg"]) == pytest.approx(
        2 * value(sheet["amounts"]["total_lipid_mass_mg"]), rel=1e-9)


def test_switching_preset_changes_lipids_ratios_and_citation(sheet):
    other = formulate(FIXTURE_SEQ, **{**FIXTURE_ARGS, "preset_key": "alc0315_pfizer"})

    assert [l["name"] for l in other["lipids"]] == [
        "ALC-0315", "DSPC", "Cholesterol", "ALC-0159"]
    assert other["preset"]["citation"] != sheet["preset"]["citation"]
    # DSPC sits at a different percentage in the two systems — the presets are
    # not one formulation with swappable lipids.
    dspc_a = next(l for l in sheet["lipids"] if l["name"] == "DSPC")
    dspc_b = next(l for l in other["lipids"] if l["name"] == "DSPC")
    assert value(dspc_a["molar_pct"]) == 10.0
    assert value(dspc_b["molar_pct"]) == 9.4


# ---------------------------------------------------------------- rejection
def test_dna_sequence_is_rejected_not_scored():
    """
    A T-containing sequence must fail, not produce a number.

    This is the failure that matters most: T and U have different residue
    masses, so a DNA sequence scored as RNA yields a molecular weight and a
    full lipid table that are wrong and look entirely plausible.
    """
    with pytest.raises(FormulationError) as e:
        formulate("AUGAAGCTGGUGGUGGUGGGCGCCGACGGCGUGUGA", **FIXTURE_ARGS)
    assert "T" in str(e.value)
    assert "DNA" in str(e.value)


@pytest.mark.parametrize("bad", ["", "   ", "\n\t ", None])
def test_empty_or_whitespace_sequence_is_rejected(bad):
    with pytest.raises(FormulationError):
        formulate(bad, **FIXTURE_ARGS)


@pytest.mark.parametrize("bad", ["AUGN", "AUG-AUG", "AUG AUG!", "auguX"])
def test_non_augc_characters_are_rejected(bad):
    with pytest.raises(FormulationError):
        formulate(bad, **FIXTURE_ARGS)


def test_internal_whitespace_is_tolerated_and_case_is_normalised():
    """A sequence pasted out of a FASTA file arrives wrapped and must work."""
    wrapped = "augaagcuggugguggugggc\ngccgacggcgugUGA"
    assert clean_sequence(wrapped) == FIXTURE_SEQ
    assert molecular_weight(clean_sequence(wrapped)) == pytest.approx(11993.1, abs=0.05)


@pytest.mark.parametrize("field, bad", [
    ("patient_weight_kg", 0),
    ("patient_weight_kg", -70),
    ("dose_per_kg_mcg", 0),
    ("concentration_mcg_ml", -1),
    ("np_ratio", 0),
    ("patient_weight_kg", "heavy"),
    ("np_ratio", float("nan")),
])
def test_non_positive_and_non_numeric_inputs_are_rejected(field, bad):
    with pytest.raises(FormulationError):
        formulate(FIXTURE_SEQ, **{**FIXTURE_ARGS, field: bad})


def test_unknown_preset_route_and_schedule_are_rejected():
    with pytest.raises(FormulationError):
        formulate(FIXTURE_SEQ, **{**FIXTURE_ARGS, "preset_key": "nope"})
    with pytest.raises(FormulationError):
        formulate(FIXTURE_SEQ, **FIXTURE_ARGS, route="Intrathecal")
    with pytest.raises(FormulationError):
        formulate(FIXTURE_SEQ, **FIXTURE_ARGS, schedule="Daily forever")


# ---------------------------------------------------------------- constants
@pytest.mark.parametrize("key", list(C.PRESETS))
def test_preset_molar_percentages_sum_to_100(key):
    total = sum(l.molar_pct for l in C.PRESETS[key].lipids)
    assert total == pytest.approx(100.0, abs=0.01)


@pytest.mark.parametrize("key", list(C.PRESETS))
def test_every_preset_has_four_lipids_with_distinct_roles(key):
    """
    One row per role, matching the UNIQUE KEY on (formulation_id, role).

    Two lipids sharing a role would be rejected by the database on save, so
    it is caught here where the message is readable.
    """
    lipids = C.PRESETS[key].lipids
    assert len(lipids) == 4
    assert sorted(l.role for l in lipids) == [
        "cholesterol", "helper", "ionizable", "peg"]


@pytest.mark.parametrize("key", list(C.PRESETS))
def test_every_constant_is_cited(key):
    preset = C.PRESETS[key]
    assert len(preset.citation) > 40
    for lipid in preset.lipids:
        assert len(lipid.citation) > 40, f"{lipid.name} has no real citation"


@pytest.mark.parametrize("formula, expected", [
    # Each formula is the one PubChem records for that compound; the expected
    # weight is computed from the IUPAC 2021 abridged atomic weights.
    ("C44H87NO5", 710.18),    # SM-102,      CID 126697616
    ("C48H95NO5", 766.29),    # ALC-0315,    CID 122666778
    ("C44H88NO8P", 790.16),   # DSPC,        CID 94190
    ("C27H46O", 386.66),      # cholesterol, CID 5997
])
def test_formula_weights_are_reproducible_from_the_formula(formula, expected):
    assert C.formula_weight(formula) == pytest.approx(expected, abs=0.01)


def test_published_vendor_weights_agree_with_the_derived_ones():
    """
    The derived weights must match what suppliers publish.

    Vendors compute against older atomic-weight tables and so differ in the
    second decimal; anything larger than that would mean the formula is wrong,
    not the rounding.
    """
    published = {
        "SM-102": 710.17,        # Selleckchem, Cayman
        "ALC-0315": 766.27,      # Selleckchem, Cayman
        "DSPC": 790.15,          # Avanti, suppliers generally
        "Cholesterol": 386.65,   # suppliers generally
    }
    for lipid in C.PRESETS["sm102_moderna"].lipids + C.PRESETS["alc0315_pfizer"].lipids:
        if lipid.name in published:
            assert lipid.molecular_weight_da == pytest.approx(
                published[lipid.name], abs=0.02), lipid.name


def test_peg2000_dmg_nominal_weight_matches_its_representative_formula():
    """
    The one polydisperse lipid with a published formula, cross-checked.

    PEG2000-DMG takes Avanti's published average of 2509.2 rather than the
    formula, because the average describes the material a lab weighs out. The
    two must still agree, or one of them has been transcribed wrongly.
    """
    assert C.PEG2000_DMG.nominal_mw_da == 2509.2
    assert C.formula_weight(C.PEG2000_DMG.formula) == pytest.approx(2509.2, abs=0.1)
    assert C.PEG2000_DMG.mw_is_nominal is True


def test_alc0159_is_marked_nominal_and_has_no_derived_formula():
    """
    ALC-0159's weight is a vendor average with no formula behind it.

    Published averages span 2400-2450 Da and no source gives a single
    authoritative figure, so the value is flagged nominal and the spread is
    stated in its note. A reader must be able to tell this number apart from
    the four that are computed from a formula.
    """
    assert C.ALC0159.mw_is_nominal is True
    assert C.ALC0159.formula is None
    assert C.ALC0159.molecular_weight_da == 2400.0
    assert "2400-2450" in C.ALC0159.mw_note


def test_rna_residue_masses_match_the_published_table():
    assert C.RNA_RESIDUE_MASS_DA == {
        "A": 329.21, "U": 306.17, "C": 305.18, "G": 345.21}
    assert C.RNA_END_CORRECTION_DA == 159.0
    assert "triphosphate" in C.RNA_MASS_CITATION


def test_unknown_element_in_a_formula_is_an_error_not_a_zero():
    """A typo in a published constant must not yield a plausible mass."""
    with pytest.raises(ValueError):
        C.formula_weight("C44H87XO5")
    with pytest.raises(ValueError):
        C.formula_weight("")


# ---------------------------------------------------------------- provenance
def test_every_returned_value_carries_a_provenance_class(sheet):
    envelopes = list(walk_values(sheet))
    assert len(envelopes) > 30
    for env in envelopes:
        assert env.get("provenance") in PROVENANCE_CLASSES, env


def test_constants_carry_citations_and_assumptions_carry_a_basis(sheet):
    """
    The two classes that are not self-explanatory must say where they came
    from. A constant without a citation and an assumption without a stated
    basis are both just unexplained numbers.
    """
    for env in walk_values(sheet):
        if env["provenance"] == CONSTANT:
            assert env.get("citation"), env
        elif env["provenance"] == ASSUMPTION:
            assert env.get("basis"), env


def test_the_dose_is_computed_from_assumptions_and_labelled_as_such(sheet):
    """
    The dose is arithmetic on two user inputs, and the sheet must say so.

    This is the specific misreading the module exists to prevent: a sheet
    reading "Dose: 35.0 ug" looks like guidance when it is 70 multiplied by a
    figure the user chose.
    """
    dose = sheet["amounts"]["dose_mcg"]
    assert dose["provenance"] == COMPUTED
    assert "not a recommended dose" in dose["note"].lower()

    per_kg = sheet["inputs"]["dose_per_kg_mcg"]
    assert per_kg["provenance"] == ASSUMPTION
    assert "no clinical basis" in per_kg["basis"].lower()


def test_dose_per_kg_is_an_input_not_a_default_the_server_decides(sheet):
    """The caller's figure is used verbatim, whatever it is."""
    odd = formulate(FIXTURE_SEQ, **{**FIXTURE_ARGS, "dose_per_kg_mcg": 3.7})
    assert value(odd["inputs"]["dose_per_kg_mcg"]) == 3.7
    assert value(odd["amounts"]["dose_mcg"]) == pytest.approx(259.0, abs=0.001)


def test_lipid_ratios_are_constant_and_amounts_are_computed(sheet):
    for row in sheet["lipids"]:
        assert row["molar_pct"]["provenance"] == CONSTANT
        assert row["molecular_weight_da"]["provenance"] == CONSTANT
        assert row["micromoles"]["provenance"] == COMPUTED
        assert row["mass_mg"]["provenance"] == COMPUTED


def test_worksheet_is_titled_a_worksheet_and_carries_the_standing_line(sheet):
    assert sheet["title"] == "Formulation Worksheet"
    line = sheet["not_for_clinical_use"].lower()
    assert "not a clinical protocol" in line
    assert "not validated for human use" in line


def test_particle_size_is_a_typical_range_and_claims_no_biodistribution(sheet):
    """
    The size range must not be dressed up as targeting.

    Diameter does not direct an LNP to the lymph nodes — pKa and surface
    chemistry dominate, and an intramuscular LNP largely stays near the
    injection site. The citation must say what the number is and is not.
    """
    low = sheet["particle_size"]["target_size_nm_min"]
    high = sheet["particle_size"]["target_size_nm_max"]
    assert (value(low), value(high)) == (80, 100)
    assert low["provenance"] == CONSTANT

    citation = low["citation"].lower()
    assert "typical range" in citation
    assert "not a specification" in citation
    assert "lymph" not in citation

    joined = " ".join(sheet["notes"]).lower()
    assert "not a prediction for this construct" in joined


def test_process_parameters_are_constants_with_citations(sheet):
    for key, env in sheet["process"].items():
        assert env["provenance"] == CONSTANT, key
        assert env.get("citation"), key


def test_total_flow_rate_is_a_range_not_a_single_claimed_setting(sheet):
    """
    The usable flow rate depends on the cartridge, so it is recorded as a
    range. The published staggered-herringbone work runs at 0.02-4 mL/min;
    stating one figure as though it belonged to that mixer would be a claim
    the source does not support.
    """
    flow = sheet["process"]["total_flow_rate_ml_min"]
    assert "-" in str(value(flow))
    assert "cartridge" in str(value(flow)).lower()


# ---------------------------------------------------------------- export
def test_export_document_carries_inputs_as_well_as_outputs(sheet):
    """
    An export showing only outputs is not reproducible: a 35 ug dose means
    nothing without the 70 kg and 0.5 ug/kg that produced it.
    """
    row = {
        "formulation_id": 1, "run_id": 2, "created_at": "2026-10-22T10:00:00",
        "preset_key": "sm102_moderna",
        "preset_label": C.PRESETS["sm102_moderna"].label,
        "preset_citation": C.PRESETS["sm102_moderna"].citation,
        "nucleotide_length": 36, "molecular_weight_da": 11993.1,
        "patient_weight_kg": 70.0, "dose_per_kg_mcg": 0.5, "np_ratio": 6.0,
        "concentration_mcg_ml": 100.0,
        "route": "Intramuscular", "schedule_label": "Two doses, 28 days apart",
        "dose_mcg": 35.0, "injection_volume_ml": 0.35,
        "total_lipid_mass_mg": 0.7824,
        "lipids": [
            {"role": "ionizable", "name": "SM-102", "molar_pct": 50.0,
             "molecular_weight_da": 710.18, "micromoles": 0.630362,
             "mass_mg": 0.4477},
        ],
    }
    doc = export_document(row)

    assert value(doc["inputs"]["patient_weight_kg"]) == 70.0
    assert value(doc["inputs"]["dose_per_kg_mcg"]) == 0.5
    assert value(doc["inputs"]["np_ratio"]) == 6.0
    assert value(doc["inputs"]["route"]) == "Intramuscular"
    assert value(doc["inputs"]["concentration_mcg_ml"]) == pytest.approx(100.0)
    assert value(doc["amounts"]["dose_mcg"]) == 35.0
    assert "not a clinical protocol" in doc["not_for_clinical_use"].lower()

    for env in walk_values(doc):
        assert env.get("provenance") in PROVENANCE_CLASSES, env


def test_export_marks_snapshot_values_as_snapshots(sheet):
    """
    The export must say the lipid numbers are snapshots, so a reader knows
    they are the values the sheet was computed with rather than today's.
    """
    row = {
        "formulation_id": 1, "run_id": 2, "created_at": None,
        "preset_key": "sm102_moderna", "preset_label": "x",
        "preset_citation": "y" * 50,
        "nucleotide_length": 36, "molecular_weight_da": 11993.1,
        "patient_weight_kg": 70.0, "dose_per_kg_mcg": 0.5, "np_ratio": 6.0,
        "concentration_mcg_ml": 100.0,
        "route": "Intramuscular", "schedule_label": "Single dose",
        "dose_mcg": 35.0, "injection_volume_ml": 0.35,
        "total_lipid_mass_mg": 0.7824,
        # A molar percentage that no longer matches the live constant: an
        # export of a saved sheet must still show the stored figure.
        "lipids": [
            {"role": "ionizable", "name": "SM-102", "molar_pct": 49.0,
             "molecular_weight_da": 700.00, "micromoles": 0.6, "mass_mg": 0.42},
        ],
    }
    doc = export_document(row)
    lipid = doc["lipids"][0]
    assert value(lipid["molar_pct"]) == 49.0
    assert value(lipid["molecular_weight_da"]) == 700.00
    assert "snapshot" in lipid["molar_pct"]["note"].lower()
    assert "snapshot" in lipid["molecular_weight_da"]["note"].lower()


# ---------------------------------------------------------------- API / DB
# These need MySQL and the two formulation tables from
# schema_formulation.sql; conftest's engine fixture skips them if it is not
# reachable. Helpers come from the Phase 2 tests, as the Phase 3 ones do.

import os  # noqa: E402

from sqlalchemy import select  # noqa: E402

from app import records  # noqa: E402
from app.models import FormulationLipid, FormulationSpec  # noqa: E402

from test_records import (  # noqa: F401,E402
    ALLELES,
    act_as,
    count,
    fake_result,
    isolated_dirs,
    me_id,
    sign_up,
)


def seed_run_with_construct(db, researcher_id, construct=FIXTURE_SEQ, tier3=None):
    """
    One completed run whose stored result carries a Tier 3 construct.

    fake_result's tier3 has no sequence in it — it only needs a CAI for the
    history tests — so the sequence is put in here. `tier3=...` overrides the
    whole block, which is how the no-construct cases are set up.
    """
    f, _ = records.add_file(db, researcher_id, "f.maf", "/nonexistent/f.maf",
                            os.urandom(32).hex(), 10, 1)
    run = records.start_run(db, researcher_id, f.file_id, "kmp", ALLELES)
    result = fake_result(ALLELES)
    result["run_id"] = run.run_id
    if tier3 is not None:
        result["tier3"] = tier3
    else:
        result["tier3"] = {
            "implemented": True,
            "after": {"cai": 0.912},
            "coding_sequence": construct,
            "full_construct": construct,
        }
    path = records.write_result(run.run_id, result)
    records.complete_run(db, run, result, path, duration_ms=1234)
    db.flush()
    return run


def test_post_formulation_returns_the_worked_example(client, db):
    token = sign_up(client)
    run = seed_run_with_construct(db, me_id(client))

    r = client.post(f"/api/runs/{run.run_id}/formulation", json={
        "patient_weight_kg": 70.0,
        "dose_per_kg_mcg": 0.5,
        "concentration_mcg_ml": 100.0,
        "np_ratio": 6.0,
        "preset_key": "sm102_moderna",
    })
    assert r.status_code == 200, r.text
    body = r.json()

    assert body["title"] == "Formulation Worksheet"
    assert value(body["sequence"]["molecular_weight_da"]) == pytest.approx(
        11993.1, abs=0.05)
    assert value(body["amounts"]["dose_mcg"]) == pytest.approx(35.0, abs=0.001)
    assert value(body["amounts"]["total_lipid_mass_mg"]) == pytest.approx(
        0.7824, abs=0.0001)
    assert body["formulation_id"] > 0
    assert body["run_id"] == run.run_id

    # The contract the UI depends on survives serialisation.
    for env in walk_values(body):
        assert env.get("provenance") in PROVENANCE_CLASSES, env


def test_saving_writes_one_spec_and_exactly_four_lipid_rows(client, db):
    token = sign_up(client)
    run = seed_run_with_construct(db, me_id(client))

    r = client.post(f"/api/runs/{run.run_id}/formulation", json={})
    assert r.status_code == 200, r.text
    fid = r.json()["formulation_id"]

    assert count(db, FormulationSpec, run_id=run.run_id) == 1
    assert count(db, FormulationLipid, formulation_id=fid) == 4

    rows = db.scalars(
        select(FormulationLipid).where(FormulationLipid.formulation_id == fid)
    ).all()
    assert sorted(r.role for r in rows) == [
        "cholesterol", "helper", "ionizable", "peg"]
    assert sorted(r.lipid_name for r in rows) == [
        "Cholesterol", "DSPC", "PEG2000-DMG", "SM-102"]


def test_stored_lipid_values_are_the_computed_ones(client, db):
    """What the sheet showed is what the row holds, to the column's precision."""
    token = sign_up(client)
    run = seed_run_with_construct(db, me_id(client))

    body = client.post(f"/api/runs/{run.run_id}/formulation", json={}).json()
    rows = {
        r.lipid_name: r
        for r in db.scalars(
            select(FormulationLipid).where(
                FormulationLipid.formulation_id == body["formulation_id"])
        ).all()
    }
    for lipid in body["lipids"]:
        row = rows[lipid["name"]]
        assert float(row.mass_mg) == pytest.approx(
            value(lipid["mass_mg"]), abs=1e-4)
        assert float(row.micromoles) == pytest.approx(
            value(lipid["micromoles"]), abs=1e-6)
        assert float(row.molar_pct) == pytest.approx(
            value(lipid["molar_pct"]), abs=0.01)
        assert float(row.molecular_weight_da) == pytest.approx(
            value(lipid["molecular_weight_da"]), abs=0.01)


def test_a_run_can_hold_several_formulations(client, db):
    """Different weights and presets on one run: one-to-many, as the DDL says."""
    token = sign_up(client)
    run = seed_run_with_construct(db, me_id(client))

    client.post(f"/api/runs/{run.run_id}/formulation", json={"patient_weight_kg": 70})
    client.post(f"/api/runs/{run.run_id}/formulation",
                json={"patient_weight_kg": 85, "preset_key": "alc0315_pfizer"})

    assert count(db, FormulationSpec, run_id=run.run_id) == 2
    listed = client.get(f"/api/runs/{run.run_id}/formulations").json()["formulations"]
    assert len(listed) == 2
    assert {f["preset_key"] for f in listed} == {"sm102_moderna", "alc0315_pfizer"}
    # Newest first, like the run list.
    assert listed[0]["formulation_id"] > listed[1]["formulation_id"]


def test_another_researchers_run_is_404(client, db):
    """
    Researcher B asking about A's run gets 404, not 403.

    Same rule as everywhere else in this API: a 403 would confirm the id is
    real. The formulation routes must not be the one place that leaks it.
    """
    a_token = sign_up(client)
    a_run = seed_run_with_construct(db, me_id(client))
    a_body = client.post(f"/api/runs/{a_run.run_id}/formulation", json={}).json()

    sign_up(client)                      # now signed in as researcher B
    assert client.post(
        f"/api/runs/{a_run.run_id}/formulation", json={}).status_code == 404
    assert client.get(
        f"/api/runs/{a_run.run_id}/formulations").status_code == 404
    assert client.get(
        f"/api/formulations/{a_body['formulation_id']}/export.json"
    ).status_code == 404

    # A's own worksheet is still reachable by A.
    act_as(client, a_token)
    assert client.get(
        f"/api/formulations/{a_body['formulation_id']}/export.json"
    ).status_code == 200


def test_a_nonexistent_run_is_also_404(client, db):
    sign_up(client)
    assert client.post("/api/runs/99999999/formulation", json={}).status_code == 404


@pytest.mark.parametrize("tier3, expected_in_detail", [
    ({"implemented": False, "note": "No targets available to design from"},
     "No targets available"),
    ({"implemented": False, "error": "boom"}, "boom"),
    ({"implemented": True, "after": {"cai": 0.9}}, "no sequence"),
])
def test_a_run_with_no_tier3_construct_is_409(client, db, tier3, expected_in_detail):
    """
    409, not 404 and not 500: the run is real and the caller owns it, there is
    simply nothing to formulate. The message says which it is.
    """
    sign_up(client)
    run = seed_run_with_construct(db, me_id(client), tier3=tier3)

    r = client.post(f"/api/runs/{run.run_id}/formulation", json={})
    assert r.status_code == 409, r.text
    assert expected_in_detail.lower() in r.json()["detail"].lower()
    # Nothing was written.
    assert count(db, FormulationSpec, run_id=run.run_id) == 0


def test_a_dna_construct_is_400_and_saves_nothing(client, db):
    """A run whose stored construct contains T must not be formulated."""
    sign_up(client)
    run = seed_run_with_construct(db, me_id(client), construct="AUGCTTAAGCC")

    r = client.post(f"/api/runs/{run.run_id}/formulation", json={})
    assert r.status_code == 400, r.text
    assert "DNA" in r.json()["detail"]
    assert count(db, FormulationSpec, run_id=run.run_id) == 0


@pytest.mark.parametrize("payload", [
    {"patient_weight_kg": 0},
    {"patient_weight_kg": -5},
    {"dose_per_kg_mcg": 0},
    {"np_ratio": 0},
    {"concentration_mcg_ml": 0},
    {"patient_weight_kg": 10_000},
])
def test_out_of_range_inputs_are_rejected_by_the_route(client, db, payload):
    sign_up(client)
    run = seed_run_with_construct(db, me_id(client))
    r = client.post(f"/api/runs/{run.run_id}/formulation", json=payload)
    assert r.status_code in (400, 422), r.text
    assert count(db, FormulationSpec, run_id=run.run_id) == 0


def test_unknown_preset_is_400_with_the_available_keys(client, db):
    sign_up(client)
    run = seed_run_with_construct(db, me_id(client))
    r = client.post(f"/api/runs/{run.run_id}/formulation",
                    json={"preset_key": "liposome_9000"})
    assert r.status_code == 400
    assert "sm102_moderna" in r.json()["detail"]


def test_export_is_built_from_the_snapshot_not_from_live_constants(client, db):
    """
    The snapshot rule, end to end.

    The saved lipid row is edited behind the API to a value the live constants
    do not contain, and the export must still show it. If the export
    recomputed, this would come back as today's 50.0 instead.
    """
    sign_up(client)
    run = seed_run_with_construct(db, me_id(client))
    fid = client.post(f"/api/runs/{run.run_id}/formulation", json={}).json()[
        "formulation_id"]

    row = db.scalars(
        select(FormulationLipid).where(
            FormulationLipid.formulation_id == fid,
            FormulationLipid.role == "ionizable",
        )
    ).one()
    row.molar_pct = 47.5
    db.flush()

    doc = client.get(f"/api/formulations/{fid}/export.json").json()
    ionizable = next(l for l in doc["lipids"] if l["role"] == "ionizable")
    assert value(ionizable["molar_pct"]) == pytest.approx(47.5)
    assert C.SM102.molar_pct == 50.0          # the live constant is untouched


def test_export_carries_the_inputs_and_the_standing_line(client, db):
    sign_up(client)
    run = seed_run_with_construct(db, me_id(client))
    fid = client.post(f"/api/runs/{run.run_id}/formulation", json={
        "patient_weight_kg": 82.5, "dose_per_kg_mcg": 0.75,
        "concentration_mcg_ml": 250.0,
        "route": "Subcutaneous", "schedule": "Single dose",
    }).json()["formulation_id"]

    doc = client.get(f"/api/formulations/{fid}/export.json").json()
    assert value(doc["inputs"]["patient_weight_kg"]) == pytest.approx(82.5)
    assert value(doc["inputs"]["dose_per_kg_mcg"]) == pytest.approx(0.75)
    # Read from the stored column, not divided back out of dose and volume.
    assert value(doc["inputs"]["concentration_mcg_ml"]) == pytest.approx(250.0)
    assert value(doc["inputs"]["route"]) == "Subcutaneous"
    assert value(doc["inputs"]["schedule"]) == "Single dose"
    assert "not a clinical protocol" in doc["not_for_clinical_use"].lower()
    for env in walk_values(doc):
        assert env.get("provenance") in PROVENANCE_CLASSES, env


def test_deleting_a_run_takes_its_formulations_with_it(client, db):
    """ON DELETE CASCADE on both tables, exercised rather than assumed."""
    sign_up(client)
    run = seed_run_with_construct(db, me_id(client))
    fid = client.post(f"/api/runs/{run.run_id}/formulation", json={}).json()[
        "formulation_id"]

    assert client.delete(f"/api/runs/{run.run_id}").status_code == 200
    assert count(db, FormulationSpec, formulation_id=fid) == 0
    assert count(db, FormulationLipid, formulation_id=fid) == 0


def test_formulation_routes_require_a_session(client, db):
    client.cookies.clear()
    assert client.post("/api/runs/1/formulation", json={}).status_code == 401
    assert client.get("/api/runs/1/formulations").status_code == 401
    assert client.get("/api/formulations/1/export.json").status_code == 401


def test_options_route_serves_both_presets_with_citations(client, db):
    sign_up(client)
    body = client.get("/api/formulation/options").json()

    assert {p["key"] for p in body["presets"]} == {
        "sm102_moderna", "alc0315_pfizer"}
    for preset in body["presets"]:
        assert len(preset["lipids"]) == 4
        assert sum(l["molar_pct"] for l in preset["lipids"]) == pytest.approx(
            100.0, abs=0.01)
        assert len(preset["citation"]) > 40
        for lipid in preset["lipids"]:
            assert len(lipid["citation"]) > 40

    assert body["defaults"]["dose_per_kg_mcg"] == 0.5
    assert "no clinical basis" in body["bases"]["dose_per_kg_mcg"].lower()
