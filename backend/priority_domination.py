"""
Priority-Weighted Greedy Dominating Set Solver
------------------------------------------------
Reads driving and walking adjacency matrix CSVs and a metadata CSV,
computes a priority score for each node based on socioeconomic factors,
then finds a greedy dominating set by selecting highest-priority nodes first.

Priority factors (equal weight, each scored 1-3):
    - Median income        (inverted: lower income = higher priority)
    - Population density   (denser = higher priority)
    - Food desert score    (more severe = higher priority)
    - Bus stop count       (binary inverted: <5 stops = higher priority)
    - Nearby nodes/degree  (higher degree = higher priority, dynamic bins)

Nodes with missing income/density data are skipped.
Ties in priority are broken by degree (higher degree wins).

Requirements:
    pip install pandas numpy matplotlib networkx
"""

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import networkx as nx
import pulp

STOPWORDS = {"of", "the", "and", "at", "in", "a", "an", "for", "to", "by"}

def abbreviate_label(index: int, name: str) -> str:
    """Used only for graph visualization. Full names are stored in the matrix CSVs."""
    words = name.split()
    parts = [w[:3].capitalize() + "." for w in words if w.lower() not in STOPWORDS]
    return f"{index}: {' '.join(parts)}"


# ─── CONFIG ──────────────────────────────────────────────────────────────────

DRIVING_MATRIX_CSV = "data/driving_matrix.csv"
WALKING_MATRIX_CSV = "data/walking_matrix.csv"
TRANSIT_MATRIX_CSV = "data/transit_matrix.csv"
METADATA_CSV       = "data/weighted_centers_new.csv"

OUTPUT_DIR = "images/"

# scoring thresholds
INCOME_LOW    = 42_000   # meant to capture the poverty line for household of 5  < this  -> score 3 (high priority)
INCOME_MID    = 70_000   # meant to capture average income for orlando households  < this  -> score 2, else score 1

POP_LOW       = 30_000   # < this  -> score 1
POP_MID       = 50_000   # < this  -> score 2, else score 3

DENSITY_LOW   = 2_000    # < this  -> score 1
DENSITY_MID   = 5_000    # < this  -> score 2, else score 3

BUS_THRESHOLD = 5        # taken from the green grocer paper as a metric or high or low access to public transport  >= this -> score 1 (good access), else score 3

# Node colors
COLOR_DOMINATING = "#e63946"   # Red    — in the dominating set
COLOR_SKIPPED    = "#aaaaaa"   # Grey   — missing data, skipped
COLOR_REGULAR    = "#f0a500"   # Orange — regular node
COLOR_EDGE       = "#4a90d9"   # Blue   — edges


# ─── CLASS ───────────────────────────────────────────────────────────────────

class PriorityDominatingSetSolver:
    """
    Priority-weighted minimum dominating set solver (ILP).

    Algorithm:
        1. Score each eligible node across 5 factors (1-3 each, max score 15).
        2. Solve an ILP that minimises set size as the primary objective and
           maximises total priority score as a lexicographic tiebreaker.
           This guarantees the smallest possible dominating set; among all
           sets of that size the one with the highest cumulative priority
           is returned.
        3. Ineligible (missing-data) nodes are excluded from selection but
           still require domination coverage — a neighbour must cover them.
    """

    def __init__(
        self,
        driving_csv:  str = DRIVING_MATRIX_CSV,
        walking_csv:  str = WALKING_MATRIX_CSV,
        transit_csv:  str = TRANSIT_MATRIX_CSV,
        metadata_csv: str = METADATA_CSV,
        output_dir:   str = OUTPUT_DIR,
    ):
        self.driving_csv  = driving_csv
        self.walking_csv  = walking_csv
        self.transit_csv  = transit_csv
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
        keep = ["name", "lat", "lon", "median_income",
                "pop_density", "food_desert_score", "bus_stop_count"]
        df = df[[c for c in keep if c in df.columns]].copy()
        return df

    # ── Label matching ────────────────────────────────────────────────────────

    def _build_metadata_map(
        self, labels: list[str], meta_df: pd.DataFrame
    ) -> dict[int, pd.Series]:
        """
        Build a node-index → metadata-row mapping using occurrence-order matching.
        When a name appears N times in labels, it is paired with the 1st through Nth
        rows of that name in meta_df, in order. Returns None for unmatched nodes.
        """
        # Pre-group metadata rows by name, preserving order
        name_to_rows: dict[str, list[pd.Series]] = {}
        for _, row in meta_df.iterrows():
            name_to_rows.setdefault(row["name"], []).append(row)

        seen: dict[str, int] = {}
        mapping: dict[int, pd.Series | None] = {}
        for i, label in enumerate(labels):
            occurrence = seen.get(label, 0)
            seen[label] = occurrence + 1
            rows = name_to_rows.get(label, [])
            mapping[i] = rows[occurrence] if occurrence < len(rows) else None
        return mapping

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

    # INERT: no longer accounting for population and also density as to not
    # double count. only density will be used from now on
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
        meta_map: dict | None = None,
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
        if meta_map is None:
            meta_map = self._build_metadata_map(labels, meta_df)

        priorities = {}
        for i, label in enumerate(labels):
            degree = int(degrees[i])
            meta = meta_map[i]

            if meta is None:
                priorities[i] = {
                    "score": 0, "degree": degree,
                    "eligible": False, "breakdown": {}, "name": label
                }
                continue

            # Score each factor
            s_income  = self._score_income(meta.get("median_income"))
            s_density = self._score_density(meta.get("pop_density"))
            s_food    = self._score_food_desert(meta.get("food_desert_score"))
            s_bus     = self._score_bus_stops(meta.get("bus_stop_count"))
            s_degree  = self._score_degree(degree, all_degrees)

            # Skip if any core continuous factor is missing
            if any(s is None for s in [s_income, s_density]):
                priorities[i] = {
                    "score": 0, "degree": degree,
                    "eligible": False, "breakdown": {}, "name": label
                }
                continue

            total = s_income + s_density + s_food + s_bus + s_degree
            priorities[i] = {
                "score": total,
                "degree": degree,
                "eligible": True,
                "name": label,
                "breakdown": {
                    "income":      s_income,
                    "density":     s_density,
                    "food_desert": s_food,
                    "bus_stops":   s_bus,
                    "degree":      s_degree,
                }
            }

        return priorities

    # ── ILP solver ────────────────────────────────────────────────────────────

    def _ilp_priority_mds(
        self,
        adj: np.ndarray,
        priorities: dict[int, dict],
    ) -> list[int]:
        """
        Exact priority-weighted minimum dominating set via ILP.

        Objective (lexicographic):
            Primary   — minimise |dominating set|
            Secondary — maximise sum of priority scores in the set

        Implemented as a single weighted objective:
            minimise  sum(x_i) - epsilon * sum(score_i * x_i)
        where epsilon is small enough that the priority term can never
        increase the set size beyond the true minimum.
        """
        n = adj.shape[0]
        ineligible = {i for i, p in priorities.items() if not p["eligible"]}

        prob = pulp.LpProblem("priority_mds", pulp.LpMinimize)
        x = [pulp.LpVariable(f"x_{i}", cat="Binary") for i in range(n)]

        # Ineligible nodes cannot be selected
        for i in ineligible:
            prob += x[i] == 0

        # Every node must be dominated (covered by itself or a neighbour)
        for i in range(n):
            neighbours = [j for j in range(n) if adj[i][j] > 0]
            prob += x[i] + pulp.lpSum(x[j] for j in neighbours) >= 1

        # Weighted objective: minimise size, break ties by maximising priority.
        # epsilon < 1 / (n * max_score) ensures priority never inflates set size.
        max_score = max((p["score"] for p in priorities.values()), default=1)
        epsilon = 1.0 / (n * max_score + 1)
        prob += (
            pulp.lpSum(x[i] for i in range(n))
            - epsilon * pulp.lpSum(priorities[i]["score"] * x[i] for i in range(n))
        )

        prob.solve(pulp.PULP_CBC_CMD(msg=0))

        if prob.status != 1:
            raise RuntimeError(f"ILP did not find an optimal solution (status={prob.status})")

        return [i for i in range(n) if pulp.value(x[i]) > 0.5]

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
        exclude_nodes: set[int] | None = None,
    ):
        exclude_nodes = exclude_nodes or set()
        nodelist = [i for i in G.nodes() if i not in exclude_nodes]
        edgelist = [(u, v) for u, v in G.edges()
                    if u not in exclude_nodes and v not in exclude_nodes]

        fig, ax = plt.subplots(figsize=(18, 13))
        ax.set_title(title, fontsize=13, fontweight="bold", pad=15)

        label_map = {i: abbreviate_label(i + 1, labels[i]) for i in nodelist}

        # Color: red = dominating, grey = skipped/ineligible, orange = regular
        node_colors = []
        node_sizes  = []
        for i in nodelist:
            if i in dominating_set:
                node_colors.append(COLOR_DOMINATING)
                node_sizes.append(550)
            elif not priorities[i]["eligible"]:
                node_colors.append(COLOR_SKIPPED)
                node_sizes.append(250)
            else:
                node_colors.append(COLOR_REGULAR)
                node_sizes.append(300)

        edge_weights = [G[u][v]["weight"] for u, v in edgelist]
        sparse = len(edge_weights) < 30
        if edge_weights:
            max_w  = max(edge_weights)
            w_scale, w_min = (2.0, 2.0) if sparse else (1.5, 0.5)
            widths = [w_scale * (1 - w / (max_w + 0.001)) + w_min for w in edge_weights]
        else:
            widths = [1.0]

        edge_alpha = 0.65 if sparse else 0.4
        nx.draw_networkx_edges(G, pos, ax=ax, edgelist=edgelist, width=widths,
                               alpha=edge_alpha, edge_color=COLOR_EDGE,
                               arrows=True, connectionstyle="arc3,rad=0.0")
        nx.draw_networkx_nodes(G, pos, ax=ax, nodelist=nodelist,
                               node_size=node_sizes, node_color=node_colors, alpha=0.92)
        nx.draw_networkx_labels(G, pos, labels=label_map, ax=ax,
                                font_size=6, font_color="#111")

        # draw_networkx_edge_labels has a bug in networkx 3.6 where it tries to
        # read connectionstyle back as a string but gets a callable. Place labels manually.
        for u, v in edgelist:
            label = f"{G[u][v]['weight']:.2f}mi"
            x = pos[u][0] + 0.35 * (pos[v][0] - pos[u][0])
            y = pos[u][1] + 0.35 * (pos[v][1] - pos[u][1])
            ax.text(x, y, label, fontsize=4.5, alpha=0.7, ha="center", va="center")

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
                f"inc={bd['income']} den={bd['density']} "
                f"food={bd['food_desert']} bus={bd['bus_stops']} "
                f"deg={bd['degree']}"
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
                                ("Walking", self.walking_csv),
                                ("Transit", self.transit_csv)]:

            print(f"\nLoading {mode} matrix from {csv_path}...")
            adj, labels = self._load_matrix(csv_path)
            print(f"  {len(labels)} nodes loaded.")

            print(f"Computing priority scores ({mode})...")
            meta_map = self._build_metadata_map(labels, meta_df)
            priorities = self._compute_priorities(adj, labels, meta_df, meta_map)

            eligible_count = sum(1 for p in priorities.values() if p["eligible"])
            skipped_count  = len(priorities) - eligible_count
            print(f"  Eligible: {eligible_count}  |  Skipped (missing data): {skipped_count}")

            print(f"Running greedy priority dominating set ({mode})...")
            dominating_set = self._ilp_priority_mds(adj, priorities)

            self._print_stats(mode, adj, labels, dominating_set, priorities)

            G = self._build_graph(adj)
            spring_pos = nx.spring_layout(G, seed=42, k=2.5)
            mode_lower = mode.lower()

            # Build geo positions from lat/lon in metadata (using occurrence-order map)
            geo_pos = {}
            geo_missing = set()
            for i in range(len(labels)):
                meta = meta_map[i]
                if meta is not None and not pd.isna(meta.get("lat")) and not pd.isna(meta.get("lon")):
                    geo_pos[i] = (float(meta["lon"]), float(meta["lat"]))
                else:
                    geo_missing.add(i)
            if geo_missing:
                print(f"  Note: {len(geo_missing)} node(s) missing lat/lon, omitted from geo graph.")

            # Normalize geo positions to [-1, 1] to avoid numerical issues in nx renderers
            lons = [p[0] for p in geo_pos.values()]
            lats = [p[1] for p in geo_pos.values()]
            lon_min, lon_max = min(lons), max(lons)
            lat_min, lat_max = min(lats), max(lats)
            lon_range = lon_max - lon_min or 1.0
            lat_range = lat_max - lat_min or 1.0
            geo_pos = {
                i: ((p[0] - lon_min) / lon_range * 2 - 1,
                    (p[1] - lat_min) / lat_range * 2 - 1)
                for i, p in geo_pos.items()
            }
            # geo_missing nodes have no position; pass a dummy so nx doesn't error on node lookup
            for i in geo_missing:
                geo_pos[i] = (0.0, 0.0)

            print(f"\nGenerating graphs ({mode})...")
            self._draw_graph(
                G, labels, spring_pos, dominating_set, priorities,
                title=(f"{mode} Graph - Spring Layout | "
                       f"Priority Greedy Dominating Set ({len(dominating_set)} nodes)"),
                filepath=f"{self.output_dir}{mode_lower}/{mode_lower}_graph_spring_priority_mds.png",
            )
            self._draw_graph(
                G, labels, geo_pos, dominating_set, priorities,
                title=(f"{mode} Graph - Geographic Layout | "
                       f"Priority Greedy Dominating Set ({len(dominating_set)} nodes)"),
                filepath=f"{self.output_dir}{mode_lower}/{mode_lower}_graph_geo_priority_mds.png",
                exclude_nodes=geo_missing,
            )

        print("\nAll done!")


# ─── ENTRY POINT ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    solver = PriorityDominatingSetSolver()
    solver.run()
