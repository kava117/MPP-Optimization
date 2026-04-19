# UpOrlando Community Center Priority Analyzer

A local Windows desktop application for scoring and ranking community centers
in the Orlando metro area based on food access and transit equity criteria.

## What it does

Takes a list of community centers with demographic and transit data, scores
each one on 5 weighted factors, and produces a ranked list of the highest-
priority sites for food access interventions.

Users can add new candidate community centers and re-run the analysis to
see how they stack up.

## Features

- **Rankings tab**: Sortable table of all centers with scores and breakdown
- **Map tab**: Interactive Folium map color-coded by priority tier
- **Add Site tab**: Form to add new candidate centers (saved locally)
- **Export**: Save current rankings as CSV

## Setup (development)

Requirements: Python 3.10+

```bash
cd uporlando_app
pip install -r requirements.txt
python main.py
```

The app will open a window with three tabs. The analysis runs automatically
on startup using `weighted_centers.csv`.

User-added centers are saved to `uporlando_data.db` (SQLite) in the app
directory, so they persist between sessions.

## Scoring criteria

Each center scores 1–3 points on each of these factors (max 15 total):

| Factor | 1 point | 2 points | 3 points |
|---|---|---|---|
| Median income | ≥ $75K | $45–75K | < $45K |
| Population size | < 30K | 30–50K | ≥ 50K |
| Population density | < 2K/sq mi | 2–5K/sq mi | ≥ 5K/sq mi |
| Food desert score | 0 (none) | 1 (partial) | 2 (confirmed) |
| Bus stop count | ≥ 5 stops | — | < 5 stops |

Priority tiers: High (12–15), Medium (9–11), Low (6–8).

Centers missing core demographic data (income/population/density) are
flagged as ineligible and not ranked.

## Packaging as Windows .exe

The app is designed to be distributed to UpOrlando users as a single `.exe`
that runs without requiring Python installation.

```bash
# Install PyInstaller
pip install pyinstaller

# Build the .exe (from uporlando_app/ directory)
pyinstaller --name UpOrlandoAnalyzer --windowed --onefile ^
    --add-data "weighted_centers.csv;." ^
    --collect-all folium ^
    --collect-all branca ^
    main.py
```

The packaged `.exe` will be in `dist/UpOrlandoAnalyzer.exe`. Test it on
a clean Windows machine before distributing.

**Note:** PyInstaller builds for the OS it runs on. The `.exe` must be
built on Windows. If developing on Linux/Mac, use a Windows VM or
GitHub Actions.

## File structure

```
uporlando_app/
├── main.py                    # GUI application entry point
├── scoring.py                 # Scoring engine (adapted from priority-domination.py)
├── database.py                # SQLite persistence for user additions
├── weighted_centers.csv       # Original 63 community centers data
├── driving_matrix.csv         # (For future v2: graph dominating set)
├── walking_matrix.csv         # (For future v2: graph dominating set)
├── requirements.txt           # Python dependencies
└── README.md                  # This file
```

## Future improvements (v2 candidates)

- Re-integrate the graph dominating set algorithm from the original script
  (requires travel matrices — for now, adding new centers can't compute
  travel times automatically)
- Address geocoding (auto-fill lat/lon from typed address using Nominatim)
- Auto-fill demographic data when a zip code is entered (from pre-loaded
  zip lookup table)
- Multi-user sync via shared Dropbox/Google Drive file
- Configurable weight sliders so users can experiment with non-equal weighting

## Credits

Scoring methodology: adapted from `priority-domination.py` by the
UpOrlando student group leader.
