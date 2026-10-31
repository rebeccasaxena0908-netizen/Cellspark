#!/usr/bin/env bash
# Pull the reference data the app reads from disk out of S3 onto this machine.
#
# ONE-TIME UPLOAD, from your laptop (run in the repo root, with AWS credentials
# exported in that shell and S3_BUCKET set):
#
#   aws s3 cp backend/data/uniprot_human.fasta s3://$S3_BUCKET/reference/uniprot_human.fasta
#   aws s3 cp backend/data/corpus.json         s3://$S3_BUCKET/reference/corpus.json
#   aws s3 sync backend/data/chroma            s3://$S3_BUCKET/reference/chroma
#
# Then on EC2 (S3_BUCKET and AWS_* come from backend/.env or the instance role):
#
#   set -a; source backend/.env; set +a; bash deploy/fetch_reference_data.sh
#
# Destinations match the paths in the code: tier1/gene_index.py (UNIPROT_PATH),
# tier4/retriever.py (CORPUS_PATH, CHROMA_PATH) — all under backend/data/.
set -euo pipefail

: "${S3_BUCKET:?set S3_BUCKET}"
DATA_DIR="$(cd "$(dirname "$0")/.." && pwd)/backend/data"
mkdir -p "$DATA_DIR/chroma"

aws s3 cp   "s3://$S3_BUCKET/reference/uniprot_human.fasta" "$DATA_DIR/uniprot_human.fasta"
aws s3 cp   "s3://$S3_BUCKET/reference/corpus.json"         "$DATA_DIR/corpus.json"
aws s3 sync "s3://$S3_BUCKET/reference/chroma"              "$DATA_DIR/chroma"

echo "Reference data is in $DATA_DIR"
