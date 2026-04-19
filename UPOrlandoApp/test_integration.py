"""
Integration test: simulate the full flow without the GUI.
- Load original data
- Score it
- Add a user center to the DB
- Merge + re-score
- Verify the user center shows up in rankings
"""
from pathlib import Path
import pandas as pd

import scoring
import database

APP_DIR = Path(__file__).parent
CSV = APP_DIR / "weighted_centers.csv"
DB = APP_DIR / "test_integration.db"

# Clean slate
if DB.exists():
    DB.unlink()

database.init_db(DB)

# Step 1: score original data
original = pd.read_csv(CSV)
print(f"Loaded {len(original)} original centers")

ranked = scoring.rank_centers(original)
eligible = ranked['eligible'].sum()
print(f"Original: {eligible} eligible, top center: {ranked.iloc[0]['name']} "
      f"(score {ranked.iloc[0]['total_score']})")

# Step 2: add a hypothetical high-priority center
print("\nAdding test center 'Hypothetical High-Need Site' ...")
database.add_center(DB, {
    "name": "Hypothetical High-Need Site",
    "address": "Test Address",
    "zip_code": "32805",
    "lat": 28.5383,
    "lon": -81.3792,
    "bus_stop_count": 1,       # low access  -> 3 pts
    "median_income": 30_000,   # very low    -> 3 pts
    "population_size": 60_000, # large       -> 3 pts
    "pop_density": 6_000,      # dense       -> 3 pts
    "food_desert_score": 2,    # confirmed   -> 3 pts
    "added_by": "integration_test",
})
# Expected: 15/15 (perfect score)

# Step 3: reload and re-score
user_df = database.load_user_centers(DB)
print(f"User-added centers in DB: {len(user_df)}")

combined = database.merge_centers(original, user_df)
print(f"Combined dataset size: {len(combined)}")

reranked = scoring.rank_centers(combined)
top = reranked.iloc[0]
print(f"\nNew top center: {top['name']} (score {top['total_score']}, "
      f"source: {top.get('source', 'unknown')})")

# Verify the test center appears at rank 1 with a perfect score
if top['name'] == "Hypothetical High-Need Site" and top['total_score'] == 15:
    print("\n✓ Integration test PASSED")
else:
    print("\n✗ Integration test FAILED")
    print(reranked.head())

# Cleanup
DB.unlink()
print("(test DB cleaned up)")
