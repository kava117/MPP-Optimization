"""
CSV → Adjacency Matrix + Graph Visualizer
------------------------------------------
Reads a CSV of geographic locations, queries OSRM for pairwise
driving and walking distances, builds two adjacency matrices,
saves them as CSVs, and generates spring + geographic graph images.

Requirements:
    pip install requests pandas numpy matplotlib networkx
"""

import time
import requests
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import networkx as nx

# ─── CONFIG ──────────────────────────────────────────────────────────────────

CSV_PATH = "centers.csv"          # Path to your input CSV
DRIVING_THRESHOLD_MILES = 6.86       # Max driving distance to create an edge
WALKING_THRESHOLD_MILES = 0.25      # Max walking distance to create an edge

OUTPUT_DRIVING_CSV = "driving_matrix.csv"
OUTPUT_WALKING_CSV = "walking_matrix.csv"

METERS_PER_MILE = 1609.344

STOPWORDS = {"of", "the", "and", "at", "in", "a", "an", "for", "to", "by"}

# ─── HELPERS ─────────────────────────────────────────────────────────────────

def abbreviate_label(index: int, name: str) -> str:
    """Used only for graph visualization. Full names are stored in the matrix CSVs.
    'Colonialtown Neighborhood Center' → '1: Col. Nei. Cen.'"""
    words = name.split()
    parts = []
    for w in words:
        if w.lower() in STOPWORDS:
            continue
        abbr = w[:3].capitalize() + "."
        parts.append(abbr)
    return f"{index}: {' '.join(parts)}"


def osrm_table(coords: list[tuple[float, float]], profile: str) -> np.ndarray:
    """
    Query the OSRM table endpoint for all pairwise distances.
    coords: list of (lat, lon)
    profile: 'driving' or 'foot'
    Returns an N×N numpy array of distances in meters.
    """
    # OSRM expects lon,lat order
    coord_str = ";".join(f"{lon},{lat}" for lat, lon in coords)
    url = f"http://router.project-osrm.org/table/v1/{profile}/{coord_str}"
    params = {"annotations": "distance"}

    print(f"  Querying OSRM ({profile}) table for {len(coords)} nodes...", flush=True)
    response = requests.get(url, params=params, timeout=60)
    response.raise_for_status()

    data = response.json()
    if data.get("code") != "Ok":
        raise RuntimeError(f"OSRM error: {data.get('message', 'Unknown error')}")

    matrix = np.array(data["distances"], dtype=float)
    return matrix


def build_adjacency(distance_matrix_m: np.ndarray, threshold_miles: float) -> np.ndarray:
    """
    Convert a meter distance matrix to an adjacency matrix in miles.
    Edges only where distance <= threshold. Self-loops = 0.
    """
    n = distance_matrix_m.shape[0]
    threshold_m = threshold_miles * METERS_PER_MILE
    adj = np.zeros((n, n), dtype=float)

    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            d = distance_matrix_m[i][j]
            if d is not None and d <= threshold_m:
                adj[i][j] = round(d / METERS_PER_MILE, 4)

    return adj


def print_stats(label: str, adj: np.ndarray, labels: list[str]):
    n = adj.shape[0]
    edges = int(np.count_nonzero(adj) // 2)  # undirected
    degrees = (adj > 0).sum(axis=1)
    avg_deg = degrees.mean()
    isolated = (degrees == 0).sum()
    print(f"\n{'-'*50}")
    print(f"  {label}")
    print(f"{'-'*50}")
    print(f"  Nodes:         {n}")
    print(f"  Edges:         {edges}")
    print(f"  Avg degree:    {avg_deg:.2f}")
    print(f"  Isolated nodes:{isolated}")
    if isolated > 0:
        iso_names = [labels[i] for i in range(n) if degrees[i] == 0]
        print(f"  -> {', '.join(iso_names)}")


def build_graph(adj: np.ndarray, labels: list[str]) -> nx.Graph:
    G = nx.Graph()
    n = adj.shape[0]
    G.add_nodes_from(range(n))
    for i in range(n):
        for j in range(i + 1, n):
            if adj[i][j] > 0:
                G.add_edge(i, j, weight=adj[i][j])
    return G


def draw_graph(G: nx.Graph, labels: list[str], pos: dict,
               title: str, filepath: str):
    fig, ax = plt.subplots(figsize=(14, 10))
    ax.set_title(title, fontsize=14, fontweight="bold", pad=15)

    label_map = {i: abbreviate_label(i + 1, labels[i]) for i in range(len(labels))}
    edge_weights = [G[u][v]["weight"] for u, v in G.edges()]

    # Normalize edge width by weight (thinner = longer distance)
    if edge_weights:
        max_w = max(edge_weights)
        widths = [1.5 * (1 - w / (max_w + 0.001)) + 0.5 for w in edge_weights]
    else:
        widths = [1.0]

    nx.draw_networkx_edges(G, pos, ax=ax, width=widths, alpha=0.5, edge_color="#4a90d9")
    nx.draw_networkx_nodes(G, pos, ax=ax, node_size=300, node_color="#f0a500", alpha=0.9)
    nx.draw_networkx_labels(G, pos, labels=label_map, ax=ax, font_size=6.5, font_color="#111")

    edge_labels = {(u, v): f"{G[u][v]['weight']:.2f}mi" for u, v in G.edges()}
    nx.draw_networkx_edge_labels(G, pos, edge_labels=edge_labels, ax=ax,
                                  font_size=5, label_pos=0.35, alpha=0.7)

    ax.axis("off")
    plt.tight_layout()
    plt.savefig(filepath, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Saved: {filepath}")


# ─── MAIN ────────────────────────────────────────────────────────────────────

def main():
    # 1. Load CSV (skip 1 blank line after header)
    print("Loading CSV...")
    df = pd.read_csv(CSV_PATH, header=0, skip_blank_lines=True)
    print(df.columns.tolist())
    df.columns = [c.strip().lower() for c in df.columns]
    print(df.columns.tolist())
    df = df.dropna(subset=["lat", "lon", "name"]).reset_index(drop=True)
    print(f"  Loaded {len(df)} nodes.")

    coords = list(zip(df["lat"].astype(float), df["lon"].astype(float)))
    labels = df["name"].tolist()

    # 2. Query OSRM
    print("\nFetching distances from OSRM...")
    driving_dist_m = osrm_table(coords, "driving")
    time.sleep(1)  # be polite to the public server
    walking_dist_m = osrm_table(coords, "foot")

    # 3. Build adjacency matrices
    print("\nBuilding adjacency matrices...")
    driving_adj = build_adjacency(driving_dist_m, DRIVING_THRESHOLD_MILES)
    walking_adj = build_adjacency(walking_dist_m, WALKING_THRESHOLD_MILES)

    # 4. Print stats
    print_stats(f"DRIVING  (threshold: {DRIVING_THRESHOLD_MILES} mi)", driving_adj, labels)
    print_stats(f"WALKING  (threshold: {WALKING_THRESHOLD_MILES} mi)", walking_adj, labels)

    # 5. Save CSVs
    print("\nSaving CSVs...")
    pd.DataFrame(driving_adj, index=labels, columns=labels).to_csv(OUTPUT_DRIVING_CSV)
    pd.DataFrame(walking_adj, index=labels, columns=labels).to_csv(OUTPUT_WALKING_CSV)
    print(f"  Saved: {OUTPUT_DRIVING_CSV}")
    print(f"  Saved: {OUTPUT_WALKING_CSV}")

    # 6. Build graphs
    driving_G = build_graph(driving_adj, labels)
    walking_G = build_graph(walking_adj, labels)

    # 7. Compute layouts
    print("\nGenerating graph images...")

    # Spring layout
    driving_spring_pos = nx.spring_layout(driving_G, seed=42, k=2.5)
    walking_spring_pos = nx.spring_layout(walking_G, seed=42, k=2.5)

    # Geographic layout (lon as x, lat as y)
    geo_pos = {i: (coords[i][1], coords[i][0]) for i in range(len(coords))}

    # 8. Draw all 4 images
    draw_graph(driving_G, labels, driving_spring_pos,
               f"Driving Graph — Spring Layout (threshold: {DRIVING_THRESHOLD_MILES} mi)",
               "images/driving_graph_spring.png")

    draw_graph(driving_G, labels, geo_pos,
               f"Driving Graph — Geographic Layout (threshold: {DRIVING_THRESHOLD_MILES} mi)",
               "images/driving_graph_geo.png")

    draw_graph(walking_G, labels, walking_spring_pos,
               f"Walking Graph — Spring Layout (threshold: {WALKING_THRESHOLD_MILES} mi)",
               "images/walking_graph_spring.png")

    draw_graph(walking_G, labels, geo_pos,
               f"Walking Graph — Geographic Layout (threshold: {WALKING_THRESHOLD_MILES} mi)",
               "images/walking_graph_geo.png")

    print("\nAll done!")


if __name__ == "__main__":
    main()
