# CellSpark

A personalised digital compiler for synthetic mRNA cancer vaccines.

CellSpark takes a cancer patient's tumour mutation file and produces a ranked
list of candidate vaccine targets, a codon-optimised mRNA construct for the
leading candidate, a literature-grounded explanation of the result, and a lipid
nanoparticle formulation worksheet.

> **Research tool.** Every output is a computational prediction. Nothing
> produced by this system has been validated in a laboratory, in an animal
> model, or in a human trial. It makes no clinical recommendations.

Specialization Project (BCA482-5) · CHRIST (Deemed to be University), Delhi NCR
Rebecca Saxena · Tanishka Pandey · Arunima Soni
Guided by Prof. Neha Saini and Prof. Neelam Yadav

---

## What it does

| Tier | Stage | Output |
|---|---|---|
| 1 | **Genomic search** — parses the MAF, generates 8–11mer peptide windows, screens them against 20,431 human proteins (11.4M residues) with hand-written KMP and Boyer–Moore | Tumour-specific candidates |
| 2 | **Target selection** — MHCflurry 2.2 scores peptide–MHC binding across the patient's HLA alleles; wild-type counterparts scored for agretopicity | Ranked targets with IC50 |
| 3 | **mRNA design** — codon optimisation against Kazusa human usage, uridine depletion, back-translation verification | Synthesis-ready construct |
| 4 | **Clinical copilot** — retrieval over 618 PubMed abstracts, generation grounded in platform facts, run data and retrieved passages | Cited explanation |
| 5 | **Formulation** — molecular weight from base composition, lipid masses at a given N/P ratio | Formulation worksheet |

Plus researcher accounts, run history, and a MySQL database recording every
analysis.

---

## Requirements

- **Python 3.11** — required, not optional. MHCflurry imports the `pipes`
  module, removed from the standard library in 3.13.
- **Node.js 18+**
- **MySQL or MariaDB** (XAMPP is fine)
- ~2 GB disk for the UniProt proteome and MHCflurry model weights

---

## Setup

### 1. Database

Start MySQL, then:

```bash
cd backend
mysql -u root < schema.sql
mysql -u root < schema_formulation.sql
```

Create an application user — the application never connects as root, and
deliberately has no schema privileges:

```bash
mysql -u root -e "
CREATE USER IF NOT EXISTS 'cellspark'@'localhost' IDENTIFIED BY 'change_me';
GRANT SELECT, INSERT, UPDATE, DELETE ON cellspark.* TO 'cellspark'@'localhost';
FLUSH PRIVILEGES;"
```

### 2. Backend

```bash
cd backend
python3.11 -m venv venv
source venv/bin/activate
python -m pip install -r requirements.txt
mhcflurry-downloads fetch models_class1_presentation
```

Copy `.env.example` to `.env` and fill it in:

```
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=cellspark
MYSQL_PASSWORD=change_me
MYSQL_DB=cellspark

GEMINI_API_KEY=            # optional — copilot falls back to templates
GEMINI_MODEL=gemini-3.5-flash-lite
CELLSPARK_LLM=gemini       # or 'off'
```

`.env` is gitignored and must stay that way.

### 3. Reference data

The UniProt human proteome FASTA goes in `backend/data/`. The PubMed corpus and
ChromaDB index build on first use; the first copilot query after a fresh clone
takes a few minutes while 618 abstracts are embedded.

### 4. Run

```bash
# terminal 1
cd backend && source venv/bin/activate
uvicorn app.main:app --reload --reload-dir app

# terminal 2
cd frontend && npm install && npm run dev
```

Open **http://localhost:5173**. Sign up, then upload a MAF.

Sample files are in `backend/tests/fixtures/`.

**First run is slow.** MHCflurry takes a few seconds to load its weights, and
on macOS the very first execution of the venv's binary wheels triggers
notarisation checks that can take several minutes. Subsequent runs are fast.
Start the backend and make one request before demonstrating.

---

## Tests

```bash
cd backend && source venv/bin/activate
pytest
```

~170 tests. Database tests skip if MySQL is unreachable. The suite runs with
`socket.connect` patched to raise, so no test touches the network.

```bash
python tests/benchmark.py    # algorithm timings
```

---

## Architecture

```
backend/
  app/
    tier1/   string_match.py, maf_parser.py, proteome.py, gene_index.py
    tier2/   binding.py
    tier3/   codon_tables.py, optimise.py
    tier4/   retriever.py, copilot.py, llm.py, context.py, platform_facts.py
    tier5/   constants.py, formulate.py
    main.py, pipeline.py, db.py, models.py, auth.py, records.py, upload.py
  schema.sql, schema_formulation.sql
  tests/
frontend/
  src/components/, src/lib/
```

**Design notes**

- The three matchers are implemented from first principles. Naive search is
  retained as a correctness oracle for the other two.
- String matching performs *self-tolerance screening* — proving a peptide is
  absent from the healthy proteome — not mutation calling, which happens
  upstream.
- The copilot generates only from the platform description, the run's own data
  and retrieved abstracts. It states plainly when none of those answers the
  question, and the interface shows whether an answer was generated or fell
  back to templates.
- Cross-check coverage is decided in code by counting gene mentions, never
  inferred from similarity scores. Dense retrieval cannot answer a membership
  question — see the report.
- Formulation values carry a provenance class: computed, published constant, or
  user assumption. The dose is an input, never a recommendation.
- Passwords and session tokens are both hashed. The application database user
  has no DDL privileges.

---

## Input format

MAF only — a tab-separated file with at minimum:

```
Hugo_Symbol  Chromosome  Start_Position  Variant_Classification
Variant_Type  Tumor_Sample_Barcode  HGVSp_Short
```

Only `Missense_Mutation` rows are processed. VCF and FASTA are not supported.

---

## Known limitations

- Self-tolerance screening is exact-match, so near-self peptides are not
  detected. This is the largest gap in the safety model.
- MHC Class I only; no Class II, no proteasomal processing model.
- No RNA secondary structure prediction.
- Expired sessions are rejected but never purged.
- No encryption at rest.

## Licence and data

Reference data belongs to its respective sources: UniProt, TCGA, IEDB, Kazusa,
PubMed Central. Patient mutation files are never committed; `backend/data/` is
gitignored.
