#!/usr/bin/env bash
#
# Daily Automation Script for Profile Refresh & Job Applications
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "=== [$(date)] Starting Daily RAG-AG-Apply Job Cycle ==="

# 1. Activate Virtual Environment
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi

# 2. Ingest latest GitHub repositories & Resume
echo "Step 1: Refreshing RAG Knowledge Base..."
python3 -m src.cli ingest

# 3. Update & Refresh Naukri & LinkedIn Profiles
echo "Step 2: Refreshing Profiles (Naukri timestamp bump & LinkedIn summary)..."
python3 -m src.cli profile update --platform both

# 4. Run Job Application Pipeline
echo "Step 3: Running Auto-Apply (Naukri Direct & LinkedIn Easy Apply)..."
python3 -m src.cli apply --platform both --limit 15 --min-score 0.65

# 5. Output Status Summary
echo "Step 4: Status Summary..."
python3 -m src.cli status

echo "=== Daily Cycle Complete ==="
