#!/usr/bin/env bash
# macOS / Linux: GeNAIus yerel sunucusunu (FastAPI + Uvicorn, yalnız 127.0.0.1) başlatır.
# Kullanım: scripts/run_local.sh [--port 8765] [--allow-degraded-raw-data]
set -euo pipefail
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT=8765
ALLOW_DEGRADED=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --allow-degraded-raw-data) ALLOW_DEGRADED=1; shift ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done
if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then PY="$REPO_ROOT/.venv/bin/python"; else PY="$(command -v python3)"; fi

REQUIRED=(
  "data/raw/psi/experimental_tables/PSI-25/PSI-25_Experimental table_BASS-II.csv"
  "data/raw/psi/experimental_tables/PSI-69/PSI-69_Experimental table_FLEX.csv"
  "data/raw/nasa_docs/20150023456_flex.pdf"
  "data/raw/nasa_docs/20210011385_bass_ii.pdf"
  "data/raw/psi/matrices_and_readmes/PSI-25/PSI-25_Science Documents_BASS-II_ReadMe.docx"
)
MISSING=()
for rel in "${REQUIRED[@]}"; do [[ -f "$REPO_ROOT/$rel" ]] || MISSING+=("$rel"); done
if (( ${#MISSING[@]} )); then
  echo "WARNING: missing required raw files (${#MISSING[@]}): ${MISSING[*]}" >&2
  if (( ! ALLOW_DEGRADED )); then
    echo "Run 'python scripts/download_raw_data.py' or pass --allow-degraded-raw-data." >&2
    exit 1
  fi
fi
OPTIONAL=(
  "data/raw/psi/matrices_and_readmes/PSI-39/PSI-39_Science Documents_CFI_DataSummary_Spreadsheet_Jan2021.xlsx"
  "data/raw/psi/experimental_tables/PSI-39/PSI-39_Experimental table_CFI.csv"
  "data/raw/psi/experimental_tables/PSI-99/PSI-99_Experimental table_SAFFIRE-2.csv"
  "data/raw/psi/matrices_and_readmes/PSI-99/PSI-99_Science Documents_SAFFIRE-II Readme.docx"
)
MISSING_OPTIONAL=()
for rel in "${OPTIONAL[@]}"; do [[ -f "$REPO_ROOT/$rel" ]] || MISSING_OPTIONAL+=("$rel"); done
if (( ${#MISSING_OPTIONAL[@]} )); then
  echo "WARNING: optional PSI-39 CFI / PSI-99 SAFFIRE files missing (${#MISSING_OPTIONAL[@]}); those modules return 503 if queried." >&2
fi
if [[ -f "$REPO_ROOT/.env" ]]; then
  echo ".env detected locally (contents are not printed)."
else
  echo "No .env file found; server runs in deterministic non-LLM mode."
fi
export PYTHONPATH="$REPO_ROOT/src${PYTHONPATH:+:$PYTHONPATH}"
exec "$PY" -m genaius.prototype.server --repo-root "$REPO_ROOT" --port "$PORT"
