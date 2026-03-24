#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# LEAKPHANTOM v2.3.1 — Run Script
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# Activate venv
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "Run ./setup.sh first"
    exit 1
fi

# Set environment
export LEAKPHANTOM_HOST="${LEAKPHANTOM_HOST:-127.0.0.1}"
export LEAKPHANTOM_PORT="${LEAKPHANTOM_PORT:-8666}"

echo ""
echo "  ░▒▓ LEAKPHANTOM v2.3.1 — PHANTOM PROTOCOL ▓▒░"
echo ""
echo "  → http://${LEAKPHANTOM_HOST}:${LEAKPHANTOM_PORT}"
echo ""

# Run from backend directory so imports resolve
cd backend
python3 main.py
