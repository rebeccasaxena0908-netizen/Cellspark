"""
Tier 5 — published constants for the formulation worksheet.

Everything in this file is a `constant` in the provenance scheme: a number
taken from outside this system and cited. Nothing here is derived from a
patient, a run, or a user input.

HOW THE MOLECULAR WEIGHTS ARE OBTAINED
Vendor datasheets disagree in the second decimal place — SM-102 is listed as
710.17, 710.18 and 710.2 by different suppliers — because they were computed
against different vintages of the IUPAC atomic-weight table. Rather than copy
one supplier's rounding, the four small-molecule lipids carry their molecular
FORMULA, verified against PubChem, and their weight is computed from it here
by `formula_weight`. The constant is then reproducible from a published
formula and a published atomic-weight table, which is the same standard the
rest of this module holds its numbers to.

The two PEG lipids cannot be handled that way. PEG is polydisperse: a batch
is a distribution of chain lengths, not one molecule, so its "molecular
weight" is a nominal average and no exact formula exists. Those two carry a
published average with the vendor named, and `mw_is_nominal` set so the UI
and the export can say so. PEG2000-DMG has a representative average formula
published alongside its average mass and so is still derived; ALC-0159 has
none and takes the vendor average directly.

WHAT IS DELIBERATELY NOT CLAIMED HERE
The target particle size is recorded as the size range this class of lipid
system typically produces, measured by dynamic light scattering. It is not a
specification, it is not a prediction for any particular construct, and it is
not evidence of where the particle goes in the body. Biodistribution is
governed far more by the ionizable lipid's pKa and surface chemistry than by
diameter, and an intramuscular LNP largely remains near the injection site
with partial lymphatic drainage.
"""

import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

# IUPAC 2021 abridged standard atomic weights (CIAAW).
# https://ciaaw.org/abridged-atomic-weights.htm
ATOMIC_WEIGHTS: Dict[str, float] = {
    "H": 1.008,
    "C": 12.011,
    "N": 14.007,
    "O": 15.999,
    "P": 30.974,
}

ATOMIC_WEIGHT_CITATION = (
    "IUPAC/CIAAW abridged standard atomic weights, 2021 revision"
)

_FORMULA_TOKEN = re.compile(r"([A-Z][a-z]?)(\d*)")


def formula_weight(formula: str) -> float:
    """
    Average molecular weight of a simple molecular formula, in g/mol.

    Handles the flat `C44H87NO5` form these lipids are published in — no
    nesting, no charges, no isotopes. An unknown element is an error rather
    than a silent zero: a typo in a published constant must not produce a
    plausible-looking mass.
    """
    if not formula or not formula.strip():
        raise ValueError("Empty molecular formula")

    text = formula.strip()
    total = 0.0
    consumed = 0
    for element, count in _FORMULA_TOKEN.findall(text):
        if element not in ATOMIC_WEIGHTS:
            raise ValueError(f"Unknown element {element!r} in formula {formula!r}")
        total += ATOMIC_WEIGHTS[element] * int(count or 1)
        consumed += len(element) + len(count)

    if consumed != len(text):
        raise ValueError(f"Could not parse molecular formula {formula!r}")
    return total


# ---------------------------------------------------------------- lipids
@dataclass(frozen=True)
class Lipid:
    """
    One component of a lipid nanoparticle, at one molar percentage.

    `role` matches the ENUM on formulation_lipid, so a row can be written
    without translation. `molar_pct` belongs to the preset rather than to the
    lipid in general — DSPC is 10% in the Moderna system and 9.4% in the
    Pfizer one — which is why it lives here and not in a lipid registry.
    """
    role: str
    name: str
    molar_pct: float
    citation: str
    formula: Optional[str] = None
    nominal_mw_da: Optional[float] = None
    mw_note: str = ""

    @property
    def molecular_weight_da(self) -> float:
        """
        The weight used in the arithmetic, in g/mol.

        A published average wins over the formula where both exist: for a
        polydisperse PEG the vendor's measured average describes the material
        a lab would actually weigh out, and the formula is only a
        representative chain. For everything else there is no average and the
        formula is the source.
        """
        if self.nominal_mw_da is not None:
            return self.nominal_mw_da
        if self.formula is not None:
            return round(formula_weight(self.formula), 2)
        raise ValueError(f"{self.name} has neither a formula nor a nominal weight")

    @property
    def mw_is_nominal(self) -> bool:
        """True when the weight is a polymer average rather than exact."""
        return self.nominal_mw_da is not None


# The two ionizable lipids, the helper phospholipid and the sterol are all
# single molecules with formulas confirmed on PubChem.
SM102 = Lipid(
    role="ionizable",
    name="SM-102",
    molar_pct=50.0,
    formula="C44H87NO5",
    citation=(
        "CAS 2089251-47-6; formula C44H87NO5 per PubChem CID 126697616. "
        "Weight computed from formula (" + ATOMIC_WEIGHT_CITATION + "); "
        "suppliers publish 710.17-710.2 depending on atomic-weight vintage."
    ),
)

ALC0315 = Lipid(
    role="ionizable",
    name="ALC-0315",
    molar_pct=46.3,
    formula="C48H95NO5",
    citation=(
        "CAS 2036272-55-4; formula C48H95NO5 per PubChem CID 122666778. "
        "Weight computed from formula (" + ATOMIC_WEIGHT_CITATION + "); "
        "suppliers publish 766.27-766.3."
    ),
)

DSPC = Lipid(
    role="helper",
    name="DSPC",
    molar_pct=10.0,
    formula="C44H88NO8P",
    citation=(
        "1,2-distearoyl-sn-glycero-3-phosphocholine; formula C44H88NO8P per "
        "PubChem CID 94190. Weight computed from formula ("
        + ATOMIC_WEIGHT_CITATION + "); suppliers publish 790.15."
    ),
)

CHOLESTEROL = Lipid(
    role="cholesterol",
    name="Cholesterol",
    molar_pct=38.5,
    formula="C27H46O",
    citation=(
        "Formula C27H46O per PubChem CID 5997. Weight computed from formula ("
        + ATOMIC_WEIGHT_CITATION + "); suppliers publish 386.65."
    ),
)

PEG2000_DMG = Lipid(
    role="peg",
    name="PEG2000-DMG",
    molar_pct=1.5,
    # Avanti publishes a representative average formula alongside the average
    # mass, so this one is still derived rather than copied.
    formula="C122H242O50",
    nominal_mw_da=2509.2,
    mw_note=(
        "Polydisperse PEG: the formula is Avanti's representative average "
        "chain, not a single molecule. Measured Mw by TOF-MS 2514.5."
    ),
    citation=(
        "1,2-dimyristoyl-rac-glycero-3-methoxypolyethylene glycol-2000. "
        "Avanti Research 880151, certificate of analysis: theoretical average "
        "MW 2509.2, representative formula C122H242O50."
    ),
)

ALC0159 = Lipid(
    role="peg",
    name="ALC-0159",
    molar_pct=1.6,
    # No representative formula is published: Cayman lists it as
    # (C2H4O)nC31H63NO2 with n unfixed, so there is nothing to derive from.
    nominal_mw_da=2400.0,
    mw_note=(
        "Polydisperse PEG, nominal average only. Published vendor averages "
        "span 2400-2450 Da (Cayman 2400, Biorbyt 2400 +/- 10%, MedKoo 2450); "
        "at 1.6 mol% this spread moves total lipid mass by under 0.1%."
    ),
    citation=(
        "2-[(polyethylene glycol)-2000]-N,N-ditetradecylacetamide, "
        "CAS 1849616-42-7. Cayman Chemical 34336: average MW 2400 Da, "
        "formula (C2H4O)nC31H63NO2."
    ),
)


# ---------------------------------------------------------------- presets
@dataclass(frozen=True)
class Preset:
    """
    One published lipid system.

    These are not interchangeable settings on one formulation. They are two
    different systems with different ionizable lipids, different PEG lipids
    and different molar ratios, so each carries its own ratio and its own
    citation and the UI re-renders both when the preset changes.
    """
    key: str
    label: str
    citation: str
    lipids: Tuple[Lipid, ...]
    target_size_nm: Tuple[int, int]
    size_citation: str

    @property
    def ionizable(self) -> Lipid:
        for lipid in self.lipids:
            if lipid.role == "ionizable":
                return lipid
        raise ValueError(f"Preset {self.key} has no ionizable lipid")


_SIZE_CITATION = (
    "Typical hydrodynamic diameter for this class of mRNA-LNP by dynamic "
    "light scattering; Comirnaty measures approximately 94 nm (Waters "
    "GTxResolve SEC application note). Distributions are broad and "
    "method-dependent - FFF-MALS spans roughly 40-300 nm diameter - so this "
    "is a typical range for the lipid system, not a specification for any "
    "particular construct, and it says nothing about biodistribution."
)

PRESETS: Dict[str, Preset] = {
    "sm102_moderna": Preset(
        key="sm102_moderna",
        label="SM-102 (Moderna mRNA-1273 type)",
        citation=(
            "SM-102 : DSPC : cholesterol : PEG2000-DMG = 50 : 10 : 38.5 : 1.5 "
            "mol%. Sabnis et al., Mol Ther 2018;26(6):1509-1519; restated for "
            "mRNA-1273 in Moderna patent US 12,280,105 as "
            "'about 50:10:38.5:1.5'."
        ),
        lipids=(SM102, DSPC, CHOLESTEROL, PEG2000_DMG),
        target_size_nm=(80, 100),
        size_citation=_SIZE_CITATION,
    ),
    "alc0315_pfizer": Preset(
        key="alc0315_pfizer",
        label="ALC-0315 (Pfizer/BioNTech BNT162b2 type)",
        citation=(
            "ALC-0315 : DSPC : cholesterol : ALC-0159 = "
            "46.3 : 9.4 : 42.7 : 1.6 mol% (BNT162b2). Vendor formulation data "
            "(MedChemExpress / CliniSciences ALC-0315 product data); the four "
            "values sum to 100.0."
        ),
        lipids=(
            ALC0315,
            # DSPC and cholesterol sit at different percentages in this system,
            # so they are re-stated rather than shared with the preset above.
            Lipid(role="helper", name="DSPC", molar_pct=9.4,
                  formula=DSPC.formula, citation=DSPC.citation),
            Lipid(role="cholesterol", name="Cholesterol", molar_pct=42.7,
                  formula=CHOLESTEROL.formula, citation=CHOLESTEROL.citation),
            ALC0159,
        ),
        target_size_nm=(80, 100),
        size_citation=_SIZE_CITATION,
    ),
}

DEFAULT_PRESET = "sm102_moderna"


# ---------------------------------------------------------------- RNA mass
# Residue masses for single-stranded RNA at physiological pH, from the
# Thermo Fisher / Ambion nucleic acid molecular weight table.
RNA_RESIDUE_MASS_DA: Dict[str, float] = {
    "A": 329.21,
    "U": 306.17,
    "C": 305.18,
    "G": 345.21,
}

# The table's end correction. It assumes a 5' TRIPHOSPHATE, which is what
# in-vitro transcription leaves behind. A manufactured therapeutic mRNA is
# capped instead (Cap1 adds roughly 500 Da over a 5'-OH) and carries a
# poly-A tail, so for a real construct this term is the wrong end group by a
# few hundred daltons. On a construct of a few thousand nucleotides that is a
# fraction of a percent of the total and it cancels out of the lipid ratios
# entirely, but it is an approximation and is reported as one. Qiagen's
# converter uses +18.02 for a 5'-OH instead; the choice of end group is the
# only difference between them.
RNA_END_CORRECTION_DA = 159.0

RNA_MASS_CITATION = (
    "Thermo Fisher / Ambion nucleic acid molecular weights and conversions: "
    "MW = (An x 329.21) + (Un x 306.17) + (Cn x 305.18) + (Gn x 345.21) + "
    "159.0, valid at physiological pH; the +159.0 term accounts for a 5' "
    "triphosphate."
)

VALID_BASES = frozenset("AUGC")


# ---------------------------------------------------------------- process
# Bench-scale microfluidic mixing parameters. These describe a process, not a
# property of the construct, and an operator changes them to suit the
# cartridge they have.
MIXING = {
    "flow_rate_ratio": {
        "value": "3:1",
        "label": "Aqueous : organic flow ratio",
        "citation": (
            "3:1 aqueous-to-ethanol is the standard ratio for microfluidic "
            "mRNA-LNP formulation on staggered-herringbone and "
            "NanoAssemblr-type mixers (Belliveau et al., Mol Ther Nucleic "
            "Acids 2012;1:e37)."
        ),
    },
    "total_flow_rate_ml_min": {
        # The brief named 12 mL/min against a staggered herringbone mixer.
        # The published SHM work runs 0.02-4 mL/min and reports polydispersity
        # falling as flow rises; 12 mL/min belongs to the larger cartridges
        # (tested 0.4-20 mL/min), not to SHM. Recorded as a range with the
        # device dependence stated rather than as one number.
        "value": "1-12 (cartridge dependent)",
        "label": "Total flow rate (mL/min)",
        "citation": (
            "Staggered-herringbone mixers are characterised at 0.02-4 mL/min "
            "(Belliveau et al. 2012); larger benchtop cartridges are run at "
            "0.4-20 mL/min. The usable rate is set by the cartridge's "
            "pressure rating, so this is a range, not a setting."
        ),
    },
    "mixer": {
        "value": "Staggered herringbone micromixer",
        "label": "Mixer geometry",
        "citation": (
            "Chaotic-advection micromixer used for nucleic-acid LNP "
            "formulation (Belliveau et al., Mol Ther Nucleic Acids "
            "2012;1:e37)."
        ),
    },
    "aqueous_phase": {
        "value": "mRNA in 50 mM citrate, pH 4.0",
        "label": "Aqueous phase",
        "citation": (
            "Acidic citrate protonates the ionizable lipid so it can complex "
            "the RNA; 50 mM citrate at pH 4.0 is the standard choice."
        ),
    },
    "organic_phase": {
        "value": "Lipids in ethanol",
        "label": "Organic phase",
        "citation": "Ethanol is the standard lipid solvent for this process.",
    },
}

# Default N/P. An input, not a constant — it is here only so the UI can name
# where its default came from.
DEFAULT_NP_RATIO = 6.0
NP_RATIO_CITATION = (
    "Both mRNA-1273 and BNT162b2 are formulated at an N/P ratio of "
    "approximately 6; 6.0 is used as the starting value."
)

# Defaults for the remaining inputs. Every one of these is an assumption with
# no clinical standing in this system; the strings say so because they are
# rendered verbatim.
DEFAULT_DOSE_PER_KG_MCG = 0.5
DOSE_PER_KG_BASIS = (
    "Editable input with no clinical basis in this system. CellSpark has run "
    "no trial, no animal study and no toxicology screen, and does not "
    "recommend a dose. 0.5 ug/kg is a round starting number for arithmetic "
    "only - change it to whatever your protocol specifies."
)

DEFAULT_CONCENTRATION_MCG_ML = 100.0
CONCENTRATION_BASIS = (
    "Editable input. The concentration your drug product is formulated at; "
    "100 ug/mL is a common working concentration for a bench preparation."
)

WEIGHT_BASIS = (
    "Editable input. Patient or subject body weight, used only to multiply "
    "out the ug/kg figure above."
)

ROUTE_OPTIONS = ("Intramuscular", "Subcutaneous", "Intradermal", "Intravenous")
DEFAULT_ROUTE = "Intramuscular"
ROUTE_BASIS = (
    "Selectable input, not derived from anything in this run. Intramuscular "
    "is the route used in the published COVID-19 mRNA vaccine trial designs "
    "and is offered as a default on that basis alone."
)

SCHEDULE_OPTIONS = (
    "Single dose",
    "Two doses, 21 days apart",
    "Two doses, 28 days apart",
    "Three doses, 0/21/42 days",
)
DEFAULT_SCHEDULE = "Two doses, 28 days apart"
SCHEDULE_BASIS = (
    "Selectable input, not derived from anything in this run. The two-dose "
    "intervals are copied from the BNT162b2 (21-day) and mRNA-1273 (28-day) "
    "trial designs and carry no recommendation for this construct."
)

# Rendered on the panel, on the print view and in the JSON export.
NOT_FOR_CLINICAL_USE = (
    "Computational worksheet for research and manufacturing planning. Not a "
    "clinical protocol and not validated for human use. No value here has "
    "been through a trial, an animal study or a toxicology screen."
)
