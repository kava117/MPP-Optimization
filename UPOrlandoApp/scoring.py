"""
UpOrlando Community Center Priority Scoring Engine
---------------------------------------------------
Adapted from priority-domination.py (group leader's script).

Scores community centers on 5 factors (each 1-3 points, max 15 total):
    - Median income        (inverted: lower = higher priority)
    - Population size      (larger = higher priority)
    - Population density   (denser = higher priority)
    - Food desert score    (more severe = higher priority)
    - Bus stop count       (binary inverted: <5 stops = higher priority)

Note: The "degree" factor from the original script is NOT included here
(it requires the graph connectivity matrices). This is a v1 simplification.

Centers missing core demographic data (income/population/density) are
flagged as ineligible and not ranked.
"""

from __future__ import annotations
import pandas as pd

# ─── Scoring thresholds (from group leader's script) ───────────────────────────
INCOME_LOW  = 45_000
INCOME_MID  = 75_000
POP_LOW     = 30_000
POP_MID     = 50_000
DENSITY_LOW = 2_000
DENSITY_MID = 5_000
BUS_THRESHOLD = 5

# Max possible score (5 factors × 3 points each)
MAX_SCORE = 15


def _score_income(val) -> int | None:
    """Lower income = higher priority. Inverted scale."""
    if pd.isna(val):
        return None
    val = float(val)
    if val < INCOME_LOW:
        return 3
    if val < INCOME_MID:
        return 2
    return 1


def _score_population(val) -> int | None:
    """Larger population = higher priority."""
    if pd.isna(val):
        return None
    val = float(val)
    if val < POP_LOW:
        return 1
    if val < POP_MID:
        return 2
    return 3


def _score_density(val) -> int | None:
    """Denser = higher priority."""
    if pd.isna(val):
        return None
    val = float(val)
    if val < DENSITY_LOW:
        return 1
    if val < DENSITY_MID:
        return 2
    return 3


def _score_food_desert(val) -> int:
    """Food desert score 0/1/2 maps to 1/2/3. Missing defaults to 1 (no food desert)."""
    if pd.isna(val):
        return 1
    val = int(float(val))
    if val == 0:
        return 1
    if val == 1:
        return 2
    return 3


def _score_bus_stops(val) -> int:
    """Fewer bus stops = higher priority (less transit access = more need)."""
    if pd.isna(val):
        return 3  # unknown assumed low access
    return 1 if float(val) >= BUS_THRESHOLD else 3


# ─── Column normalization (handles her messy field names) ─────────────────────

COLUMN_MAP = {
    # Handles both the full QGIS export names and short versions
    "median_income": "median_income",
    "medianincome": "median_income",
    "orlando_zip_data_clean_median_income": "median_income",
    "population_size": "population_size",
    "populationsize": "population_size",
    "pop_size": "population_size",
    "orlando_zip_data_clean_population_size": "population_size",
    "pop_density": "pop_density",
    "popdensity": "pop_density",
    "density": "pop_density",
    "orlando_zip_data_clean_pop_density_per_sqmi": "pop_density",
    "food_desert_score": "food_desert_score",
    "fooddesert": "food_desert_score",
    "fl_fooddesert_scored_v2_food_desert_score": "food_desert_score",
    "bus_stop_count": "bus_stop_count",
    "busstop": "bus_stop_count",
}


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase column names and map them to canonical short names."""
    df = df.copy()
    df.columns = [c.strip().lower() for c in df.columns]
    rename = {}
    for col in df.columns:
        if col in COLUMN_MAP:
            rename[col] = COLUMN_MAP[col]
        else:
            # Fuzzy match on substrings
            for key, canonical in COLUMN_MAP.items():
                if key in col and canonical not in rename.values():
                    rename[col] = canonical
                    break
    return df.rename(columns=rename)


# ─── Main scoring function ────────────────────────────────────────────────────

def score_centers(df: pd.DataFrame) -> pd.DataFrame:
    """
    Score a dataframe of community centers and return it with scoring columns.

    Input must have columns (after normalization):
        name, lat, lon, median_income, population_size, pop_density,
        food_desert_score, bus_stop_count

    Returns df with new columns:
        s_income, s_population, s_density, s_food_desert, s_bus_stops,
        total_score, eligible, priority_tier
    """
    df = normalize_columns(df)

    s_income = df["median_income"].apply(_score_income)
    s_pop    = df["population_size"].apply(_score_population)
    s_dens   = df["pop_density"].apply(_score_density)
    s_food   = df["food_desert_score"].apply(_score_food_desert)
    s_bus    = df["bus_stop_count"].apply(_score_bus_stops)

    # Eligibility: core demographics must be present
    eligible = s_income.notna() & s_pop.notna() & s_dens.notna()

    # Total score (fill None with 0 for ineligible rows)
    total = (
        s_income.fillna(0).astype(int)
        + s_pop.fillna(0).astype(int)
        + s_dens.fillna(0).astype(int)
        + s_food.astype(int)
        + s_bus.astype(int)
    )
    # Ineligible rows get score 0
    total = total.where(eligible, 0)

    # Priority tiers based on score (only meaningful for eligible centers)
    def tier(score, is_eligible):
        if not is_eligible:
            return "Ineligible (missing data)"
        if score >= 12:
            return "High priority"
        if score >= 9:
            return "Medium priority"
        return "Low priority"

    out = df.copy()
    out["s_income"]       = s_income.fillna(0).astype(int)
    out["s_population"]   = s_pop.fillna(0).astype(int)
    out["s_density"]      = s_dens.fillna(0).astype(int)
    out["s_food_desert"]  = s_food.astype(int)
    out["s_bus_stops"]    = s_bus.astype(int)
    out["total_score"]    = total.astype(int)
    out["eligible"]       = eligible
    out["priority_tier"]  = [
        tier(s, e) for s, e in zip(total, eligible)
    ]
    return out


def rank_centers(df: pd.DataFrame) -> pd.DataFrame:
    """Score and sort centers by total_score (descending). Ineligible at the end."""
    scored = score_centers(df)
    # Sort: eligible first, then by total_score desc
    scored = scored.sort_values(
        by=["eligible", "total_score"],
        ascending=[False, False],
    ).reset_index(drop=True)
    return scored


# ─── CLI entry point for testing ──────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "weighted_centers.csv"
    df = pd.read_csv(path)
    ranked = rank_centers(df)

    print(f"\nScored {len(ranked)} community centers "
          f"({ranked['eligible'].sum()} eligible, "
          f"{(~ranked['eligible']).sum()} ineligible)\n")

    print(f"{'Rank':<5} {'Name':<40} {'Score':<6} {'Tier':<26} {'Breakdown'}")
    print("─" * 120)
    for i, row in ranked.iterrows():
        if not row["eligible"]:
            print(f"{'—':<5} {row['name'][:38]:<40} {'—':<6} {row['priority_tier']:<26} missing data")
            continue
        bd = (f"inc={row['s_income']} pop={row['s_population']} "
              f"den={row['s_density']} food={row['s_food_desert']} "
              f"bus={row['s_bus_stops']}")
        print(f"{i+1:<5} {row['name'][:38]:<40} "
              f"{row['total_score']:<6} {row['priority_tier']:<26} {bd}")
