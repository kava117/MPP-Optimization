#!/bin/bash
# FoodReach — Start Frontend
# Usage: ./start_frontend.sh

cd "$(dirname "$0")/frontend"

if ! command -v python3 &>/dev/null; then
  echo "Error: python3 not found."
  exit 1
fi

echo "============================================"
echo "  FoodReach Frontend"
echo "  http://localhost:8080"
echo "  Press Ctrl+C to stop"
echo "============================================"
python3 -m http.server 8080
