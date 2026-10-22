-- ===========================================================================
-- CellSpark — formulation module, schema addition
-- MySQL / MariaDB.  Apply AS ROOT, once:
--
--     mysql -u root < schema_formulation.sql
--
-- The `cellspark` application user's grant is database-wide
-- (cellspark.*), so it picks up these tables automatically. It still has
-- no DDL rights, which is intended.
--
-- This file ADDS tables. It does not touch schema.sql's nine, and it does
-- not drop anything that holds live data.
-- ===========================================================================

USE cellspark;

DROP TABLE IF EXISTS formulation_lipid;
DROP TABLE IF EXISTS formulation_spec;


-- ---------------------------------------------------------------------------
-- formulation_spec — one worked formulation for one run
-- ---------------------------------------------------------------------------
-- Columns are grouped by PROVENANCE, because that distinction is the whole
-- point of this module and the UI renders it:
--
--   computed    — derived from the run's own mRNA sequence. Reproducible.
--   assumption  — supplied by the user. Not a recommendation, an input.
--   constant    — taken from published formulations, cited in code.
--
-- patient_weight_kg is PATIENT DATA. It is the only patient attribute the
-- system stores beyond the mutation file itself, and the report's ethics
-- section should say so.
--
-- A run can have several formulations — different weights, different
-- presets — so this is one-to-many, not one-to-one.
-- ---------------------------------------------------------------------------
CREATE TABLE formulation_spec (
    formulation_id      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    run_id              BIGINT UNSIGNED NOT NULL,
    researcher_id       BIGINT UNSIGNED NOT NULL,

    -- ---- computed from the sequence ------------------------------------
    nucleotide_length   INT UNSIGNED    NOT NULL,
    count_a             INT UNSIGNED    NOT NULL,
    count_u             INT UNSIGNED    NOT NULL,
    count_g             INT UNSIGNED    NOT NULL,
    count_c             INT UNSIGNED    NOT NULL,
    molecular_weight_da DECIMAL(14,2)   NOT NULL,

    -- ---- assumptions supplied by the user ------------------------------
    patient_weight_kg   DECIMAL(5,2)    NOT NULL,
    dose_per_kg_mcg     DECIMAL(6,3)    NOT NULL,
    concentration_mcg_ml DECIMAL(8,2)   NOT NULL,
    np_ratio            DECIMAL(5,2)    NOT NULL,
    route               VARCHAR(60)     NOT NULL,
    schedule_label      VARCHAR(120)    NOT NULL,

    -- ---- computed from sequence + assumptions --------------------------
    dose_mcg            DECIMAL(10,3)   NOT NULL,
    injection_volume_ml DECIMAL(8,3)    NOT NULL,
    mrna_nanomoles      DECIMAL(12,6)   NOT NULL,
    phosphate_micromoles DECIMAL(12,6)  NOT NULL,
    total_lipid_mass_mg DECIMAL(10,4)   NOT NULL,

    -- ---- the published formulation this was worked against -------------
    preset_key          VARCHAR(40)     NOT NULL,
    preset_label        VARCHAR(120)    NOT NULL,
    preset_citation     VARCHAR(300)    NOT NULL,
    target_size_nm_min  SMALLINT UNSIGNED   NULL,
    target_size_nm_max  SMALLINT UNSIGNED   NULL,

    created_at          DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (formulation_id),
    KEY idx_formulation_run (run_id),
    KEY idx_formulation_researcher (researcher_id),

    CONSTRAINT fk_formulation_run
        FOREIGN KEY (run_id) REFERENCES pipeline_run (run_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_formulation_researcher
        FOREIGN KEY (researcher_id) REFERENCES researcher (researcher_id)
        ON DELETE CASCADE
) ENGINE = InnoDB;


-- ---------------------------------------------------------------------------
-- formulation_lipid — the four lipids of one formulation
-- ---------------------------------------------------------------------------
-- Four lipids per formulation is a repeating group, so it gets its own
-- table rather than sixteen columns on the parent — the same first-normal-
-- form argument as run_allele and message_citation.
--
-- The molar percentage and molecular weight are SNAPSHOT here at the moment
-- of calculation, not referenced from a lookup table. If a published
-- constant is later corrected, historical formulations must keep the values
-- they were actually computed with; a saved spec sheet that silently
-- changes is worse than one that is out of date.
-- ---------------------------------------------------------------------------
CREATE TABLE formulation_lipid (
    lipid_id        BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    formulation_id  BIGINT UNSIGNED NOT NULL,

    role            ENUM('ionizable','helper','cholesterol','peg')
                                    NOT NULL,
    lipid_name      VARCHAR(80)     NOT NULL,
    molar_pct       DECIMAL(5,2)    NOT NULL,
    molecular_weight_da DECIMAL(10,2) NOT NULL,

    micromoles      DECIMAL(12,6)   NOT NULL,
    mass_mg         DECIMAL(10,4)   NOT NULL,

    PRIMARY KEY (lipid_id),
    UNIQUE KEY uq_lipid_formulation_role (formulation_id, role),
    KEY idx_lipid_formulation (formulation_id),

    CONSTRAINT fk_lipid_formulation
        FOREIGN KEY (formulation_id) REFERENCES formulation_spec (formulation_id)
        ON DELETE CASCADE
) ENGINE = InnoDB;


-- ===========================================================================
-- Queries this makes possible
-- ===========================================================================

-- Every formulation a researcher has worked, with its run's top target.
--
--   SELECT f.formulation_id, f.created_at, f.preset_label,
--          f.patient_weight_kg, f.dose_mcg, t.gene_symbol, t.peptide
--     FROM formulation_spec f
--     JOIN pipeline_run r ON r.run_id = f.run_id
--     LEFT JOIN predicted_target t
--            ON t.run_id = f.run_id AND t.rank_position = 1
--    WHERE f.researcher_id = ?
--    ORDER BY f.created_at DESC;

-- Total ionizable lipid required across all formulations — the kind of
-- question a lab asks when ordering reagents.
--
--   SELECT l.lipid_name, ROUND(SUM(l.mass_mg), 2) AS total_mg
--     FROM formulation_lipid l
--     JOIN formulation_spec f ON f.formulation_id = l.formulation_id
--    WHERE l.role = 'ionizable'
--    GROUP BY l.lipid_name;

-- How dose scales with construct length across saved formulations.
--
--   SELECT nucleotide_length, patient_weight_kg, dose_mcg, mrna_nanomoles
--     FROM formulation_spec
--    ORDER BY nucleotide_length;
