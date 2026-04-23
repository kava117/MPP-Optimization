"""
Food Market Optimizer — Solver
Adapts domination.py and priority-domination.py for web API use.
Supports dynamic radius thresholds and both ILP and greedy priority modes.
"""

import pandas as pd
import numpy as np
import pulp
import networkx as nx
from typing import Optional


DATA_DIR = "data/"

INCOME_LOW   = 45_000
INCOME_MID   = 75_000
POP_LOW      = 30_000
POP_MID      = 50_000
DENSITY_LOW  = 2_000
DENSITY_MID  = 5_000
BUS_THRESHOLD = 5


def load_matrix(mode: str) -> tuple[np.ndarray, list[str]]:
    """Load driving or walking adjacency matrix."""
    path = DATA_DIR + ("driving_matrix.csv" if mode == "driving" else "walking_matrix.csv")
    df = pd.read_csv(path, index_col=0)
    return df.to_numpy(dtype=float), list(df.index)


def load_centers() -> pd.DataFrame:
    df = pd.read_csv(DATA_DIR + "centers.csv").dropna(subset=["name"])
    df["zip"] = df["zip"].astype(float).astype(int).astype(str)
    return df.reset_index(drop=True)


def apply_threshold(matrix: np.ndarray, threshold_miles: float) -> np.ndarray:
    """Zero out edges beyond the given distance threshold."""
    adj = matrix.copy()
    adj[adj > threshold_miles] = 0
    adj[adj < 0] = 0
    return adj


def filter_by_zips(
    matrix: np.ndarray,
    labels: list[str],
    centers_df: pd.DataFrame,
    selected_zips: list[str]
) -> tuple[np.ndarray, list[str], list[int]]:
    """
    Return a sub-matrix containing only centers whose ZIP is in selected_zips.
    Returns (sub_matrix, sub_labels, original_indices).
    """
    if not selected_zips:
        return matrix, labels, list(range(len(labels)))

    zip_map = dict(zip(centers_df["name"], centers_df["zip"]))
    keep_idx = [
        i for i, lbl in enumerate(labels)
        if zip_map.get(lbl, "") in selected_zips
    ]
    if not keep_idx:
        return matrix, labels, list(range(len(labels)))

    sub = matrix[np.ix_(keep_idx, keep_idx)]
    sub_labels = [labels[i] for i in keep_idx]
    return sub, sub_labels, keep_idx


# ── ILP Solver ────────────────────────────────────────────────────────────────

def solve_mds_ilp(adj: np.ndarray, labels: list[str]) -> list[int]:
    """
    Minimum Dominating Set via Integer Linear Programming (exact solution).
    Returns list of node indices in the dominating set.
    """
    n = len(labels)
    prob = pulp.LpProblem("MinDominatingSet", pulp.LpMinimize)
    x = [pulp.LpVariable(f"x_{i}", cat="Binary") for i in range(n)]
    prob += pulp.lpSum(x)
    for i in range(n):
        neighbors = [j for j in range(n) if adj[i][j] > 0]
        prob += x[i] + pulp.lpSum(x[j] for j in neighbors) >= 1
    solver = pulp.PULP_CBC_CMD(msg=0)
    prob.solve(solver)
    if pulp.LpStatus[prob.status] != "Optimal":
        # Fallback: every node dominates itself
        return list(range(n))
    return [i for i in range(n) if pulp.value(x[i]) > 0.5]


# ── Priority Greedy Solver ────────────────────────────────────────────────────

def _score_income(val) -> Optional[int]:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    v = float(val)
    return 3 if v < INCOME_LOW else (2 if v < INCOME_MID else 1)


def _score_population(val) -> Optional[int]:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    v = float(val)
    return 1 if v < POP_LOW else (2 if v < POP_MID else 3)


def _score_density(val) -> Optional[int]:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    v = float(val)
    return 1 if v < DENSITY_LOW else (2 if v < DENSITY_MID else 3)


def _score_food_desert(val) -> int:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return 1
    v = int(float(val))
    return 1 if v == 0 else (2 if v == 1 else 3)


def _score_bus_stops(val) -> int:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return 3
    return 1 if float(val) >= BUS_THRESHOLD else 3


def _score_degree(degree: int, all_degrees: list[int]) -> int:
    s = sorted(all_degrees)
    n = len(s)
    lo = s[n // 3]
    hi = s[(2 * n) // 3]
    return 1 if degree <= lo else (2 if degree <= hi else 3)


def solve_mds_priority(
    adj: np.ndarray,
    labels: list[str],
    centers_df: pd.DataFrame,
) -> tuple[list[int], dict]:
    """
    Priority-weighted greedy dominating set.
    Returns (dominating_set_indices, priorities_dict).
    """
    n = len(labels)
    degrees = [(adj[i] > 0).sum() for i in range(n)]
    name_to_meta = {row["name"]: row for _, row in centers_df.iterrows()}

    priorities = {}
    for i, label in enumerate(labels):
        meta = name_to_meta.get(label)
        degree = int(degrees[i])

        if meta is None:
            priorities[i] = {"score": 0, "degree": degree, "eligible": False,
                              "breakdown": {}, "name": label}
            continue

        s_income  = _score_income(meta.get("median_income"))
        s_pop     = _score_population(meta.get("population_size"))
        s_density = _score_density(meta.get("pop_density"))
        s_food    = _score_food_desert(meta.get("food_desert_score"))
        s_bus     = _score_bus_stops(meta.get("bus_stop_count"))
        s_deg     = _score_degree(degree, list(degrees))

        # If no demographic data at all, fall back to degree-only scoring
        if all(s is None for s in [s_income, s_pop, s_density]):
            s_income = s_pop = s_density = 1
        elif any(s is None for s in [s_income, s_pop, s_density]):
            s_income  = s_income  or 1
            s_pop     = s_pop     or 1
            s_density = s_density or 1

        total = s_income + s_pop + s_density + s_food + s_bus + s_deg
        priorities[i] = {
            "score": total, "degree": degree, "eligible": True, "name": label,
            "breakdown": {
                "income": s_income, "population": s_pop,
                "density": s_density, "food_desert": s_food,
                "bus_stops": s_bus, "degree": s_deg,
            }
        }

    eligible_sorted = sorted(
        [i for i, p in priorities.items() if p["eligible"]],
        key=lambda i: (priorities[i]["score"], priorities[i]["degree"]),
        reverse=True,
    )
    ineligible = {i for i, p in priorities.items() if not p["eligible"]}

    dominated = set()
    dominating_set = []
    for i in eligible_sorted:
        neighbors = {j for j in range(n) if adj[i][j] > 0}
        coverage  = {i} | neighbors
        if (coverage - dominated) - ineligible:
            dominating_set.append(i)
            dominated |= coverage

    return dominating_set, priorities


# ── Main API Entry Point ──────────────────────────────────────────────────────

def run_optimization(
    mode: str,
    threshold_miles: float,
    selected_zips: list[str],
    use_priority: bool,
) -> dict:
    """
    Full optimization pipeline.

    Returns dict with:
      - selected_stops: list of center dicts (name, lat, lon, zip)
      - covered_zips: list of ZIP codes covered
      - total_zips: total ZIPs in selection
      - coverage_pct: float
      - all_centers: full center list with is_selected, is_covered flags
      - graph_edges: edges for visualization
      - priorities: priority breakdown (if use_priority)
    """
    matrix, labels = load_matrix(mode)
    centers_df = load_centers()

    # Filter to selected ZIPs
    all_zips = sorted(centers_df["zip"].unique().tolist())
    if not selected_zips:
        selected_zips = all_zips

    sub_matrix, sub_labels, orig_idx = filter_by_zips(
        matrix, labels, centers_df, selected_zips
    )

    # Apply distance threshold
    adj = apply_threshold(sub_matrix, threshold_miles)

    # Run solver
    priorities = {}
    if use_priority:
        dom_set, priorities = solve_mds_priority(adj, sub_labels, centers_df)
    else:
        dom_set = solve_mds_ilp(adj, sub_labels)

    # Build coverage map: which ZIP codes are covered
    name_to_zip = dict(zip(centers_df["name"], centers_df["zip"]))
    selected_names = {sub_labels[i] for i in dom_set}

    # A ZIP is covered if any selected stop is in it OR within threshold of a center in it
    covered_zips = set()
    for i in dom_set:
        # The stop itself
        cname = sub_labels[i]
        if cname in name_to_zip:
            covered_zips.add(name_to_zip[cname])
        # Its neighbors
        for j in range(len(sub_labels)):
            if adj[i][j] > 0 and sub_labels[j] in name_to_zip:
                covered_zips.add(name_to_zip[sub_labels[j]])

    covered_zips &= set(selected_zips)
    total_zips = len(set(selected_zips))
    coverage_pct = round(len(covered_zips) / total_zips * 100, 1) if total_zips > 0 else 0

    # Build center output list
    name_to_center = {row["name"]: row for _, row in centers_df.iterrows()}
    all_centers_out = []
    for i, lbl in enumerate(sub_labels):
        c = name_to_center.get(lbl, {})
        is_selected = i in dom_set
        p = priorities.get(i, {})
        all_centers_out.append({
            "name": lbl,
            "lat": float(c.get("lat", 0)),
            "lon": float(c.get("lon", 0)),
            "zip": name_to_zip.get(lbl, ""),
            "address": str(c.get("address", "")),
            "is_selected": is_selected,
            "priority_score": p.get("score", None),
            "priority_breakdown": p.get("breakdown", {}),
        })

    # Build edges for visualization (only between selected stops and covered neighbors)
    edges = []
    for i in dom_set:
        for j in range(len(sub_labels)):
            if i < j and adj[i][j] > 0:
                ci = name_to_center.get(sub_labels[i], {})
                cj = name_to_center.get(sub_labels[j], {})
                edges.append({
                    "from": sub_labels[i],
                    "to": sub_labels[j],
                    "distance": round(float(adj[i][j]), 2),
                    "from_lat": float(ci.get("lat", 0)),
                    "from_lon": float(ci.get("lon", 0)),
                    "to_lat": float(cj.get("lat", 0)),
                    "to_lon": float(cj.get("lon", 0)),
                })

    return {
        "selected_stops": [c for c in all_centers_out if c["is_selected"]],
        "covered_zips": sorted(list(covered_zips)),
        "total_zips": total_zips,
        "num_stops": len(dom_set),
        "coverage_pct": coverage_pct,
        "all_centers": all_centers_out,
        "graph_edges": edges,
        "mode": mode,
        "threshold_miles": threshold_miles,
        "algorithm": "priority_greedy" if use_priority else "ilp_exact",
    }


def get_available_zip_list() -> list[str]:
    """Return all ZIP codes that have at least one center."""
    df = load_centers()
    return sorted(df["zip"].unique().tolist())
