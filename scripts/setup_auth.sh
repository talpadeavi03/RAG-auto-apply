#!/usr/bin/env bash
#
# Interactive setup script for Antigravity CLI and Browser Sessions
#
set -euo pipefail

echo "=========================================================="
echo "  RAG-AG-Apply: Authentication & Environment Setup"
echo "=========================================================="

# 1. Antigravity CLI Check & Login
echo ""
echo "[1/3] Checking Antigravity CLI (agy)..."
if command -v agy &>/dev/null; then
    echo "✓ agy is installed: $(agy --version)"
elif [ -f "$HOME/.local/bin/agy" ]; then
    echo "✓ agy found at $HOME/.local/bin/agy: $($HOME/.local/bin/agy --version)"
    export PATH="$HOME/.local/bin:$PATH"
else
    echo "Installing Antigravity CLI..."
    curl -fsSL https://antigravity.google/cli/install.sh | bash
fi

echo ""
echo "Note on Antigravity CLI Authentication:"
echo "To log in to agy in your terminal, simply execute:"
echo "    agy -p 'Hello'"
echo "It will provide a one-click OAuth URL. Once logged in, agy credentials remain cached."
echo ""

# 2. Browser Session Setup
echo "[2/3] Setting up Playwright Chromium..."
if [ -d ".venv" ]; then
    source .venv/bin/activate
fi
playwright install chromium

echo ""
echo "[3/3] Ready! To initialize knowledge base, run:"
echo "    python3 -m src.cli ingest --github <your-github-username>"
echo ""
