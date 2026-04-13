"""
Priority-Weighted Greedy Dominating Set Solver
------------------------------------------------
Reads driving and walking adjacency matrix CSVs and a metadata CSV,
computes a priority score for each node based on socioeconomic factors,
then finds a greedy dominating set by selecting highest-priority nodes first.

Priority factors (equal weight, each scored 1-3):
    - Median income        (inverted: lower income = higher priority)
    - Population size      (larger = higher priority)
    - Population density   (denser = higher priority)
    - Food desert score    (more severe = higher priority)
    - Bus stop count       (binary inverted: <5 stops = higher priority)
    - Nearby nodes/degree  (higher degree = higher priority, dynamic bins)

Nodes with missing income/population/density data are skipped.
Ties in priority are broken by degree (higher degree wins).

Requirements:
    pip install pandas numpy matplotlib networkx

Usage (standalone):
    python priority_dominating_set.py

Usage (importable):
    from priority_dominating_set import PriorityDominatingSetSolver
    solver = PriorityDominatingSetSolver()
    solver.run()
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import networkx as nx

STOPWORDS = {"of", "the", "and", "at", "in", "a", "an", "for", "to", "by"}

def abbreviate_label(index: int, name: str) -> str:
    """Used only for graph visualization. Full names are stored in the matrix CSVs."""
    words = name.split()
    parts = [w[:3].capitalize() + "." for w in words if w.lower() not in STOPWORDS]
    return f"{index}: {' '.join(parts)}"


# ─── CONFIG ──────────────────────────────────────────────────────────────────

DRIVING_MATRIX_CSV = "driving_matrix.csv"
WALKING_MATRIX_CSV = "walking_matrix.csv"
METADATA_CSV       = "centers.csv"

OUTPUT_DIR = ""  # Set to e.g. "outputs/" if needed

# Fixed scoring thresholds
INCOME_LOW    = 45_000   # < this  -> score 3 (high priority)
INCOME_MID    = 75_000   # < this  -> score 2, else score 1

POP_LOW       = 30_000   # < this  -> score 1
POP_MID       = 50_000   # < this  -> score 2, else score 3

DENSITY_LOW   = 2_000    # < this  -> score 1
DENSITY_MID   = 5_000    # < this  -> score 2, else score 3

BUS_THRESHOLD = 5        # >= this -> score 1 (good access), else score 3

# Node colors
COLOR_DOMINATING = "#e63946"   # Red    — in the dominating set
COLOR_SKIPPED    = "#aaaaaa"   # Grey   — missing data, skipped
COLOR_REGULAR    = "#f0a500"   # Orange — regular node
COLOR_EDGE       = "#4a90d9"   # Blue   — edges


# ─── CLASS ───────────────────────────────────────────────────────────────────

class PriorityDominatingSetSolver:
    """
    Greedy priority-weighted dominating set solver.

    Algorithm:
        1. Score each eligible node across 6 factors (1-3 each, max score 18).
        2. Sort nodes by score descending; break ties by degree descending.
        3. Greedily select the highest-priority undominated node, mark it and
           all its neighbors as dominated, repeat until all eligible nodes
           are dominated.
        4. Any skipped (missing-data) nodes are dominated passively — if a
           neighbor covers them, great; otherwise they remain undominated
           (flagged in output).
    """

    def __init__(
        self,
        driving_csv:  str = DRIVING_MATRIX_CSV,
        walking_csv:  str = WALKING_MATRIX_CSV,
        metadata_csv: str = METADATA_CSV,
        output_dir:   str = OUTPUT_DIR,
    ):
        self.driving_csv  = driving_csv
        self.walking_csv  = walking_csv
        self.metadata_csv = metadata_csv
        self.output_dir   = output_dir

    # ── Data loading ──────────────────────────────────────────────────────────

    def _load_matrix(self, filepath: str) -> tuple[np.ndarray, list[str]]:
        """Load adjacency matrix CSV. Returns (adj_matrix, labels)."""
        df = pd.read_csv(filepath, index_col=0)
        labels = list(df.index)
        adj = df.to_numpy(dtype=float)
        return adj, labels

    def _load_metadata(self) -> pd.DataFrame:
        """Load and clean metadata CSV."""
        df = pd.read_csv(self.metadata_csv, skip_blank_lines=True)
        df.columns = [c.strip().lower() for c in df.columns]

        # Normalize column names to short versions
        col_map = {}
        for c in df.columns:
            if "median_income" in c or "medianincome" in c:
                col_map[c] = "median_income"
            elif "population_size" in c or "populationsize" in c or "pop_size" in c:
                col_map[c] = "population_size"
            elif "pop_density" in c or "popdensity" in c or "density" in c:
                col_map[c] = "pop_density"
            elif "food_desert" in c or "fooddesert" in c:
                col_map[c] = "food_desert_score"
            elif "bus_stop" in c or "busstop" in c:
                col_map[c] = "bus_stop_count"
        df = df.rename(columns=col_map)

        # Keep only the columns we need
        keep = ["name", "median_income", "population_size",
                 "pop_density", "food_desert_score", "bus_stop_count"]
        df = df[[c for c in keep if c in df.columns]].copy()
        return df

    # ── Label matching ────────────────────────────────────────────────────────

    def _match_label_to_metadata(
        self, label: str, meta_df: pd.DataFrame
    ) -> pd.Series | None:
        """
        Match an adjacency matrix label (full center name) to a metadata row
        by exact name lookup. Returns the matching row or None if no match.
        """
        row = meta_df[meta_df["name"] == label]
        if row.empty:
            return None
        return row.iloc[0]

    # ── Scoring ───────────────────────────────────────────────────────────────

    def _score_income(self, val) -> int:
        if pd.isna(val):
            return None
        val = float(val)
        if val < INCOME_LOW:
            return 3
        elif val < INCOME_MID:
            return 2
        return 1

    def _score_population(self, val) -> int:
        if pd.isna(val):
            return None
        val = float(val)
        if val < POP_LOW:
            return 1
        elif val < POP_MID:
            return 2
        return 3

    def _score_density(self, val) -> int:
        if pd.isna(val):
            return None
        val = float(val)
        if val < DENSITY_LOW:
            return 1
        elif val < DENSITY_MID:
            return 2
        return 3

    def _score_food_desert(self, val) -> int:
        if pd.isna(val):
            return 1   # unknown -> treat as no food desert
        val = int(float(val))
        if val == 0:
            return 1
        elif val == 1:
            return 2
        return 3

    def _score_bus_stops(self, val) -> int:
        if pd.isna(val):
            return 3   # unknown -> assume low access
        return 1 if float(val) >= BUS_THRESHOLD else 3

    def _score_degree(self, degree: int, all_degrees: list[int]) -> int:
        """Bin degree dynamically into thirds of the degree distribution."""
        sorted_d = sorted(all_degrees)
        n = len(sorted_d)
        low_thresh  = sorted_d[n // 3]
        high_thresh = sorted_d[(2 * n) // 3]
        if degree <= low_thresh:
            return 1
        elif degree <= high_thresh:
            return 2
        return 3

    def _compute_priorities(
        self,
        adj: np.ndarray,
        labels: list[str],
        meta_df: pd.DataFrame,
    ) -> dict[int, dict]:
        """
        Compute priority scores for all nodes.
        Returns dict: node_index -> {
            'score': int,
            'degree': int,
            'eligible': bool,
            'breakdown': dict,
            'name': str
        }
        """
        n = len(labels)
        degrees = [(adj[i] > 0).sum() for i in range(n)]
        all_degrees = list(degrees)

        priorities = {}
        for i, label in enumerate(labels):
            degree = int(degrees[i])
            meta = self._match_label_to_metadata(label, meta_df)

            if meta is None:
                priorities[i] = {
                    "score": 0, "degree": degree,
                    "eligible": False, "breakdown": {}, "name": label
                }
                continue

            # Score each factor
            s_income  = self._score_income(meta.get("median_income"))
            s_pop     = self._score_population(meta.get("population_size"))
            s_density = self._score_density(meta.get("pop_density"))
            s_food    = self._score_food_desert(meta.get("food_desert_score"))
            s_bus     = self._score_bus_stops(meta.get("bus_stop_count"))
            s_degree  = self._score_degree(degree, all_degrees)

            # Skip if any core continuous factor is missing
            if any(s is None for s in [s_income, s_pop, s_density]):
                priorities[i] = {
                    "score": 0, "degree": degree,
                    "eligible": False, "breakdown": {}, "name": label
                }
                continue

            total = s_income + s_pop + s_density + s_food + s_bus + s_degree
            priorities[i] = {
                "score": total,
                "degree": degree,
                "eligible": True,
                "name": label,
                "breakdown": {
                    "income":      s_income,
                    "population":  s_pop,
                    "density":     s_density,
                    "food_desert": s_food,
                    "bus_stops":   s_bus,
                    "degree":      s_degree,
                }
            }

        return priorities

    # ── Greedy solver ─────────────────────────────────────────────────────────

    def _greedy_priority_mds(
        self,
        adj: np.ndarray,
        priorities: dict[int, dict],
    ) -> list[int]:
        """
        Greedy priority-first dominating set algorithm.

        Selects eligible nodes in descending priority order (ties broken by
        degree). A node is selected if it or any of its neighbors is not yet
        dominated. Continues until all eligible nodes are dominated.
        Ineligible (missing-data) nodes are dominated passively.
        """
        n = adj.shape[0]
        dominated = set()
        dominating_set = []

        # Sort eligible nodes by (score desc, degree desc)
        eligible = [
            i for i, p in priorities.items() if p["eligible"]
        ]
        eligible_sorted = sorted(
            eligible,
            key=lambda i: (priorities[i]["score"], priorities[i]["degree"]),
            reverse=True,
        )

        # Pre-dominate ineligible nodes so they don't block the algorithm
        # (they will be dominated if a neighbor is selected, otherwise flagged)
        ineligible = {i for i, p in priorities.items() if not p["eligible"]}

        for i in eligible_sorted:
            neighbors = {j for j in range(n) if adj[i][j] > 0}
            coverage  = {i} | neighbors

            # Check if this node or any eligible neighbor is still undominated
            uncovered_eligible = (coverage - dominated) - ineligible
            if uncovered_eligible:
                dominating_set.append(i)
                dominated |= coverage

        return dominating_set

    # ── Graph building ────────────────────────────────────────────────────────

    def _build_graph(self, adj: np.ndarray) -> nx.Graph:
        G = nx.Graph()
        n = adj.shape[0]
        G.add_nodes_from(range(n))
        for i in range(n):
            for j in range(i + 1, n):
                if adj[i][j] > 0:
                    G.add_edge(i, j, weight=adj[i][j])
        return G

    # ── Drawing ───────────────────────────────────────────────────────────────

    def _draw_graph(
        self,
        G: nx.Graph,
        labels: list[str],
        pos: dict,
        dominating_set: list[int],
        priorities: dict[int, dict],
        title: str,
        filepath: str,
    ):
        fig, ax = plt.subplots(figsize=(18, 13))
        ax.set_title(title, fontsize=13, fontweight="bold", pad=15)

        label_map = {i: abbreviate_label(i + 1, labels[i]) for i in range(len(labels))}

        # Color: red = dominating, grey = skipped/ineligible, orange = regular
        node_colors = []
        node_sizes  = []
        for i in range(len(labels)):
            if i in dominating_set:
                node_colors.append(COLOR_DOMINATING)
                node_sizes.append(550)
            elif not priorities[i]["eligible"]:
                node_colors.append(COLOR_SKIPPED)
                node_sizes.append(250)
            else:
                node_colors.append(COLOR_REGULAR)
                node_sizes.append(300)

        edge_weights = [G[u][v]["weight"] for u, v in G.edges()]
        if edge_weights:
            max_w  = max(edge_weights)
            widths = [1.5 * (1 - w / (max_w + 0.001)) + 0.5 for w in edge_weights]
        else:
            widths = [1.0]

        nx.draw_networkx_edges(G, pos, ax=ax, width=widths,
                               alpha=0.4, edge_color=COLOR_EDGE)
        nx.draw_networkx_nodes(G, pos, ax=ax, node_size=node_sizes,
                               node_color=node_colors, alpha=0.92)
        nx.draw_networkx_labels(G, pos, labels=label_map, ax=ax,
                                font_size=6, font_color="#111")

        edge_labels = {
            (u, v): f"{G[u][v]['weight']:.2f}mi" for u, v in G.edges()
        }
        nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, ax=ax,
                                     font_size=4.5, label_pos=0.35, alpha=0.7)

        n_dom     = len(dominating_set)
        n_skipped = sum(1 for p in priorities.values() if not p["eligible"])
        legend_elements = [
            mpatches.Patch(facecolor=COLOR_DOMINATING,
                           label=f"Dominating set ({n_dom} nodes)"),
            mpatches.Patch(facecolor=COLOR_REGULAR,
                           label="Dominated node"),
            mpatches.Patch(facecolor=COLOR_SKIPPED,
                           label=f"Skipped / missing data ({n_skipped} nodes)"),
        ]
        ax.legend(handles=legend_elements, loc="upper left",
                  fontsize=9, framealpha=0.85)

        ax.axis("off")
        plt.tight_layout()
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"  Saved: {filepath}")

    # ── Stats printer ─────────────────────────────────────────────────────────

    def _print_stats(
        self,
        mode: str,
        adj: np.ndarray,
        labels: list[str],
        dominating_set: list[int],
        priorities: dict[int, dict],
    ):
        n         = len(labels)
        edges     = int(np.count_nonzero(adj) // 2)
        eligible  = [i for i, p in priorities.items() if p["eligible"]]
        skipped   = [i for i, p in priorities.items() if not p["eligible"]]

        # Check which skipped nodes ended up dominated by a neighbor
        dominated_skipped = []
        undominated_skipped = []
        for i in skipped:
            neighbors = [j for j in range(n) if adj[i][j] > 0]
            if any(j in dominating_set for j in neighbors):
                dominated_skipped.append(i)
            else:
                undominated_skipped.append(i)

        print(f"\n{'-'*60}")
        print(f"  {mode.upper()} - Priority Greedy Dominating Set")
        print(f"{'-'*60}")
        print(f"  Total nodes:            {n}")
        print(f"  Total edges:            {edges}")
        print(f"  Eligible nodes:         {len(eligible)}")
        print(f"  Skipped (missing data): {len(skipped)}")
        print(f"  Dominating set size:    {len(dominating_set)}")
        print(f"  Skipped nodes passively dominated: {len(dominated_skipped)}")
        print(f"  Skipped nodes undominated:         {len(undominated_skipped)}")

        print(f"\n  Dominating nodes (sorted by priority):")
        print(f"  {'#':<4} {'Label':<35} {'Score':>5} {'Deg':>4}  Breakdown")
        print(f"  {'-'*80}")
        sorted_ds = sorted(dominating_set,
                           key=lambda i: priorities[i]["score"], reverse=True)
        for i in sorted_ds:
            p = priorities[i]
            bd = p["breakdown"]
            breakdown_str = (
                f"inc={bd['income']} pop={bd['population']} "
                f"den={bd['density']} food={bd['food_desert']} "
                f"bus={bd['bus_stops']} deg={bd['degree']}"
            )
            print(f"  {i+1:<4} {labels[i]:<35} {p['score']:>5} {p['degree']:>4}  {breakdown_str}")

        if undominated_skipped:
            print(f"\n  Undominated skipped nodes (no neighbor in dominating set):")
            for i in undominated_skipped:
                print(f"    [{i+1:2d}] {labels[i]}")

    # ── Main entry point ──────────────────────────────────────────────────────

    def run(self):
        """Full pipeline for both driving and walking matrices."""
        print("Loading metadata...")
        meta_df = self._load_metadata()
        print(f"  {len(meta_df)} metadata rows loaded.")

        for mode, csv_path in [("Driving", self.driving_csv),
                                ("Walking", self.walking_csv)]:

            print(f"\nLoading {mode} matrix from {csv_path}...")
            adj, labels = self._load_matrix(csv_path)
            print(f"  {len(labels)} nodes loaded.")

            print(f"Computing priority scores ({mode})...")
            priorities = self._compute_priorities(adj, labels, meta_df)

            eligible_count = sum(1 for p in priorities.values() if p["eligible"])
            skipped_count  = len(priorities) - eligible_count
            print(f"  Eligible: {eligible_count}  |  Skipped (missing data): {skipped_count}")

            print(f"Running greedy priority dominating set ({mode})...")
            dominating_set = self._greedy_priority_mds(adj, priorities)

            self._print_stats(mode, adj, labels, dominating_set, priorities)

            G = self._build_graph(adj)
            spring_pos = nx.spring_layout(G, seed=42, k=2.5)
            mode_lower = mode.lower()

            print(f"\nGenerating graphs ({mode})...")
            self._draw_graph(
                G, labels, spring_pos, dominating_set, priorities,
                title=(f"{mode} Graph - Spring Layout | "
                       f"Priority Greedy Dominating Set ({len(dominating_set)} nodes)"),
                filepath=f"{self.output_dir}{mode_lower}_graph_spring_priority_mds.png",
            )
            # Geo layout falls back to spring (coords not stored in matrix CSV)
            self._draw_graph(
                G, labels, spring_pos, dominating_set, priorities,
                title=(f"{mode} Graph - Geographic Layout | "
                       f"Priority Greedy Dominating Set ({len(dominating_set)} nodes)"),
                filepath=f"{self.output_dir}{mode_lower}_graph_geo_priority_mds.png",
            )

        print("\nAll done!")


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    solver = PriorityDominatingSetSolver()
    solver.run()
