#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
# LEAKPHANTOM v2.3.1 — Setup Script
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${GREEN}"
cat << 'BANNER'
    ██╗     ███████╗ █████╗ ██╗  ██╗██████╗ ██╗  ██╗ █████╗ ███╗   ██╗████████╗ ██████╗ ███╗   ███╗
    ██║     ██╔════╝██╔══██╗██║ ██╔╝██╔══██╗██║  ██║██╔══██╗████╗  ██║╚══██╔══╝██╔═══██╗████╗ ████║
    ██║     █████╗  ███████║█████╔╝ ██████╔╝███████║███████║██╔██╗ ██║   ██║   ██║   ██║██╔████╔██║
    ██║     ██╔══╝  ██╔══██║██╔═██╗ ██╔═══╝ ██╔══██║██╔══██║██║╚██╗██║   ██║   ██║   ██║██║╚██╔╝██║
    ███████╗███████╗██║  ██║██║  ██╗██║     ██║  ██║██║  ██║██║ ╚████║   ██║   ╚██████╔╝██║ ╚═╝ ██║
    ╚══════╝╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝   ╚═╝    ╚═════╝ ╚═╝     ╚═╝
BANNER
echo -e "${NC}"
echo -e "${CYAN}v2.3.1 — PHANTOM PROTOCOL SETUP${NC}"
echo ""

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# ── Check Python ──
echo -e "${GREEN}[1/4]${NC} Checking Python 3.12+ ..."
if command -v python3 &>/dev/null; then
    PY_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    echo -e "  Found Python ${PY_VER}"
else
    echo -e "${RED}  Python 3 not found. Please install Python 3.12+${NC}"
    exit 1
fi

# ── Create venv ──
echo -e "${GREEN}[2/4]${NC} Creating virtual environment ..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo -e "  Created venv/"
else
    echo -e "  venv/ already exists"
fi

source venv/bin/activate

# ── Install Python deps ──
echo -e "${GREEN}[3/4]${NC} Installing Python dependencies ..."
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo -e "  Dependencies installed"

# ── Optional: Check for capture tools ──
echo -e "${GREEN}[4/4]${NC} Checking optional capture tools ..."

check_tool() {
    if command -v "$1" &>/dev/null; then
        echo -e "  ${GREEN}✓${NC} $1 found"
    else
        echo -e "  ${YELLOW}~${NC} $1 not found (demo mode will be used for $2)"
    fi
}

check_tool "airmon-ng" "WiFi monitor mode"
check_tool "tshark" "packet capture"
check_tool "hcitool" "Bluetooth"

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
echo -e "${GREEN}  Setup complete! Run ${CYAN}./run.sh${GREEN} to start LEAKPHANTOM${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════════════${NC}"
