#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
# GCP Cloud Cost Optimizer — one-shot setup script
# ──────────────────────────────────────────────────────────────────────────────
set -euo pipefail

echo ""
echo "═══════════════════════════════════════════════════"
echo "  GCP Cloud Cost Optimizer — Setup"
echo "═══════════════════════════════════════════════════"
echo ""

# 1. Python virtual environment
if [ ! -d ".venv" ]; then
    echo "[1/3] Creating Python virtual environment..."
    python3 -m venv .venv
fi

# 2. Install dependencies
echo "[2/3] Installing Python dependencies..."
.venv/bin/pip install --quiet --upgrade pip
.venv/bin/pip install --quiet -r requirements.txt
echo "  Done."

# 3. Auth check
echo ""
echo "[3/3] Authentication — choose ONE of the following:"
echo ""
echo "  OPTION A — Service Account Key (recommended for automation)"
echo "  ────────────────────────────────────────────────────────────"
echo "  1. In GCP Console → IAM → Service Accounts, create a SA with roles:"
echo "       - Compute Viewer"
echo "       - Monitoring Viewer"
echo "       - Cloud Asset Viewer (optional)"
echo "  2. Download the JSON key."
echo "  3. Copy it to:  ./credentials/service-account.json"
echo "     OR set env var:  export GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json"
echo ""
echo "  OPTION B — Your own GCP account (interactive)"
echo "  ────────────────────────────────────────────────────────────"
echo "  Run:  gcloud auth application-default login"
echo ""
echo "  OPTION C — Workload Identity / GCE metadata (if running on GCP)"
echo "  ────────────────────────────────────────────────────────────"
echo "  No action needed — ADC picks it up automatically."
echo ""
echo "═══════════════════════════════════════════════════"
echo "  Setup complete.  Run the analyzer with:"
echo ""
echo "    source .venv/bin/activate"
echo "    python main.py"
echo ""
echo "  Optional flags:"
echo "    --project <id>      override GCP project ID"
echo "    --running-only      skip STOPPED/TERMINATED VMs"
echo "    --no-memory         skip memory metrics (faster)"
echo "    --no-export         don't write CSV/JSON files"
echo "═══════════════════════════════════════════════════"
echo ""
