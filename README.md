# FoodReach — Mobile Market Optimizer

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Start the backend (Terminal 1)
```bash
./start_backend.sh
# OR: cd backend && python3 app.py
```

### 3. Start the frontend (Terminal 2)
```bash
./start_frontend.sh
# OR: cd frontend && python3 -m http.server 8080
```

### 4. Open the app
Navigate to: **http://localhost:8080**

---

## Project Structure

```
food_market_app/
├── backend/
│   ├── app.py           # Flask API (3 endpoints)
│   ├── solver.py        # Dominating set algorithms (ILP + Priority)
│   └── data/
│       ├── centers.csv           # 65 community centers
│       ├── driving_matrix.csv    # Road distances (miles)
│       ├── walking_matrix.csv    # Walking distances (miles, haversine × 1.4)
│       └── zip_codes.gpkg        # ZIP polygons + center points
├── frontend/
│   ├── index.html
│   ├── style.css
│   └── app.js
├── requirements.txt
├── start_backend.sh
├── start_frontend.sh
└── README.md
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | /api/centers | All 65 centers as GeoJSON |
| GET | /api/zipcodes | ZIP polygon boundaries as GeoJSON |
| GET | /api/zips | ZIP codes with center counts |
| POST | /api/optimize | Run optimization |

### POST /api/optimize
```json
{
  "mode": "driving",         // "driving" or "walking"
  "threshold_miles": 5.0,   // coverage radius (user-adjustable)
  "selected_zips": [],       // empty = all ZIPs
  "use_priority": false      // true = priority-weighted greedy, false = ILP exact
}
```

## Adding Food Desert / Demographic Data (TODO)

To enable the Priority Weighted algorithm with real scores, add these columns
to `backend/data/centers.csv`:

| Column | Description |
|--------|-------------|
| `median_income` | Median household income for the ZIP |
| `population_size` | Total population |
| `pop_density` | People per sq mile |
| `food_desert_score` | 0 = none, 1 = moderate, 2 = severe |
| `bus_stop_count` | Number of bus stops within 0.25 miles |

The solver will automatically use these once present.
