-- ===========================================================================
-- CellSpark — relational schema
-- MySQL / MariaDB (XAMPP).  InnoDB throughout, for foreign key enforcement.
--
--   mysql -u root -p < schema.sql
--
-- Design notes are inline. They are also the material for the ER diagram and
-- the normalisation section of the report, so they say *why*, not just what.
-- ===========================================================================

CREATE DATABASE IF NOT EXISTS cellspark
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE cellspark;

-- Drop in reverse dependency order so the script is re-runnable.
DROP TABLE IF EXISTS message_citation;
DROP TABLE IF EXISTS chat_message;
DROP TABLE IF EXISTS cross_check_lookup;
DROP TABLE IF EXISTS predicted_target;
DROP TABLE IF EXISTS run_allele;
DROP TABLE IF EXISTS pipeline_run;
DROP TABLE IF EXISTS mutation_file;
DROP TABLE IF EXISTS auth_session;
DROP TABLE IF EXISTS researcher;


-- ---------------------------------------------------------------------------
-- researcher — one row per person with an account
-- ---------------------------------------------------------------------------
-- password_hash is CHAR(60) because that is exactly the length of a bcrypt
-- digest. The plaintext password is never stored, never logged, and never
-- leaves the request handler that hashes it.
-- ---------------------------------------------------------------------------
CREATE TABLE researcher (
    researcher_id   BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    email           VARCHAR(255)    NOT NULL,
    display_name    VARCHAR(100)    NOT NULL,
    institution     VARCHAR(150)        NULL,
    password_hash   CHAR(60)        NOT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at   DATETIME            NULL,

    PRIMARY KEY (researcher_id),
    UNIQUE KEY uq_researcher_email (email)
) ENGINE = InnoDB;


-- ---------------------------------------------------------------------------
-- auth_session — server-side sessions
-- ---------------------------------------------------------------------------
-- session_id holds the SHA-256 of the random token, not the token itself.
-- The raw token goes to the browser in an httpOnly cookie and is never
-- written down here, so a dump of this table cannot be used to impersonate
-- anyone. Same principle as password hashing, applied to session tokens.
--
-- Sessions live in the database rather than in a signed JWT so that logout
-- and revocation actually work — deleting the row ends the session
-- immediately, which a stateless token cannot do.
-- ---------------------------------------------------------------------------
CREATE TABLE auth_session (
    session_id      CHAR(64)        NOT NULL,
    researcher_id   BIGINT UNSIGNED NOT NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at      DATETIME        NOT NULL,
    user_agent      VARCHAR(255)        NULL,

    PRIMARY KEY (session_id),
    KEY idx_session_researcher (researcher_id),
    KEY idx_session_expires (expires_at),

    CONSTRAINT fk_session_researcher
        FOREIGN KEY (researcher_id) REFERENCES researcher (researcher_id)
        ON DELETE CASCADE
) ENGINE = InnoDB;


-- ---------------------------------------------------------------------------
-- mutation_file — an uploaded MAF, owned by one researcher
-- ---------------------------------------------------------------------------
-- The file itself stays on disk; only its metadata and path are stored here.
-- A MAF can be megabytes and the database has no reason to hold it.
--
-- UNIQUE (researcher_id, sha256) deduplicates: the same person uploading the
-- same file twice reuses the existing row rather than creating a duplicate.
-- Two different researchers uploading the same file get separate rows,
-- because ownership differs.
-- ---------------------------------------------------------------------------
CREATE TABLE mutation_file (
    file_id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    researcher_id   BIGINT UNSIGNED NOT NULL,
    original_name   VARCHAR(255)    NOT NULL,
    stored_path     VARCHAR(500)    NOT NULL,
    sha256          CHAR(64)        NOT NULL,
    size_bytes      INT UNSIGNED    NOT NULL,
    mutation_count  INT UNSIGNED        NULL,
    uploaded_at     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (file_id),
    UNIQUE KEY uq_file_owner_hash (researcher_id, sha256),
    KEY idx_file_researcher (researcher_id),

    CONSTRAINT fk_file_researcher
        FOREIGN KEY (researcher_id) REFERENCES researcher (researcher_id)
        ON DELETE CASCADE
) ENGINE = InnoDB;


-- ---------------------------------------------------------------------------
-- pipeline_run — one execution of the four tiers
-- ---------------------------------------------------------------------------
-- Headline figures are denormalised into columns deliberately. They are
-- derivable from the result JSON, but storing them makes the history list a
-- single indexed query instead of opening and parsing every result file.
-- This is a considered denormalisation for read performance, not an
-- oversight — worth stating that way if asked.
--
-- The full result stays on disk at result_path for the same reason as the
-- MAF: it can be hundreds of kilobytes and is read whole or not at all.
-- ---------------------------------------------------------------------------
CREATE TABLE pipeline_run (
    run_id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    researcher_id     BIGINT UNSIGNED NOT NULL,
    file_id           BIGINT UNSIGNED NOT NULL,

    algorithm         ENUM('kmp','boyer_moore','naive') NOT NULL DEFAULT 'kmp',
    status            ENUM('running','completed','failed')
                          NOT NULL DEFAULT 'running',

    started_at        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
    finished_at       DATETIME            NULL,
    duration_ms       INT UNSIGNED        NULL,

    mutations_parsed  INT UNSIGNED        NULL,
    candidates_built  INT UNSIGNED        NULL,
    targets_returned  INT UNSIGNED        NULL,
    best_ic50_nm      DECIMAL(10,2)       NULL,
    cai_after         DECIMAL(4,3)        NULL,

    result_path       VARCHAR(500)        NULL,
    error_message     TEXT                NULL,

    PRIMARY KEY (run_id),
    KEY idx_run_researcher_started (researcher_id, started_at),
    KEY idx_run_file (file_id),

    CONSTRAINT fk_run_researcher
        FOREIGN KEY (researcher_id) REFERENCES researcher (researcher_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_run_file
        FOREIGN KEY (file_id) REFERENCES mutation_file (file_id)
        ON DELETE RESTRICT
) ENGINE = InnoDB;


-- ---------------------------------------------------------------------------
-- run_allele — the HLA alleles a run was executed against
-- ---------------------------------------------------------------------------
-- A run has several alleles. Storing them as "HLA-A*02:01,HLA-B*07:02" in one
-- column would violate first normal form and make "which runs used B*07:02"
-- a LIKE scan. One row per allele keeps the column atomic and the query
-- indexable.
-- ---------------------------------------------------------------------------
CREATE TABLE run_allele (
    run_id  BIGINT UNSIGNED NOT NULL,
    allele  VARCHAR(20)     NOT NULL,

    PRIMARY KEY (run_id, allele),
    KEY idx_runallele_allele (allele),

    CONSTRAINT fk_runallele_run
        FOREIGN KEY (run_id) REFERENCES pipeline_run (run_id)
        ON DELETE CASCADE
) ENGINE = InnoDB;


-- ---------------------------------------------------------------------------
-- predicted_target — the ranked neoantigens a run produced
-- ---------------------------------------------------------------------------
-- Mirroring the top targets into rows makes the output queryable:
--   "every run where KRAS was the top target"
--   "all strong binders this researcher has ever produced"
-- Neither is answerable if the results only exist as JSON on disk.
--
-- agretopicity is wt_ic50_nm / ic50_nm. It is stored rather than computed on
-- read so that it can be indexed and filtered.
-- ---------------------------------------------------------------------------
CREATE TABLE predicted_target (
    target_id       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    run_id          BIGINT UNSIGNED NOT NULL,
    rank_position   TINYINT UNSIGNED NOT NULL,

    peptide         VARCHAR(15)     NOT NULL,
    wildtype        VARCHAR(15)         NULL,
    gene_symbol     VARCHAR(30)     NOT NULL,
    protein_change  VARCHAR(30)     NOT NULL,
    allele          VARCHAR(20)     NOT NULL,

    ic50_nm         DECIMAL(10,2)   NOT NULL,
    wt_ic50_nm      DECIMAL(10,2)       NULL,
    agretopicity    DECIMAL(8,2)        NULL,

    PRIMARY KEY (target_id),
    UNIQUE KEY uq_target_run_rank (run_id, rank_position),
    KEY idx_target_gene (gene_symbol),
    KEY idx_target_ic50 (ic50_nm),

    CONSTRAINT fk_target_run
        FOREIGN KEY (run_id) REFERENCES pipeline_run (run_id)
        ON DELETE CASCADE
) ENGINE = InnoDB;


-- ---------------------------------------------------------------------------
-- chat_message — the copilot conversation, per run
-- ---------------------------------------------------------------------------
-- provider records which path produced an assistant message — the model name,
-- or 'templates' for the offline fallback. Without it the history cannot
-- distinguish a generated answer from a template one, and they look
-- identical.
-- ---------------------------------------------------------------------------
CREATE TABLE chat_message (
    message_id      BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    run_id          BIGINT UNSIGNED NOT NULL,
    researcher_id   BIGINT UNSIGNED NOT NULL,
    role            ENUM('user','assistant') NOT NULL,
    content         TEXT            NOT NULL,
    provider        VARCHAR(50)         NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (message_id),
    KEY idx_message_run_created (run_id, created_at),
    KEY idx_message_researcher (researcher_id),

    CONSTRAINT fk_message_run
        FOREIGN KEY (run_id) REFERENCES pipeline_run (run_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_message_researcher
        FOREIGN KEY (researcher_id) REFERENCES researcher (researcher_id)
        ON DELETE CASCADE
) ENGINE = InnoDB;


-- ---------------------------------------------------------------------------
-- message_citation — the abstracts an assistant message was grounded in
-- ---------------------------------------------------------------------------
-- One message cites several sources. Keeping them in a child table instead of
-- a repeating group inside chat_message is the first-normal-form argument
-- again, and it makes "which abstracts does the copilot cite most" a simple
-- GROUP BY.
-- ---------------------------------------------------------------------------
CREATE TABLE message_citation (
    citation_id     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    message_id      BIGINT UNSIGNED NOT NULL,
    pmid            VARCHAR(20)     NOT NULL,
    title           VARCHAR(500)        NULL,
    journal         VARCHAR(200)        NULL,
    pub_year        SMALLINT UNSIGNED   NULL,
    similarity      DECIMAL(6,4)        NULL,

    PRIMARY KEY (citation_id),
    KEY idx_citation_message (message_id),
    KEY idx_citation_pmid (pmid),

    CONSTRAINT fk_citation_message
        FOREIGN KEY (message_id) REFERENCES chat_message (message_id)
        ON DELETE CASCADE
) ENGINE = InnoDB;


-- ---------------------------------------------------------------------------
-- cross_check_lookup — literature lookups performed against a target's gene
-- ---------------------------------------------------------------------------
-- coverage mirrors the three states the cross-check feature reports. Storing
-- it makes the index's own blind spots measurable over time: counting
-- not_covered rows per gene shows exactly where the 618-abstract corpus is
-- thin.
-- ---------------------------------------------------------------------------
CREATE TABLE cross_check_lookup (
    lookup_id       BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    run_id          BIGINT UNSIGNED NOT NULL,
    researcher_id   BIGINT UNSIGNED NOT NULL,
    gene_symbol     VARCHAR(30)     NOT NULL,
    protein_change  VARCHAR(30)         NULL,
    coverage        ENUM('well_covered','thin','not_covered') NOT NULL,
    summary         TEXT                NULL,
    provider        VARCHAR(50)         NULL,
    created_at      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (lookup_id),
    KEY idx_lookup_run (run_id),
    KEY idx_lookup_gene_coverage (gene_symbol, coverage),

    CONSTRAINT fk_lookup_run
        FOREIGN KEY (run_id) REFERENCES pipeline_run (run_id)
        ON DELETE CASCADE,
    CONSTRAINT fk_lookup_researcher
        FOREIGN KEY (researcher_id) REFERENCES researcher (researcher_id)
        ON DELETE CASCADE
) ENGINE = InnoDB;


-- ===========================================================================
-- Queries worth having ready for the viva. Each one is only answerable
-- because the data is relational.
-- ===========================================================================

-- A researcher's run history, newest first.
--
--   SELECT r.run_id, f.original_name, r.started_at, r.duration_ms,
--          r.targets_returned, r.best_ic50_nm
--     FROM pipeline_run r
--     JOIN mutation_file f ON f.file_id = r.file_id
--    WHERE r.researcher_id = ? AND r.status = 'completed'
--    ORDER BY r.started_at DESC;

-- Which genes come top most often across every run on the system.
--
--   SELECT gene_symbol, COUNT(*) AS times_ranked_first
--     FROM predicted_target
--    WHERE rank_position = 1
--    GROUP BY gene_symbol
--    ORDER BY times_ranked_first DESC;

-- Strong binders whose mutation did not create the epitope — the
-- agretopicity finding, as a query.
--
--   SELECT run_id, peptide, gene_symbol, ic50_nm, agretopicity
--     FROM predicted_target
--    WHERE ic50_nm < 50 AND agretopicity < 1
--    ORDER BY ic50_nm;

-- Where the 618-abstract corpus is blind.
--
--   SELECT gene_symbol, COUNT(*) AS misses
--     FROM cross_check_lookup
--    WHERE coverage = 'not_covered'
--    GROUP BY gene_symbol
--    ORDER BY misses DESC;

-- How often the copilot fell back to templates instead of generating.
--
--   SELECT provider, COUNT(*) AS messages
--     FROM chat_message
--    WHERE role = 'assistant'
--    GROUP BY provider;

-- Expired sessions, for a cleanup job.
--
--   DELETE FROM auth_session WHERE expires_at < NOW();