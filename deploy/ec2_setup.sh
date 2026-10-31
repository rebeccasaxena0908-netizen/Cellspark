#!/usr/bin/env bash
# CellSpark — EC2 setup for Amazon Linux 2023. Safe to re-run.
#
#   bash deploy/ec2_setup.sh https://github.com/<user>/Cellspark.git
#
# Installs system packages, clones (or updates) the repo in ~/cellspark,
# builds the Python 3.11 venv, downloads the MHCflurry models, and builds the
# frontend. It does NOT create backend/.env and contains no secrets: write that
# file yourself (copy backend/.env.example), then:
#
#   bash deploy/fetch_reference_data.sh        # proteome + PubMed index from S3
#   sudo cp deploy/cellspark.service /etc/systemd/system/
#   sudo systemctl daemon-reload && sudo systemctl enable --now cellspark
set -euo pipefail

REPO_URL="${1:?usage: ec2_setup.sh <git-repo-url>}"
APP_DIR="$HOME/cellspark"

# Python 3.11 is required: MHCflurry imports `pipes`, removed in Python 3.13.
sudo dnf install -y python3.11 python3.11-pip git nodejs npm

if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only          # re-run: update instead of clone
else
  git clone "$REPO_URL" "$APP_DIR"
fi

cd "$APP_DIR/backend"
[ -d venv ] || python3.11 -m venv venv      # keep an existing venv on re-run
./venv/bin/python -m pip install --upgrade pip
./venv/bin/python -m pip install -r requirements.txt

# ~1 GB of model weights; skipped by mhcflurry if already present.
./venv/bin/mhcflurry-downloads fetch models_class1_presentation

cd "$APP_DIR/frontend"
npm ci
npm run build                               # writes frontend/dist, served by FastAPI

echo
echo "Done. Next: create $APP_DIR/backend/.env, run deploy/fetch_reference_data.sh,"
echo "then install deploy/cellspark.service (see the header of this file)."
