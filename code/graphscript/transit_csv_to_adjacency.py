"""
Public Transport Adjacency Matrix Builder
------------------------------------------
Reads a bus route edge list CSV and builds an N×N adjacency matrix
over all known community center nodes. An edge exists between two
centers if a direct bus route connects them AND the total_trip_miles
is within the configured threshold.

The resulting matrix is saved as a CSV in the same format as
driving_matrix.csv and walking_matrix.csv, making it a drop-in
input for dominating_set.py and priority_dominating_set.py.

Requirements:
    pip install pandas numpy

Usage (standalone):
    python transit_matrix.py

Usage (importable):
    from transit_matrix import TransitMatrixBuilder
    builder = TransitMatrixBuilder()
    builder.run()
"""

import re
import pandas as pd
import numpy as np

# ─── CONFIG ──────────────────────────────────────────────────────────────────

TRANSIT_CSV      = "data/transit_centers.csv"
CENTERS_CSV      = "data/centers_new.csv"        # Same source CSV used by csv_to_adjacency.py
OUTPUT_CSV       = "data/transit_matrix.csv"
THRESHOLD_MILES  = 3.5                     # Max total_trip_miles to create an edge

STOPWORDS = {"of", "the", "and", "at", "in", "a", "an", "for", "to", "by"}

# Same skip patterns as csv_to_adjacency.py — must stay in sync
SKIP_PATTERNS = [
    "universal", "lakeland", "hudson", "tampa", "this is", "this a", "n/a"
]


# ─── CLASS ───────────────────────────────────────────────────────────────────

class TransitMatrixBuilder:
    """
    Builds a public-transport adjacency matrix from a bus route edge list.

    The matrix dimensions and node ordering match the driving/walking matrices
    produced by csv_to_adjacency.py, so all three can be compared directly.
    """

    def __init__(
        self,
        transit_csv:  str = TRANSIT_CSV,
        centers_csv:  str = CENTERS_CSV,
        output_csv:   str = OUTPUT_CSV,
        threshold_miles: float = THRESHOLD_MILES,
    ):
        self.transit_csv     = transit_csv
        self.centers_csv     = centers_csv
        self.output_csv      = output_csv
        self.threshold_miles = threshold_miles

    # ── Node list loading ─────────────────────────────────────────────────────

    def _load_nodes(self) -> tuple[list[str], list[str]]:
        """
        Load and clean the centers CSV using the same logic as
        csv_to_adjacency.py. Returns (original_names, abbreviated_labels)
        in the same order as the driving/walking matrices.
        """
        df = pd.read_csv(self.centers_csv, skip_blank_lines=True)
        df.columns = [c.strip().lower() for c in df.columns]

        def is_skip(name):
            if not isinstance(name, str):
                return True
            n = name.strip().lower()
            if n in ("", "n/a"):
                return True
            return any(p in n for p in SKIP_PATTERNS)

        def clean_coord(val):
            try:
                return float(str(val).strip().rstrip(","))
            except Exception:
                return None

        df["lat"] = df["lat"].apply(clean_coord)
        df["lon"] = df["lon"].apply(clean_coord)
        df = df[~df["name"].apply(is_skip)].copy()
        df = df.dropna(subset=["lat", "lon"]).reset_index(drop=True)
        df = df[
            df["lat"].between(25, 32) & df["lon"].between(-86, -79)
        ].reset_index(drop=True)

        original_names = list(df["name"])
        labels = [
            self._abbreviate(i + 1, name)
            for i, name in enumerate(original_names)
        ]
        return original_names, labels

    def _abbreviate(self, index: int, name: str) -> str:
        """Mirrors the abbreviation logic in csv_to_adjacency.py exactly."""
        words = name.split()
        parts = []
        for w in words:
            clean = re.sub(r'[^a-zA-Z]', '', w)
            if clean.lower() in STOPWORDS or not clean:
                continue
            parts.append(clean[:3].capitalize() + ".")
        return f"{index}: {' '.join(parts)}"

    # ── Transit edge loading ──────────────────────────────────────────────────

    def _load_transit_edges(self) -> pd.DataFrame:
        """
        Load the transit CSV and filter to edges within the threshold.
        Returns a DataFrame with columns:
            origin_cc_name, dest_cc_name, total_trip_miles
        """
        df = pd.read_csv(self.transit_csv)
        df.columns = [c.strip().lower() for c in df.columns]

        required = {"origin_cc_name", "dest_cc_name", "total_trip_miles"}
        missing  = required - set(df.columns)
        if missing:
            raise ValueError(f"Transit CSV missing required columns: {missing}")

        # Filter by threshold
        before = len(df)
        df = df[df["total_trip_miles"] <= self.threshold_miles].copy()
        after  = len(df)
        print(f"  Transit edges: {before} total, {after} within "
              f"{self.threshold_miles} mi threshold, {before - after} dropped.")

        return df[["origin_cc_name", "dest_cc_name", "total_trip_miles"]]

    # ── Name matching ─────────────────────────────────────────────────────────

    def _build_name_index(
        self, original_names: list[str], transit_df: pd.DataFrame
    ) -> dict[str, int]:
        """
        Build a lookup from transit CSV center names -> node index.
        Matches exactly first, then falls back to case-insensitive strip.
        Reports any unmatched transit names so the user can investigate.
        """
        # Collect all unique names appearing in the transit CSV
        transit_names = set(transit_df["origin_cc_name"].tolist()) | \
                        set(transit_df["dest_cc_name"].tolist())

        name_to_idx = {}
        unmatched   = []

        for tname in transit_names:
            # Exact match
            if tname in original_names:
                name_to_idx[tname] = original_names.index(tname)
                continue

            # Case-insensitive stripped match
            tname_clean = tname.strip().lower()
            found = False
            for i, oname in enumerate(original_names):
                if oname.strip().lower() == tname_clean:
                    name_to_idx[tname] = i
                    found = True
                    break

            if not found:
                unmatched.append(tname)

        if unmatched:
            print(f"\n  WARNING: {len(unmatched)} transit center name(s) could "
                  f"not be matched to a node:")
            for nm in unmatched:
                print(f"    - '{nm}'")
            print("  These edges will be skipped. Check for typos between "
                  "your transit CSV and centers CSV.\n")

        return name_to_idx

    # ── Matrix builder ────────────────────────────────────────────────────────

    def _build_matrix(
        self,
        n: int,
        transit_df: pd.DataFrame,
        name_to_idx: dict[str, int],
    ) -> np.ndarray:
        """
        Populate an N×N adjacency matrix from the filtered transit edges.
        Matrix is symmetric (undirected) and self-loops are 0.
        Non-edges are 0.
        """
        adj = np.zeros((n, n), dtype=float)
        edges_added = 0
        edges_skipped = 0

        for _, row in transit_df.iterrows():
            oname = row["origin_cc_name"]
            dname = row["dest_cc_name"]
            dist  = round(float(row["total_trip_miles"]), 4)

            if oname not in name_to_idx or dname not in name_to_idx:
                edges_skipped += 1
                continue

            i = name_to_idx[oname]
            j = name_to_idx[dname]

            if i == j:
                continue  # no self-loops

            # If multiple routes connect the same pair, keep the shortest
            if adj[i][j] == 0 or dist < adj[i][j]:
                adj[i][j] = dist
                adj[j][i] = dist
                edges_added += 1

        print(f"  Matrix edges added: {edges_added}  |  skipped (unmatched): {edges_skipped}")
        return adj

    # ── Stats printer ─────────────────────────────────────────────────────────

    def _print_stats(
        self, adj: np.ndarray, labels: list[str], threshold: float
    ):
        n        = adj.shape[0]
        edges    = int(np.count_nonzero(adj) // 2)
        degrees  = (adj > 0).sum(axis=1)
        avg_deg  = degrees.mean()
        isolated = int((degrees == 0).sum())

        print(f"\n{'-'*55}")
        print(f"  TRANSIT MATRIX  (threshold: {threshold} mi)")
        print(f"{'-'*55}")
        print(f"  Nodes:          {n}")
        print(f"  Edges:          {edges}")
        print(f"  Avg degree:     {avg_deg:.2f}")
        print(f"  Isolated nodes: {isolated}")

        if isolated > 0:
            iso = [labels[i] for i in range(n) if degrees[i] == 0]
            print(f"\n  Isolated (no transit connection within threshold):")
            for nm in iso:
                print(f"    -> {nm}")

        print(f"\n  Connected pairs (edges):")
        for i in range(n):
            for j in range(i + 1, n):
                if adj[i][j] > 0:
                    print(f"    {labels[i]}  <->  {labels[j]}  "
                          f"({adj[i][j]:.2f} mi)")

    # ── Main entry point ──────────────────────────────────────────────────────

    def run(self) -> tuple[np.ndarray, list[str]]:
        """
        Full pipeline: load nodes -> load edges -> match names ->
        build matrix -> save CSV -> print stats.

        Returns (adj_matrix, labels) for direct use in downstream solvers.
        """
        print("Loading community center nodes...")
        original_names, labels = self._load_nodes()
        n = len(original_names)
        print(f"  {n} nodes loaded.")

        print("\nLoading transit edges...")
        transit_df = self._load_transit_edges()

        print("\nMatching transit names to node indices...")
        name_to_idx = self._build_name_index(original_names, transit_df)
        print(f"  {len(name_to_idx)} names matched successfully.")

        print("\nBuilding adjacency matrix...")
        adj = self._build_matrix(n, transit_df, name_to_idx)

        self._print_stats(adj, labels, self.threshold_miles)

        print(f"\nSaving matrix to {self.output_csv}...")
        pd.DataFrame(
            adj, index=original_names, columns=original_names
        ).to_csv(self.output_csv)
        print(f"  Saved: {self.output_csv}")

        print("\nAll done!")
        return adj, labels


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    builder = TransitMatrixBuilder()
    builder.run()