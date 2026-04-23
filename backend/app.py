"""
Food Market Optimizer — Flask API
"""

import json
import geopandas as gpd
import pandas as pd
from flask import Flask, jsonify, request
from flask_cors import CORS

from solver import run_optimization, load_centers

app = Flask(__name__)
CORS(app)

DATA_DIR = "data/"


@app.route("/api/centers", methods=["GET"])
def get_centers():
    """Return all community centers as GeoJSON."""
    df = load_centers()
    features = []
    for _, row in df.iterrows():
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [row["lon"], row["lat"]]},
            "properties": {
                "name": row["name"],
                "zip": row["zip"],
                "address": row.get("address", ""),
            }
        })
    return jsonify({"type": "FeatureCollection", "features": features})


@app.route("/api/zipcodes", methods=["GET"])
def get_zipcodes():
    """Return ZIP code polygons as GeoJSON."""
    gdf = gpd.read_file(DATA_DIR + "zip_codes.gpkg", layer="central_fl_zip")
    gdf = gdf.rename(columns={"ZCTA5CE20": "zip"})
    gdf = gdf[["zip", "geometry"]]

    # Attach center count per ZIP for UI display
    centers_df = load_centers()
    zip_counts = centers_df.groupby("zip").size().to_dict()
    gdf["center_count"] = gdf["zip"].map(zip_counts).fillna(0).astype(int)

    geojson = json.loads(gdf.to_json())
    return jsonify(geojson)


@app.route("/api/zips", methods=["GET"])
def get_zip_list():
    """Return list of unique ZIP codes with center counts."""
    df = load_centers()
    counts = df.groupby("zip").size().reset_index(name="count")
    counts = counts.sort_values("zip")
    return jsonify(counts.to_dict(orient="records"))


@app.route("/api/optimize", methods=["POST"])
def optimize():
    """
    Run the dominating set optimization.

    Body (JSON):
      {
        "mode": "driving" | "walking",
        "threshold_miles": float,        # e.g. 5.0
        "selected_zips": ["32801", ...], # empty = all
        "use_priority": bool
      }
    """
    body = request.get_json(force=True)
    mode            = body.get("mode", "driving")
    threshold_miles = float(body.get("threshold_miles", 5.0))
    selected_zips   = body.get("selected_zips", [])
    use_priority    = bool(body.get("use_priority", False))

    if mode not in ("driving", "walking"):
        return jsonify({"error": "mode must be 'driving' or 'walking'"}), 400
    if threshold_miles <= 0:
        return jsonify({"error": "threshold_miles must be > 0"}), 400

    try:
        result = run_optimization(mode, threshold_miles, selected_zips, use_priority)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(debug=True, port=5000)
