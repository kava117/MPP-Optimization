"""
Minimum Dominating Set Solver
------------------------------
Reads driving and walking adjacency matrix CSVs, solves for the
minimum dominating set of each graph using Integer Linear Programming
(via PuLP), and saves highlighted graph images.
 
Requirements:
    pip install pulp pandas numpy matplotlib networkx
"""
 
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
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
 
OUTPUT_DIR = "images/"
 
# Node colors
COLOR_DOMINATING = "#e63946"   # Red   — in the dominating set
COLOR_REGULAR    = "#f0a500"   # Orange — regular node
COLOR_EDGE       = "#4a90d9"   # Blue  — edges
 
 
# ─── CLASS ───────────────────────────────────────────────────────────────────
 
class DominatingSetSolver:
    """
    Loads adjacency matrices from CSV, solves the Minimum Dominating Set
    problem via ILP, and produces highlighted graph visualizations.
    """
 
    def __init__(
        self,
        driving_csv: str = DRIVING_MATRIX_CSV,
        walking_csv: str = WALKING_MATRIX_CSV,
        transit_csv: str = TRANSIT_MATRIX_CSV,
        output_dir: str = OUTPUT_DIR,
    ):
        self.driving_csv = driving_csv
        self.walking_csv = walking_csv
        self.transit_csv = transit_csv
        self.output_dir  = output_dir
 
    # ── Data loading ─────────────────────────────────────────────────────────
 
    def _load_matrix(self, filepath: str) -> tuple[np.ndarray, list[str]]:
        """
        Load an adjacency matrix CSV.
        Returns (adj_matrix, labels).
        """
        df = pd.read_csv(filepath, index_col=0)
        labels = list(df.index)
        adj = df.to_numpy(dtype=float)
        return adj, labels
 
    # ── ILP solver ───────────────────────────────────────────────────────────
 
    def _solve_mds(self, adj: np.ndarray, labels: list[str]) -> list[int]:
        """
        Solve the Minimum Dominating Set problem via ILP.
 
        Formulation:
            Variables:  x_i in {0, 1}  for each node i
            Minimize:   sum(x_i)
            Subject to: x_i + sum(x_j for j in N(i)) >= 1  for all i
                        (every node must be in the set or adjacent to one)
 
        Returns a list of node indices in the minimum dominating set.
        """
        n = len(labels)
        prob = pulp.LpProblem("MinimumDominatingSet", pulp.LpMinimize)
 
        # Binary decision variables
        x = [pulp.LpVariable(f"x_{i}", cat="Binary") for i in range(n)]
 
        # Objective: minimize set size
        prob += pulp.lpSum(x)
 
        # Domination constraints
        for i in range(n):
            neighbors = [j for j in range(n) if adj[i][j] > 0]
            # Node i is dominated if it or any neighbor is in the set
            prob += x[i] + pulp.lpSum(x[j] for j in neighbors) >= 1
 
        # Solve (suppress solver output)
        solver = pulp.PULP_CBC_CMD(msg=0)
        prob.solve(solver)
 
        if pulp.LpStatus[prob.status] != "Optimal":
            raise RuntimeError(f"ILP solver did not find optimal solution: {pulp.LpStatus[prob.status]}")
 
        dominating_set = [i for i in range(n) if pulp.value(x[i]) > 0.5]
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
        title: str,
        filepath: str,
    ):
        fig, ax = plt.subplots(figsize=(18, 13))
        ax.set_title(title, fontsize=13, fontweight="bold", pad=15)
 
        label_map = {i: abbreviate_label(i + 1, labels[i]) for i in range(len(labels))}

        # Node colors: red for dominating set, orange otherwise
        node_colors = [
            COLOR_DOMINATING if i in dominating_set else COLOR_REGULAR
            for i in range(len(labels))
        ]
 
        # Node sizes: slightly larger for dominating nodes
        node_sizes = [
            500 if i in dominating_set else 300
            for i in range(len(labels))
        ]
 
        # Edge widths scaled by inverse weight (shorter = bolder); sparse graphs get thicker, more opaque lines
        edge_weights = [G[u][v]["weight"] for u, v in G.edges()]
        sparse = len(edge_weights) < 30
        if edge_weights:
            max_w = max(edge_weights)
            w_scale, w_min = (2.0, 2.0) if sparse else (1.5, 0.5)
            widths = [w_scale * (1 - w / (max_w + 0.001)) + w_min for w in edge_weights]
        else:
            widths = [1.0]

        edge_alpha = 0.65 if sparse else 0.4
        nx.draw_networkx_edges(G, pos, ax=ax, width=widths, alpha=edge_alpha, edge_color=COLOR_EDGE)
        nx.draw_networkx_nodes(G, pos, ax=ax, node_size=node_sizes,
                               node_color=node_colors, alpha=0.92)
        nx.draw_networkx_labels(G, pos, labels=label_map, ax=ax,
                                font_size=6, font_color="#111")
 
        edge_labels = {(u, v): f"{G[u][v]['weight']:.2f}mi" for u, v in G.edges()}
        nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, ax=ax,
                                     font_size=4.5, label_pos=0.35, alpha=0.7)
 
        # Legend
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor=COLOR_DOMINATING, label=f"Dominating set ({len(dominating_set)} nodes)"),
            Patch(facecolor=COLOR_REGULAR,    label="Regular node"),
        ]
        ax.legend(handles=legend_elements, loc="upper left", fontsize=9,
                  framealpha=0.85)
 
        ax.axis("off")
        plt.tight_layout()
        plt.savefig(filepath, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"  Saved: {filepath}")
 
    # ── Stats printer ─────────────────────────────────────────────────────────
 
    def _print_stats(
        self,
        label: str,
        dominating_set: list[int],
        labels: list[str],
        adj: np.ndarray,
    ):
        n = len(labels)
        edges = int(np.count_nonzero(adj) // 2)
        print(f"\n{'-'*55}")
        print(f"  {label}")
        print(f"{'-'*55}")
        print(f"  Total nodes:          {n}")
        print(f"  Total edges:          {edges}")
        print(f"  Dominating set size:  {len(dominating_set)}")
        print(f"  Coverage:             {len(dominating_set)/n*100:.1f}% of nodes")
        print(f"\n  Dominating nodes:")
        for idx in dominating_set:
            degree = int((adj[idx] > 0).sum())
            print(f"    [{idx+1:2d}] {labels[idx]}  (degree: {degree})")
 
    # ── Main entry point ──────────────────────────────────────────────────────
 
    def run(self):
        """
        Full pipeline: load -> solve -> visualize for both driving and walking.
        """
        for mode, csv_path in [("Driving", self.driving_csv),
                                ("Walking", self.walking_csv),
                                ("Transit", self.transit_csv)]:
 
            print(f"\nLoading {mode} matrix from {csv_path}...")
            adj, labels = self._load_matrix(csv_path)
            n = len(labels)
            print(f"  {n} nodes loaded.")
 
            print(f"Solving minimum dominating set ({mode})...")
            dominating_set = self._solve_mds(adj, labels)
 
            self._print_stats(f"{mode.upper()} - Minimum Dominating Set", dominating_set, labels, adj)
 
            G = self._build_graph(adj)
 
            # Layouts
            spring_pos = nx.spring_layout(G, seed=42, k=2.5)
 
            # Geographic layout — labels are "idx: Aaa. Bbb." so we need
            # the original coords, which are encoded as the matrix row/col order.
            # We extract lat/lon from the adjacency CSV index if available,
            # otherwise fall back to spring layout for geo too.
            geo_pos = spring_pos  # fallback
            try:
                df_raw = pd.read_csv(csv_path, index_col=0)
                # coords are not stored in the matrix CSV, so geo uses spring
                # To use real geo layout, pass coords separately (see note below)
            except Exception:
                pass
 
            mode_lower = mode.lower()
 
            print(f"\nGenerating highlighted graphs ({mode})...")
            self._draw_graph(
                G, labels, spring_pos, dominating_set,
                title=f"{mode} Graph - Spring Layout | Minimum Dominating Set ({len(dominating_set)} nodes)",
                filepath=f"{self.output_dir}{mode_lower}/{mode_lower}_graph_spring_mds.png",
            )
            self._draw_graph(
                G, labels, geo_pos, dominating_set,
                title=f"{mode} Graph - Geographic Layout | Minimum Dominating Set ({len(dominating_set)} nodes)",
                filepath=f"{self.output_dir}{mode_lower}/{mode_lower}_graph_geo_mds.png",
            )
 
        print("\nAll done!")
 
 
# ── Optional: geographic layout support ──────────────────────────────────────
# If you want the geo layout to use real lat/lon coordinates, instantiate like:
#
#   solver = DominatingSetSolver()
#   solver.run_with_coords(coords)  # coords = list of (lat, lon) tuples
#
# and add this method to the class:
#
#   def run_with_coords(self, coords):
#       self._coords = coords
#       self.run()
#
# Then inside run(), replace geo_pos fallback with:
#   geo_pos = {i: (self._coords[i][1], self._coords[i][0]) for i in range(n)}
 
 
# ─── ENTRY POINT ─────────────────────────────────────────────────────────────
 
if __name__ == "__main__":
    solver = DominatingSetSolver()
    solver.run()