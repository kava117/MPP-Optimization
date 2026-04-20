"""
Key Player Visualizer
─────────────────────────────────────────────────────────────────────────────
Runs keyplayer_analysis.R, then produces two combined images:

  images/keyplayer_spring.png  —  2×2 grid, spring layout
  images/keyplayer_geo.png     —  2×2 grid, geographic layout

Layout of each 2×2 grid:
  [0,0] Driving   | KPP-Neg (fragment)
  [0,1] Walking   | KPP-Neg (fragment)
  [1,0] Driving   | KPP-Pos (reach)
  [1,1] Walking   | KPP-Pos (reach)

Key players are colored by within-set rank (1 = most important):
  Rank 1 → darkest red   …   Rank 5 → lightest pink

Requirements:
    pip install pandas numpy matplotlib networkx
    R with keyplayer package
"""

import os
import subprocess
import sys

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd

# ─── CONFIG ──────────────────────────────────────────────────────────────────

DRIVING_MATRIX_CSV = "driving_matrix.csv"
WALKING_MATRIX_CSV = "walking_matrix.csv"
METADATA_CSV       = "weighted_centers.csv"
R_SCRIPT           = "keyplayer_analysis.R"
OUTPUT_DIR         = "images/"
K                  = 5

# Rank 1 (most important) → index 0, rank 5 → index 4
KP_RANK_COLORS = [
    "#7b0000",  # rank 1 — near-black red
    "#c0392b",  # rank 2 — strong red
    "#e74c3c",  # rank 3 — medium red
    "#f1948a",  # rank 4 — light red
    "#fadbd8",  # rank 5 — pale pink
]

COLOR_REGULAR  = "#f0a500"  # orange — non-key-player node
COLOR_EDGE     = "#4a90d9"  # blue — edges

STOPWORDS = {"of", "the", "and", "at", "in", "a", "an", "for", "to", "by"}

# ─── DATA HELPERS ────────────────────────────────────────────────────────────

def abbreviate_label(index: int, name: str) -> str:
    parts = [w[:3].capitalize() + "." for w in name.split() if w.lower() not in STOPWORDS]
    return f"{index}: {' '.join(parts)}"


def load_matrix(filepath: str) -> tuple[np.ndarray, list[str]]:
    df = pd.read_csv(filepath, index_col=0)
    return df.to_numpy(dtype=float), list(df.index)


def load_kp_result(filepath: str) -> dict[str, int]:
    """Returns {node_name: rank (1=most important)} for the key player set."""
    if not os.path.exists(filepath):
        print(f"  Warning: {filepath} not found — skipping.", file=sys.stderr)
        return {}
    df = pd.read_csv(filepath)
    return dict(zip(df["name"], df["rank"].astype(int)))


def build_graph(adj: np.ndarray) -> nx.Graph:
    G = nx.Graph()
    n = adj.shape[0]
    G.add_nodes_from(range(n))
    for i in range(n):
        for j in range(i + 1, n):
            if adj[i][j] > 0:
                G.add_edge(i, j, weight=adj[i][j])
    return G


def build_geo_pos(
    metadata_csv: str, labels: list[str]
) -> tuple[dict[int, tuple[float, float]], set[int]]:
    """Build normalized lon/lat position dict, return (pos, missing_node_indices)."""
    meta = pd.read_csv(metadata_csv, skip_blank_lines=True)
    meta.columns = [c.strip().lower() for c in meta.columns]

    name_to_rows: dict[str, list] = {}
    for _, row in meta.iterrows():
        name_to_rows.setdefault(row["name"], []).append(row)

    seen: dict[str, int] = {}
    raw_pos: dict[int, tuple[float, float]] = {}
    missing: set[int] = set()

    for i, label in enumerate(labels):
        occ  = seen.get(label, 0)
        seen[label] = occ + 1
        rows = name_to_rows.get(label, [])
        row  = rows[occ] if occ < len(rows) else None
        if (row is not None
                and not pd.isna(row.get("lat"))
                and not pd.isna(row.get("lon"))):
            raw_pos[i] = (float(row["lon"]), float(row["lat"]))
        else:
            missing.add(i)

    if raw_pos:
        lons      = [p[0] for p in raw_pos.values()]
        lats      = [p[1] for p in raw_pos.values()]
        lon_range = max(lons) - min(lons) or 1.0
        lat_range = max(lats) - min(lats) or 1.0
        pos = {
            i: (
                (p[0] - min(lons)) / lon_range * 2 - 1,
                (p[1] - min(lats)) / lat_range * 2 - 1,
            )
            for i, p in raw_pos.items()
        }
    else:
        pos = {}

    for i in missing:
        pos[i] = (0.0, 0.0)

    return pos, missing


# ─── DRAWING ─────────────────────────────────────────────────────────────────

def draw_panel(
    ax,
    G: nx.Graph,
    labels: list[str],
    pos: dict[int, tuple[float, float]],
    kp_rank_map: dict[str, int],
    title: str,
    exclude_nodes: set[int] | None = None,
):
    """Draw a single key-player graph panel onto ax."""
    exclude_nodes = exclude_nodes or set()
    nodelist = [i for i in G.nodes() if i not in exclude_nodes]
    edgelist = [
        (u, v) for u, v in G.edges()
        if u not in exclude_nodes and v not in exclude_nodes
    ]

    node_colors = []
    node_sizes  = []
    for i in nodelist:
        rank = kp_rank_map.get(labels[i])
        if rank is not None:
            node_colors.append(KP_RANK_COLORS[rank - 1])
            node_sizes.append(650)
        else:
            node_colors.append(COLOR_REGULAR)
            node_sizes.append(280)

    edge_weights = [G[u][v]["weight"] for u, v in edgelist]
    if edge_weights:
        max_w  = max(edge_weights)
        widths = [1.5 * (1 - w / (max_w + 0.001)) + 0.5 for w in edge_weights]
    else:
        widths = [1.0]

    label_map = {i: abbreviate_label(i + 1, labels[i]) for i in nodelist}

    nx.draw_networkx_edges(
        G, pos, ax=ax, edgelist=edgelist,
        width=widths, alpha=0.35, edge_color=COLOR_EDGE,
    )
    nx.draw_networkx_nodes(
        G, pos, ax=ax, nodelist=nodelist,
        node_size=node_sizes, node_color=node_colors, alpha=0.92,
    )
    nx.draw_networkx_labels(
        G, pos, labels=label_map, ax=ax,
        font_size=5.5, font_color="#111",
    )

    for u, v in edgelist:
        label = f"{G[u][v]['weight']:.2f}mi"
        x = pos[u][0] + 0.35 * (pos[v][0] - pos[u][0])
        y = pos[u][1] + 0.35 * (pos[v][1] - pos[u][1])
        ax.text(x, y, label, fontsize=4, alpha=0.6, ha="center", va="center")

    ax.set_title(title, fontsize=10, fontweight="bold", pad=10)
    ax.axis("off")


def build_legend(k: int) -> list[mpatches.Patch]:
    patches = [
        mpatches.Patch(
            facecolor=KP_RANK_COLORS[r - 1],
            edgecolor="#333",
            linewidth=0.5,
            label=f"Rank {r}" + (" — most important" if r == 1 else
                                  " — least important" if r == k else ""),
        )
        for r in range(1, k + 1)
    ]
    patches.append(
        mpatches.Patch(facecolor=COLOR_REGULAR, label="Non-key-player node")
    )
    return patches


# ─── MAIN ────────────────────────────────────────────────────────────────────

def run_r_script():
    print("Running R key player analysis (this may take a minute)...")
    result = subprocess.run(
        ["Rscript", R_SCRIPT],
        capture_output=True, text=True,
    )
    print(result.stdout)
    if result.returncode != 0:
        print("R script stderr:", result.stderr, file=sys.stderr)
        sys.exit(1)
    print("R analysis complete.\n")


def main():
    run_r_script()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Load matrices and graphs
    driving_adj, driving_labels = load_matrix(DRIVING_MATRIX_CSV)
    walking_adj, walking_labels = load_matrix(WALKING_MATRIX_CSV)
    driving_G = build_graph(driving_adj)
    walking_G = build_graph(walking_adj)

    # Layouts
    driving_spring = nx.spring_layout(driving_G, seed=42, k=2.5)
    walking_spring = nx.spring_layout(walking_G, seed=42, k=2.5)
    driving_geo, driving_geo_missing = build_geo_pos(METADATA_CSV, driving_labels)
    walking_geo, walking_geo_missing = build_geo_pos(METADATA_CSV, walking_labels)

    # Load key player result CSVs
    kp_results: dict[tuple[str, str], dict[str, int]] = {}
    for matrix in ("driving", "walking"):
        for kp_type in ("fragment", "mreach"):
            kp_results[(matrix, kp_type)] = load_kp_result(
                f"keyplayer_{matrix}_{kp_type}.csv"
            )

    # Panel definitions: (row, col, matrix, kp_type, G, labels, spring_pos, geo_pos, geo_missing)
    panel_defs = [
        (0, 0, "driving", "fragment", driving_G, driving_labels,
         driving_spring, driving_geo, driving_geo_missing),
        (0, 1, "walking", "fragment", walking_G, walking_labels,
         walking_spring, walking_geo, walking_geo_missing),
        (1, 0, "driving", "mreach",   driving_G, driving_labels,
         driving_spring, driving_geo, driving_geo_missing),
        (1, 1, "walking", "mreach",   walking_G, walking_labels,
         walking_spring, walking_geo, walking_geo_missing),
    ]

    col_headers = {
        "fragment": "KPP-Neg  |  Fragmentation",
        "mreach":   "KPP-Pos  |  M-Reach (2 hops)",
    }

    for layout_name in ("spring", "geo"):
        fig, axes = plt.subplots(2, 2, figsize=(22, 16))
        fig.suptitle(
            f"Key Player Analysis  —  k={K}, Genetic Algorithm  ({layout_name.capitalize()} Layout)",
            fontsize=14, fontweight="bold", y=0.985,
        )

        for row, col, matrix, kp_type, G, labels, spring_pos, geo_pos, geo_missing in panel_defs:
            pos     = spring_pos if layout_name == "spring" else geo_pos
            exclude = set()     if layout_name == "spring" else geo_missing
            draw_panel(
                axes[row][col],
                G, labels, pos,
                kp_rank_map=kp_results[(matrix, kp_type)],
                title=f"{matrix.capitalize()} Network  —  {col_headers[kp_type]}",
                exclude_nodes=exclude,
            )

        legend_patches = build_legend(K)
        fig.legend(
            handles=legend_patches,
            loc="lower center",
            ncol=K + 1,
            fontsize=9,
            framealpha=0.92,
            edgecolor="#ccc",
            bbox_to_anchor=(0.5, 0.005),
        )

        plt.tight_layout(rect=[0, 0.055, 1, 0.978])
        out_path = f"{OUTPUT_DIR}keyplayer/keyplayer_{layout_name}.png"
        plt.savefig(out_path, dpi=150, bbox_inches="tight")
        plt.close()
        print(f"Saved: {out_path}")

    print("\nAll done.")


if __name__ == "__main__":
    main()
