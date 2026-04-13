# Graphscript — Project Specification

## Purpose

This module solves an optimization problem: given a set of community centers across the Orlando metro area, select the smallest meaningful subset of centers that "covers" the network — meaning every unselected center is geographically close to at least one selected center. This is the **Minimum Dominating Set (MDS)** problem on a graph.

Two approaches are implemented and intended for side-by-side comparison:
- A mathematically optimal ILP solver (`domination.py`)
- A priority-weighted greedy solver that biases selection toward socioeconomically underserved nodes (`priority-domination.py`)

---

## Pipeline Overview

```
centers.csv
    │
    ▼
csv_to_adjacency.py
    │
    ├── driving_matrix.csv
    └── walking_matrix.csv
            │
            ├──▶ domination.py           (ILP — optimal, size-minimizing)
            └──▶ priority-domination.py  (Greedy — equity-weighted)
```

Each stage is a standalone script. The adjacency CSVs are the only artifact passed between stages.

---

## Files

### `centers.csv`

Input data. Each row is one community center.

**Current columns:** `name`, `zip`, `address`, `lat`, `lon`

**Required additional columns** (not yet populated — must be added before `priority-domination.py` will score nodes correctly):

| Column | Type | Description |
|---|---|---|
| `median_income` | float | Median household income of the surrounding area |
| `population_size` | int | Total population of the surrounding area |
| `pop_density` | float | Population density (people per sq mi or similar) |
| `food_desert_score` | int (0–2) | 0 = no desert, 1 = moderate, 2 = severe |
| `bus_stop_count` | int | Number of nearby bus stops |

Nodes missing `median_income`, `population_size`, or `pop_density` are marked ineligible in `priority-domination.py` and excluded from the greedy selection (but may still be passively dominated by a neighbor). `food_desert_score` and `bus_stop_count` default to low-priority values when absent rather than disqualifying the node.

---

### `csv_to_adjacency.py`

**Role:** Data ingestion and graph construction.

**Inputs:** `centers.csv`

**Outputs:**
- `driving_matrix.csv` — N×N weighted adjacency matrix (edge weight = driving distance in miles)
- `walking_matrix.csv` — N×N weighted adjacency matrix (edge weight = walking distance in miles)
- `driving_graph_spring.png`, `driving_graph_geo.png`
- `walking_graph_spring.png`, `walking_graph_geo.png`

**Key parameters (top of file):**

| Constant | Default | Meaning |
|---|---|---|
| `DRIVING_THRESHOLD_MILES` | `10.5` | Max driving distance to place an edge |
| `WALKING_THRESHOLD_MILES` | `0.25` | Max walking distance to place an edge |
| `CSV_PATH` | `"centers.csv"` | Input file |

**How it works:**
1. Loads `centers.csv`, extracts `(lat, lon)` for each node.
2. Queries the public OSRM routing API (`router.project-osrm.org`) once for driving, once for walking, using the `/table/v1/` endpoint for all-pairs distances in a single request.
3. Applies threshold filtering — only pairs within the threshold get an edge.
4. Converts meters to miles and writes both matrices as CSVs with abbreviated node labels as index/column headers.
5. Generates two layout types per graph: spring (force-directed) and geographic (lon/lat as x/y).

**Label format:** Full center names from `centers.csv` are used as row/column headers in the matrix CSVs. Abbreviated visual labels (e.g., `"1: Cal. Nei. Cen."`) are computed at render time inside `draw_graph()` using the `abbreviate_label()` helper and are never persisted to disk.

---

### `domination.py`

**Role:** Mathematically optimal MDS via Integer Linear Programming.

**Inputs:** `driving_matrix.csv`, `walking_matrix.csv`

**Outputs:** `driving_graph_spring_mds.png`, `driving_graph_geo_mds.png`, `walking_graph_spring_mds.png`, `walking_graph_geo_mds.png`

**Class:** `DominatingSetSolver`

**ILP formulation:**
- Binary variable `x_i` for each node (1 = in dominating set).
- Minimize `Σ x_i`.
- Constraint for each node `i`: `x_i + Σ x_j (j ∈ neighbors of i) ≥ 1` — every node must be selected or have a selected neighbor.
- Solved with PuLP using the CBC solver.

**When to use this over the greedy solver:** When you need a guaranteed minimum-size solution with no equity weighting. Useful as a baseline to measure how many additional nodes the priority solver selects in order to bias toward underserved areas.

**Geo layout note:** The geographic layout currently falls back to the spring layout because lat/lon coordinates are not stored in the matrix CSVs. To fix this, pass coords separately (see the comment block at the bottom of the file).

---

### `priority-domination.py`

**Role:** Equity-weighted greedy MDS. Selects nodes in descending priority order based on socioeconomic need rather than minimizing set size.

**Inputs:** `driving_matrix.csv`, `walking_matrix.csv`, `centers.csv`

**Outputs:** `driving_graph_spring_priority_mds.png`, `driving_graph_geo_priority_mds.png`, `walking_graph_spring_priority_mds.png`, `walking_graph_geo_priority_mds.png`

**Class:** `PriorityDominatingSetSolver`

**Scoring (each factor scored 1–3, max total = 18):**

| Factor | Higher priority when... |
|---|---|
| `median_income` | Lower income |
| `population_size` | Larger population |
| `pop_density` | Denser area |
| `food_desert_score` | More severe food desert |
| `bus_stop_count` | Fewer bus stops (< 5) |
| Node degree | More graph neighbors (dynamically binned into thirds) |

All six factors are equally weighted. Ties in total score are broken by degree (higher degree wins).

**Algorithm:**
1. Score all eligible nodes (those with non-null income, population, and density).
2. Sort eligible nodes descending by `(score, degree)`.
3. Greedily iterate: if a node or any of its eligible neighbors is not yet dominated, add the node to the dominating set and mark all its neighbors as dominated.
4. Ineligible (missing-data) nodes are excluded from selection but may be passively dominated if a neighbor is selected.

**Label matching:** Matrix CSV labels are full center names, so `_match_label_to_metadata()` uses an exact `name` column lookup against `centers.csv`. No fuzzy matching is needed.

---

## Dependencies

```
requests
pandas
numpy
matplotlib
networkx
pulp          # domination.py only
```

Install: `pip install requests pandas numpy matplotlib networkx pulp`

---

## Comparison Methodology

The two solvers are intended to be run on the same adjacency matrices and compared:

- `domination.py` gives the **floor** — the fewest nodes that can cover the graph.
- `priority-domination.py` gives an **equity-adjusted** selection — typically larger, but biased toward nodes serving high-need areas.

The difference in set size between the two runs quantifies the "equity cost" of the priority approach.

---

## Known Gaps / Future Work

- `centers.csv` is missing the socioeconomic columns required by `priority-domination.py`. All nodes will be marked ineligible until those columns are populated.
- Geographic layout in both solver scripts falls back to spring layout. True geo layout requires threading `(lat, lon)` coordinates from `centers.csv` through to the solver classes (a coord list is not stored in the matrix CSVs).
- The two solvers share significant boilerplate (`_load_matrix`, `_build_graph`, `_draw_graph`, `abbreviate_label`). If a third solver variant is added, consider extracting a shared base class or utility module.
