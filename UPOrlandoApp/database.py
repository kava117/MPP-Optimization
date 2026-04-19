"""
Local SQLite database for persisting user-added community centers.

The app loads the original 63 centers from weighted_centers.csv on first run,
and lets users add new ones that get saved here. On subsequent runs, the
original data + user additions are merged.
"""

from __future__ import annotations
import sqlite3
from pathlib import Path
import pandas as pd

DB_FILENAME = "uporlando_data.db"


def get_db_path(app_dir: Path) -> Path:
    """Return the database path inside the app's data directory."""
    return app_dir / DB_FILENAME


def init_db(db_path: Path):
    """Create the user_added_centers table if it doesn't exist."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_added_centers (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            name                TEXT NOT NULL,
            address             TEXT,
            zip_code            TEXT,
            lat                 REAL,
            lon                 REAL,
            bus_stop_count      INTEGER,
            median_income       REAL,
            population_size     REAL,
            pop_density         REAL,
            food_desert_score   INTEGER,
            added_by            TEXT,
            added_at            TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


def add_center(db_path: Path, center: dict):
    """Insert a new user-added center."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        INSERT INTO user_added_centers
        (name, address, zip_code, lat, lon, bus_stop_count,
         median_income, population_size, pop_density, food_desert_score, added_by)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        center.get("name"),
        center.get("address"),
        center.get("zip_code"),
        center.get("lat"),
        center.get("lon"),
        center.get("bus_stop_count"),
        center.get("median_income"),
        center.get("population_size"),
        center.get("pop_density"),
        center.get("food_desert_score"),
        center.get("added_by", ""),
    ))
    conn.commit()
    conn.close()


def load_user_centers(db_path: Path) -> pd.DataFrame:
    """Load all user-added centers as a dataframe."""
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query("SELECT * FROM user_added_centers", conn)
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df


def delete_center(db_path: Path, center_id: int):
    """Delete a user-added center by its id."""
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM user_added_centers WHERE id = ?", (center_id,))
    conn.commit()
    conn.close()


def merge_centers(original_df: pd.DataFrame, user_df: pd.DataFrame) -> pd.DataFrame:
    """
    Combine original centers CSV with user-added centers for scoring.
    Returns a unified dataframe with a 'source' column marking origin.
    """
    orig = original_df.copy()
    orig["source"] = "original"
    orig["user_id"] = None

    if user_df.empty:
        return orig

    # Rename user df columns to match original column names
    user = user_df.rename(columns={
        "median_income": "Orlando_Zip_Data_Clean_Median_Income",
        "population_size": "Orlando_Zip_Data_Clean_Population_Size",
        "pop_density": "Orlando_Zip_Data_Clean_Pop_Density_per_sqmi",
        "food_desert_score": "FL_FoodDesert_Scored_v2_food_desert_score",
        "id": "user_id",
    }).copy()
    user["source"] = "user_added"

    # Align columns — fill missing with NaN
    all_cols = list(set(orig.columns) | set(user.columns))
    for col in all_cols:
        if col not in orig.columns:
            orig[col] = None
        if col not in user.columns:
            user[col] = None

    combined = pd.concat([orig[all_cols], user[all_cols]], ignore_index=True)
    return combined
