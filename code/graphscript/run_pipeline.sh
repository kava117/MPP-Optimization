#!/usr/bin/env bash
set -euo pipefail

# ─── COLORS ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
RESET='\033[0m'

step()  { echo -e "\n${CYAN}${BOLD}==> $*${RESET}"; }
ok()    { echo -e "${GREEN}✓ $*${RESET}"; }
warn()  { echo -e "${YELLOW}! $*${RESET}"; }
fail()  { echo -e "${RED}✗ $*${RESET}"; exit 1; }

# ─── DEPENDENCY CHECK ─────────────────────────────────────────────────────────
REQUIRED_PACKAGES=(requests pandas numpy matplotlib networkx pulp)

step "Checking Python dependencies..."

MISSING=()
for pkg in "${REQUIRED_PACKAGES[@]}"; do
    if python3 -c "import ${pkg}" 2>/dev/null; then
        ok "${pkg} already installed"
    else
        warn "${pkg} not found — will install"
        MISSING+=("${pkg}")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    step "Installing missing packages: ${MISSING[*]}"
    pip install --quiet "${MISSING[@]}" || fail "pip install failed"
    ok "All packages installed"
else
    ok "All dependencies satisfied"
fi

step "Checking R dependency (required for key player analysis)..."
if ! command -v Rscript &>/dev/null; then
    fail "Rscript not found — install R and run: Rscript -e \"install.packages('keyplayer', repos='https://cran.r-project.org')\""
fi
if ! Rscript -e "library(keyplayer)" &>/dev/null 2>&1; then
    fail "R package 'keyplayer' not installed — run: Rscript -e \"install.packages('keyplayer', repos='https://cran.r-project.org')\""
fi
ok "R and keyplayer package available"

# ─── PIPELINE ─────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

step "Step 1/5 — Driving & Walking Adjacency Matrices"
python3 "${SCRIPT_DIR}/csv_to_adjacency.py" || fail "csv_to_adjacency.py failed"
ok "Driving and walking matrices written"

step "Step 2/5 — Transit Adjacency Matrix"
python3 "${SCRIPT_DIR}/transit_csv_to_adjacency.py" || fail "transit_csv_to_adjacency.py failed"
ok "Transit matrix written"

step "Step 3/5 — Minimum Dominating Set (ILP)"
python3 "${SCRIPT_DIR}/domination.py" || fail "domination.py failed"
ok "Domination graphs written"

step "Step 4/5 — Priority Dominating Set"
python3 "${SCRIPT_DIR}/priority-domination.py" || fail "priority-domination.py failed"
ok "Priority domination graphs written"

step "Step 5/5 — Key Player Analysis"
python3 "${SCRIPT_DIR}/keyplayer_viz.py" || fail "keyplayer_viz.py failed"
ok "Key player graphs written"

echo -e "\n${GREEN}${BOLD}Pipeline complete.${RESET}"
