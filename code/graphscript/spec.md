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
            ├──▶ priority-domination.py  (Greedy — equity-weighted)
            └──▶ keyplayer_viz.py        (Key player analysis — centrality-based)
                      │
                      └── keyplayer_analysis.R  (R subprocess — runs kpset)
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

### `keyplayer_analysis.R` + `keyplayer_viz.py`

**Role:** Key player analysis — identifies which nodes are structurally most important using centrality-based methods from Borgatti (2006), as implemented in the R `keyplayer` package (An & Liu 2016). Complements the dominating set approaches by asking a different question: not *which nodes cover the graph* but *which nodes are most critical to the network's structure*.

**Inputs:** `driving_matrix.csv`, `walking_matrix.csv`, `weighted_centers.csv`

**Outputs:**
- `keyplayer_driving_fragment.csv`, `keyplayer_driving_mreach.csv`
- `keyplayer_walking_fragment.csv`, `keyplayer_walking_mreach.csv`
- `images/keyplayer_spring.png` — 2×2 combined figure, spring layout
- `images/keyplayer_geo.png` — 2×2 combined figure, geographic layout

**How it works:**

`keyplayer_viz.py` calls `Rscript keyplayer_analysis.R` as a subprocess, waits for it to complete, reads the 4 output CSVs, and produces the visualizations using the same networkx/matplotlib pipeline as the other solvers.

`keyplayer_analysis.R` runs four scenarios (2 matrices × 2 metrics):

1. Loads each matrix CSV, reads the first column as row names, applies `make.unique()` to handle duplicate node names, and binarizes (edge > 0 → 1).
2. Calls `kpset()` to find the k=5 most central nodes under each metric.
3. Calls `kpcent()` individually for each node in the result set to compute a standalone importance score, which is used to rank the 5 nodes within the set (rank 1 = highest individual score).
4. Writes a CSV with node name, rank, and centrality score for each scenario.

**Key parameters:**

| Parameter | Value | Meaning |
|---|---|---|
| `K` | `5` | Number of key players to find |
| `ROUNDS` | `50` | Random-restart rounds for the greedy search |
| `M` | `2` (KPP-Pos only) | Max hop distance for M-reach scoring |

**Metrics:**

| Label | `kpset` type | Method | Meaning |
|---|---|---|---|
| KPP-Neg | `"fragment"` | `"min"` | Nodes whose removal most fragments the network (disruption) |
| KPP-Pos | `"mreach.degree"` | `"max"` | Nodes that collectively reach the most other nodes within 2 hops |

**Visualization:** Key players are rendered in a 5-shade red gradient by within-set rank: near-black red (rank 1, most important) through pale pink (rank 5, least important within the set). Non-key-player nodes are orange. A shared legend appears at the bottom of each combined figure.

**Search algorithm:** The `keyplayer` package uses a greedy search with random restarts — not a genetic algorithm. `seed="random"` and `round=50` provide 50 random restarts, which is adequate for a 65-node network. There is no GA option in this package.

---

#### Bugs and Concerns

**1. `mreach.degree` scores exceed network size — metric is not a unique-node count**

Individual `mreach.degree` scores for some nodes exceed 65 (the total number of nodes). The maximum observed individual score is 90. This is because the default `cmode="total"` sums the *in-degree + out-degree* of all nodes reachable within M hops, not the *count of unique reachable nodes*. As a result:
- The KPP-Pos set score of 111 (for driving) is inflated and not interpretable as "111 nodes covered."
- Rankings within the key player set are comparisons of the same biased metric, so relative ordering is consistent but absolute scores are not coverage counts.
- If the intended question is "which 5 centers can serve the most distinct neighborhoods within 2 connections," this metric does not answer it cleanly.

**Possible fix:** Use `cmode="outdegree"` to count only outgoing reach, which reduces but does not eliminate double-counting on directed graphs. A fully unambiguous unique-node coverage measure would require a custom implementation outside of `keyplayer`.

---

**2. Near-isolated nodes can be selected by kpset when k exceeds the number of useful nodes**

In the driving KPP-Pos result, two of the five selected nodes (Clarcona Community Center and Orange County Orlando Magic Recreation Center) have out-degree 0 and 1 respectively — they are essentially disconnected from the network. Their individual `kpcent` scores are 0 and 2. They were selected because the greedy algorithm must always return exactly k=5 nodes, filling remaining slots with whatever marginally improves the score even when marginal gain is zero.

This is a structural issue with any fixed-k key player algorithm on sparse graphs: it cannot signal "fewer than k meaningful key players exist." The driving KPP-Pos results suggest that genuine marginal coverage saturates at approximately 3 nodes; the 4th and 5th selections are noise.

**Implication for interpretation:** Check individual `centrality_score` values in the output CSVs before treating all k selections as meaningful. Nodes with score 0 (or near-zero relative to rank 1) should be treated as artifacts of the fixed-k constraint, not as genuinely important nodes.

---

**3. The driving matrix is not symmetric**

`csv_to_adjacency.py` queries OSRM for directed driving distances, which are not guaranteed to be symmetric (A→B ≠ B→A in general due to one-way streets and routing differences). The adjacency matrix passed to `keyplayer` is therefore directed. The `keyplayer` package handles directed graphs, but:
- Fragmentation scores reflect the directed structure and may differ substantially from what an undirected analysis would produce.
- `mreach.degree` with `cmode="total"` counts both in- and out-edges, which is partly why scores exceed n.
- `domination.py` and `priority-domination.py` treat the matrix as undirected implicitly (they check `adj[i][j] > 0` for both directions). If asymmetric edges exist, the two solver families are operating on slightly different graphs.

---

**4. `kpcent` within-set ranking is an approximation**

The rank assigned to each key player is based on that node's *individual* `kpcent` score — how important it would be if it were the sole key player. This is a proxy for within-set importance, not a true marginal contribution score. True marginal contribution would require recomputing the set score with each node removed, which the current implementation does not do. For closely ranked nodes (e.g., the fragmentation scores of 0.9985 for three walking nodes), the rank ordering may not be meaningful.

---

**5. Duplicate node names require `make.unique()` in R**

At least one node name ("Community Health Centers") appears more than once in the matrix CSVs, causing R's `read.csv(row.names=1)` to fail with "duplicate row.names are not allowed." The R script works around this with `make.unique()`, which appends `.1`, `.2`, etc. to duplicates. However, the resulting deduplicated names (e.g., `"Community Health Centers.1"`) will not match against `weighted_centers.csv` if any downstream lookup by name is needed. The Python side uses occurrence-order matching (not name matching) when reading R output CSVs, so this is currently safe — but adding any R-side name lookup against the metadata CSV would silently fail for the duplicated node.

---

## Dependencies

**Python:**
```
requests
pandas
numpy
matplotlib
networkx
pulp          # domination.py only
```

Install: `pip install requests pandas numpy matplotlib networkx pulp`

**R** (required for `keyplayer_viz.py`):
```
keyplayer     # installs igraph, sna, network, matpow as dependencies
```

Install: `Rscript -e "install.packages('keyplayer', repos='https://cran.r-project.org')"`

System packages required to compile R dependencies from source (Ubuntu/Debian): `libxml2-dev libglpk-dev libgmp-dev gfortran`

---

## Comparison Methodology

The two solvers are intended to be run on the same adjacency matrices and compared:

- `domination.py` gives the **floor** — the fewest nodes that can cover the graph.
- `priority-domination.py` gives an **equity-adjusted** selection — typically larger, but biased toward nodes serving high-need areas.

The difference in set size between the two runs quantifies the "equity cost" of the priority approach.

---

## Known Gaps / Future Work

- `centers.csv` is missing the socioeconomic columns required by `priority-domination.py`. All nodes will be marked ineligible until those columns are populated.
- The three solver scripts share significant boilerplate (`_load_matrix`, `_build_graph`, `_draw_graph`, `abbreviate_label`, geo position logic). If further variants are added, consider extracting a shared utility module.
- The KPP-Pos (`mreach.degree`) metric does not count unique reachable nodes — see concern #1 in the keyplayer section. A custom reach implementation may be needed for a clean coverage interpretation.
- The fixed-k constraint in `kpset` cannot signal that fewer than k meaningful key players exist. For sparse subgraphs (especially walking), results should be interpreted carefully — see concern #2.
