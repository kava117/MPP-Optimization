"""
UpOrlando Community Center Priority Analyzer
---------------------------------------------
Main GUI application. Local Windows desktop app for scoring and ranking
community centers by food access / transit equity criteria.

Features:
    - Rankings tab: sortable table of all scored centers
    - Map tab: Folium map showing centers color-coded by priority tier
    - Add Site tab: form to add new candidate centers (persists to SQLite)
    - Export: save current rankings as CSV

Run: python main.py
"""

from __future__ import annotations
import sys
import os
from pathlib import Path
import tempfile
import pandas as pd

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QTableWidget, QTableWidgetItem, QPushButton, QLabel, QLineEdit,
    QFormLayout, QMessageBox, QHeaderView, QFileDialog, QGroupBox,
    QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QSplitter,
)
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QFont
#from PySide6.QtWebEngineWidgets import QWebEngineView

import folium

import scoring
import database

# ─── Paths ────────────────────────────────────────────────────────────────────
# Two paths matter:
#   - RESOURCE_DIR: where bundled read-only files live (CSV, etc.)
#       In dev: the project folder.
#       In PyInstaller .exe: the temp extraction folder (sys._MEIPASS).
#   - USER_DATA_DIR: where the app writes user-editable data (SQLite DB).
#       Always %APPDATA%\UpOrlandoAnalyzer on Windows so it persists across launches.

def _get_resource_dir() -> Path:
    """Folder containing bundled read-only resources (CSV, etc.)."""
    if hasattr(sys, "_MEIPASS"):
        # Running as PyInstaller bundle
        return Path(sys._MEIPASS)
    return Path(__file__).parent

def _get_user_data_dir() -> Path:
    """Persistent per-user folder for the app's writable data."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    app_dir = base / "UpOrlandoAnalyzer"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir

RESOURCE_DIR = _get_resource_dir()
USER_DATA_DIR = _get_user_data_dir()
DATA_CSV = RESOURCE_DIR / "weighted_centers.csv"
DB_PATH = database.get_db_path(USER_DATA_DIR)


# ─── Priority tier colors (for table + map) ──────────────────────────────────
TIER_COLORS = {
    "High priority":              "#dc2626",   # red
    "Medium priority":            "#f59e0b",   # amber
    "Low priority":               "#10b981",   # green
    "Ineligible (missing data)":  "#9ca3af",   # gray
}


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("UpOrlando Community Center Priority Analyzer")
        self.resize(1400, 900)

        # Initialize database
        database.init_db(DB_PATH)

        # Load original data once
        self.original_df = pd.read_csv(DATA_CSV)

        # Build UI
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self._build_rankings_tab()
        self._build_map_tab()
        self._build_add_site_tab()
        self._build_about_tab()

        # Initial analysis run
        self.run_analysis()

    # ── Data pipeline ─────────────────────────────────────────────────────────

    def get_combined_data(self) -> pd.DataFrame:
        """Merge original CSV data with user-added centers from the database."""
        user_df = database.load_user_centers(DB_PATH)
        combined = database.merge_centers(self.original_df, user_df)
        return combined

    def run_analysis(self):
        """Re-score all centers and refresh the table + map."""
        combined = self.get_combined_data()
        self.ranked = scoring.rank_centers(combined)
        self._refresh_rankings_table()
        self._refresh_map()

    # ── Rankings tab ──────────────────────────────────────────────────────────

    def _build_rankings_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Header with summary + buttons
        header = QHBoxLayout()
        self.summary_label = QLabel("Loading...")
        self.summary_label.setStyleSheet("font-size: 13px; padding: 6px;")
        header.addWidget(self.summary_label)
        header.addStretch()

        btn_refresh = QPushButton("Re-run Analysis")
        btn_refresh.clicked.connect(self.run_analysis)
        header.addWidget(btn_refresh)

        btn_export = QPushButton("Export Rankings (CSV)")
        btn_export.clicked.connect(self.export_rankings)
        header.addWidget(btn_export)

        layout.addLayout(header)

        # Table
        self.table = QTableWidget()
        self.table.setSortingEnabled(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        self.tabs.addTab(tab, "Rankings")

    def _refresh_rankings_table(self):
        """Populate the rankings table with current scored data."""
        cols = [
            "Rank", "Name", "Source", "Score", "Priority Tier",
            "Income", "Population", "Density", "Food Desert", "Bus Stops",
            "Address",
        ]
        self.table.setSortingEnabled(False)
        self.table.setColumnCount(len(cols))
        self.table.setHorizontalHeaderLabels(cols)
        self.table.setRowCount(len(self.ranked))

        for i, row in self.ranked.iterrows():
            rank_val = i + 1 if row["eligible"] else ""
            source = row.get("source", "original")
            source_label = "User added" if source == "user_added" else "Original"

            # Use raw data from the scored df — normalize_columns already ran
            values = [
                str(rank_val),
                str(row.get("name", "")),
                source_label,
                str(row["total_score"]) if row["eligible"] else "—",
                str(row["priority_tier"]),
                str(row.get("s_income", "")),
                str(row.get("s_population", "")),
                str(row.get("s_density", "")),
                str(row.get("s_food_desert", "")),
                str(row.get("s_bus_stops", "")),
                str(row.get("address", "")),
            ]
            for j, val in enumerate(values):
                item = QTableWidgetItem(val)
                # Make numeric columns sort numerically
                if j in (0, 3, 5, 6, 7, 8, 9):
                    try:
                        item.setData(Qt.EditRole, float(val))
                    except (ValueError, TypeError):
                        pass
                # Color tier cell
                if j == 4:
                    color = TIER_COLORS.get(val, "#ffffff")
                    item.setBackground(QColor(color))
                    item.setForeground(QColor("#ffffff"))
                    item.setFont(QFont("", -1, QFont.Bold))
                # Highlight user-added rows
                if source == "user_added" and j == 2:
                    item.setBackground(QColor("#dbeafe"))
                    item.setFont(QFont("", -1, QFont.Bold))
                self.table.setItem(i, j, item)

        self.table.setSortingEnabled(True)
        self.table.resizeColumnsToContents()
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.Stretch)  # Name column
        header.setSectionResizeMode(10, QHeaderView.Stretch)  # Address column

        # Summary
        eligible = self.ranked["eligible"].sum()
        ineligible = (~self.ranked["eligible"]).sum()
        user_added = (self.ranked.get("source", pd.Series()) == "user_added").sum()
        top_3 = self.ranked[self.ranked["eligible"]].head(3)["name"].tolist()
        top_3_str = ", ".join(top_3) if top_3 else "—"
        self.summary_label.setText(
            f"<b>{len(self.ranked)} centers scored</b> "
            f"({eligible} eligible, {ineligible} ineligible, "
            f"{user_added} user-added) &nbsp;|&nbsp; "
            f"Top priorities: <b>{top_3_str}</b>"
        )

    def export_rankings(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Rankings", "uporlando_rankings.csv",
            "CSV files (*.csv)"
        )
        if not path:
            return
        export_cols = [
            "name", "address", "zip_code", "lat", "lon",
            "total_score", "priority_tier", "eligible", "source",
            "s_income", "s_population", "s_density", "s_food_desert", "s_bus_stops",
        ]
        export_df = self.ranked[[c for c in export_cols if c in self.ranked.columns]]
        export_df.insert(0, "rank", range(1, len(export_df) + 1))
        export_df.to_csv(path, index=False)
        QMessageBox.information(self, "Export Complete",
                                f"Saved {len(export_df)} rows to:\n{path}")

  # ── Map tab ───────────────────────────────────────────────────────────────

    def _build_map_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)

        info = QLabel(
            "<h3>Interactive Map</h3>"
            "<p>The map opens in your default web browser for the best experience. "
            "Click the button below to generate and view the current rankings on a map of Orlando.</p>"
            "<p><b>Map Legend:</b> &nbsp;"
            "<span style='background:#dc2626;color:white;padding:2px 8px;'>High priority</span> &nbsp;"
            "<span style='background:#f59e0b;color:white;padding:2px 8px;'>Medium priority</span> &nbsp;"
            "<span style='background:#10b981;color:white;padding:2px 8px;'>Low priority</span> &nbsp;"
            "<span style='background:#9ca3af;color:white;padding:2px 8px;'>Ineligible</span></p>"
            "<p>User-added centers appear with a blue border. Click any dot for the center's details.</p>"
        )
        info.setWordWrap(True)
        info.setStyleSheet("padding: 20px;")
        layout.addWidget(info)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_open_map = QPushButton("Open Map in Browser")
        btn_open_map.setStyleSheet(
            "background: #2563eb; color: white; padding: 12px 24px; "
            "font-size: 14px; font-weight: bold;"
        )
        btn_open_map.clicked.connect(self.open_map_in_browser)
        btn_row.addWidget(btn_open_map)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self.map_status = QLabel("")
        self.map_status.setStyleSheet("padding: 8px; color: #10b981;")
        self.map_status.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.map_status)

        layout.addStretch()
        self.tabs.addTab(tab, "Map")

    def _refresh_map(self):
        """Regenerate the Folium map (writes to temp file, user opens in browser)."""
        # Center on Orlando
        m = folium.Map(location=[28.5383, -81.3792], zoom_start=11,
                       tiles="CartoDB positron")

        # Add centers
        df = self.ranked
        for _, row in df.iterrows():
            lat = row.get("lat")
            lon = row.get("lon")
            if pd.isna(lat) or pd.isna(lon):
                continue
            color = TIER_COLORS.get(row["priority_tier"], "#9ca3af")
            is_user = row.get("source") == "user_added"

            name = row.get("name", "Unnamed")
            score_str = str(row["total_score"]) if row["eligible"] else "N/A (missing data)"
            popup_html = f"""
                <div style='font-family: sans-serif; min-width: 220px;'>
                    <b style='font-size: 14px;'>{name}</b><br>
                    <i>{row.get('address', '')}</i><br><br>
                    <b>Priority Score:</b> {score_str} / 15<br>
                    <b>Tier:</b> {row['priority_tier']}<br>
                    {"<b>Source:</b> User-added<br>" if is_user else ""}
                </div>
            """
            folium.CircleMarker(
                location=[lat, lon],
                radius=9 if is_user else 7,
                popup=folium.Popup(popup_html, max_width=300),
                tooltip=f"{name} (Score: {score_str})",
                color="#1e40af" if is_user else "#ffffff",
                weight=3 if is_user else 1,
                fill=True,
                fill_color=color,
                fill_opacity=0.85,
            ).add_to(m)

        # Write to temp HTML file (will be opened on demand)
        self.map_html_path = Path(tempfile.gettempdir()) / "uporlando_map.html"
        m.save(str(self.map_html_path))

    def open_map_in_browser(self):
        """Open the currently-generated map in the user's default browser."""
        import webbrowser
        if not hasattr(self, "map_html_path") or not self.map_html_path.exists():
            self._refresh_map()
        webbrowser.open(self.map_html_path.as_uri())
        self.map_status.setText(
            f"✓ Map opened in browser ({len(self.ranked)} centers). "
            "Re-run Analysis on the Rankings tab to refresh the map with new data."
        )

    # ── Add Site tab ──────────────────────────────────────────────────────────

    def _build_add_site_tab(self):
        tab = QWidget()
        main_layout = QVBoxLayout(tab)

        info = QLabel(
            "Add a new candidate community center. The app will score it "
            "using the same criteria as the existing centers. User-added "
            "sites are saved locally and persist between app sessions."
        )
        info.setWordWrap(True)
        info.setStyleSheet("padding: 8px; background: #eff6ff; border-radius: 4px;")
        main_layout.addWidget(info)

        # Form
        form_group = QGroupBox("New Community Center")
        form = QFormLayout(form_group)

        self.add_name = QLineEdit()
        self.add_name.setPlaceholderText("e.g., New Pine Hills Food Hub")
        form.addRow("Name *:", self.add_name)

        self.add_address = QLineEdit()
        self.add_address.setPlaceholderText("Full street address")
        form.addRow("Address:", self.add_address)

        self.add_zip = QLineEdit()
        self.add_zip.setPlaceholderText("e.g., 32808")
        form.addRow("Zip Code:", self.add_zip)

        # Coordinates
        coord_row = QHBoxLayout()
        self.add_lat = QDoubleSpinBox()
        self.add_lat.setRange(27.0, 29.5)
        self.add_lat.setDecimals(6)
        self.add_lat.setValue(28.5383)
        self.add_lat.setSingleStep(0.001)
        self.add_lon = QDoubleSpinBox()
        self.add_lon.setRange(-82.0, -80.5)
        self.add_lon.setDecimals(6)
        self.add_lon.setValue(-81.3792)
        self.add_lon.setSingleStep(0.001)
        coord_row.addWidget(QLabel("Lat:"))
        coord_row.addWidget(self.add_lat)
        coord_row.addWidget(QLabel("Lon:"))
        coord_row.addWidget(self.add_lon)
        form.addRow("Coordinates *:", coord_row)

        # Scoring inputs
        scoring_group = QGroupBox("Scoring Inputs (demographic context of the zip code)")
        scoring_layout = QFormLayout(scoring_group)

        self.add_bus = QSpinBox()
        self.add_bus.setRange(0, 100)
        self.add_bus.setSuffix(" stops within range")
        scoring_layout.addRow("Bus Stop Count:", self.add_bus)

        self.add_income = QSpinBox()
        self.add_income.setRange(0, 300_000)
        self.add_income.setValue(60_000)
        self.add_income.setSuffix(" $/yr")
        self.add_income.setSingleStep(1000)
        scoring_layout.addRow("Median Income:", self.add_income)

        self.add_pop = QSpinBox()
        self.add_pop.setRange(0, 200_000)
        self.add_pop.setValue(20_000)
        self.add_pop.setSingleStep(1000)
        scoring_layout.addRow("Population Size (zip):", self.add_pop)

        self.add_density = QSpinBox()
        self.add_density.setRange(0, 50_000)
        self.add_density.setValue(3_000)
        self.add_density.setSingleStep(100)
        self.add_density.setSuffix(" per sq mi")
        scoring_layout.addRow("Population Density:", self.add_density)

        self.add_food_desert = QComboBox()
        self.add_food_desert.addItems(["0 — Not a food desert",
                                        "1 — Partial food desert",
                                        "2 — Confirmed food desert"])
        scoring_layout.addRow("Food Desert Score:", self.add_food_desert)

        self.add_submitter = QLineEdit()
        self.add_submitter.setPlaceholderText("Your name (for tracking who added what)")
        scoring_layout.addRow("Added By:", self.add_submitter)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_submit = QPushButton("Add Center & Re-run Analysis")
        btn_submit.setStyleSheet(
            "background: #2563eb; color: white; padding: 8px 16px; font-weight: bold;"
        )
        btn_submit.clicked.connect(self.submit_new_center)
        btn_row.addWidget(btn_submit)

        main_layout.addWidget(form_group)
        main_layout.addWidget(scoring_group)
        main_layout.addLayout(btn_row)

        # Existing user additions
        existing_group = QGroupBox("User-added centers (from this install)")
        existing_layout = QVBoxLayout(existing_group)

        # Scroll area holds dynamic list of user centers with delete buttons
        from PySide6.QtWidgets import QScrollArea
        self.user_list_scroll = QScrollArea()
        self.user_list_scroll.setWidgetResizable(True)
        self.user_list_scroll.setMaximumHeight(200)
        self.user_list_container = QWidget()
        self.user_list_layout = QVBoxLayout(self.user_list_container)
        self.user_list_layout.setContentsMargins(4, 4, 4, 4)
        self.user_list_scroll.setWidget(self.user_list_container)
        existing_layout.addWidget(self.user_list_scroll)

        self._refresh_user_list()
        main_layout.addWidget(existing_group)
        self._refresh_user_list()
        main_layout.addWidget(existing_group)

        main_layout.addStretch()
        self.tabs.addTab(tab, "Add Site")

    def _refresh_user_list(self):
        """Refresh the list of user-added centers with per-row delete buttons."""
        # Clear existing rows
        while self.user_list_layout.count():
            item = self.user_list_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        user_df = database.load_user_centers(DB_PATH)

        if user_df.empty:
            lbl = QLabel("No user-added centers yet.")
            lbl.setStyleSheet("color: #6b7280; padding: 8px;")
            self.user_list_layout.addWidget(lbl)
            self.user_list_layout.addStretch()
            return

        for _, row in user_df.iterrows():
            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(4, 2, 4, 2)

            info = QLabel(
                f"<b>{row['name']}</b> "
                f"<span style='color:#6b7280;'>— added by "
                f"{row['added_by'] or 'unknown'} at {row['added_at']}</span>"
            )
            info.setWordWrap(True)
            row_layout.addWidget(info, stretch=1)

            btn_delete = QPushButton("Delete")
            btn_delete.setStyleSheet(
                "background: #dc2626; color: white; padding: 4px 12px; font-weight: bold;"
            )
            btn_delete.setMaximumWidth(80)
            # Capture id and name in lambda defaults to avoid closure issues
            cid = int(row["id"])
            cname = str(row["name"])
            btn_delete.clicked.connect(
                lambda checked=False, i=cid, n=cname: self.delete_user_center(i, n)
            )
            row_layout.addWidget(btn_delete)

            self.user_list_layout.addWidget(row_widget)

        self.user_list_layout.addStretch()

    def submit_new_center(self):
        name = self.add_name.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing Name",
                                "Please enter a name for the new center.")
            return

        food_desert_map = {0: 0, 1: 1, 2: 2}
        food_desert_score = self.add_food_desert.currentIndex()

        center = {
            "name": name,
            "address": self.add_address.text().strip(),
            "zip_code": self.add_zip.text().strip(),
            "lat": self.add_lat.value(),
            "lon": self.add_lon.value(),
            "bus_stop_count": self.add_bus.value(),
            "median_income": self.add_income.value(),
            "population_size": self.add_pop.value(),
            "pop_density": self.add_density.value(),
            "food_desert_score": food_desert_score,
            "added_by": self.add_submitter.text().strip() or "anonymous",
        }

        database.add_center(DB_PATH, center)

        # Clear form
        self.add_name.clear()
        self.add_address.clear()
        self.add_zip.clear()

        # Refresh everything
        self._refresh_user_list()
        self.run_analysis()

        QMessageBox.information(
            self, "Center Added",
            f"'{name}' has been added and the analysis has been re-run.\n\n"
            "Check the Rankings tab to see its score."
        )
        
    def delete_user_center(self, center_id: int, center_name: str):
        """Delete a user-added center after confirmation."""
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            f"Delete user-added center '{center_name}'?\n\n"
            "This only removes it from your local data. "
            "Original (built-in) community centers cannot be deleted.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        database.delete_center(DB_PATH, center_id)
        self._refresh_user_list()
        self.run_analysis()

        QMessageBox.information(
            self, "Deleted",
            f"'{center_name}' has been removed. Analysis has been re-run."
        )
    # ── About tab ─────────────────────────────────────────────────────────────

    def _build_about_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setHtml("""
            <h2>UpOrlando Community Center Priority Analyzer</h2>
            <p>This tool scores community centers in the Orlando metro area
            on 5 weighted factors to help identify the best locations for
            food access and transit equity interventions.</p>

            <h3>Scoring criteria (each 1–3 points, max 15):</h3>
            <ul>
                <li><b>Median income</b> (inverted): lower income = higher priority</li>
                <li><b>Population size</b>: larger = higher priority</li>
                <li><b>Population density</b>: denser = higher priority</li>
                <li><b>Food desert score</b>: more severe = higher priority</li>
                <li><b>Bus stop count</b>: fewer stops = higher priority (more need)</li>
            </ul>

            <h3>Priority tiers:</h3>
            <ul>
                <li><b>High priority</b>: 12–15 points</li>
                <li><b>Medium priority</b>: 9–11 points</li>
                <li><b>Low priority</b>: 6–8 points</li>
                <li><b>Ineligible</b>: missing core demographic data</li>
            </ul>

            <p><i>Based on analysis methodology developed by the UpOrlando
            student team. This is v1 — a simplified ranking without the
            graph dominating set selection. A future v2 could add that back.</i></p>
        """)
        layout.addWidget(text)
        self.tabs.addTab(tab, "About")


def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
