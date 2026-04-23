#!/bin/bash
# FoodReach — Start Backend
# Usage: ./start_backend.sh

cd "$(dirname "$0")/backend"

# Check Python is available
if ! command -v python3 &>/dev/null; then
  echo "Error: python3 not found. Please install Python 3.9+."
  exit 1
fi

# Check dependencies
python3 -c "import flask, geopandas, pulp, networkx" 2>/dev/null || {
  echo "Missing dependencies. Run: pip install -r requirements.txt"
  exit 1
}

echo "============================================"
echo "  FoodReach Backend"
echo "  http://localhost:5000"
echo "  Press Ctrl+C to stop"
echo "============================================"
python3 app.py
