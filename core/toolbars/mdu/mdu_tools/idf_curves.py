"""
This file is part of Giswater
The program is free software: you can redistribute it and/or modify it under the terms of the GNU
General Public License as published by the Free Software Foundation, either version 3 of the License,
or (at your option) any later version.
"""
# -*- coding: utf-8 -*-
import math
import os
from functools import partial

from qgis.PyQt.QtWidgets import QTableWidgetItem, QFileDialog

from ...ui.ui_manager import MduIdfCurvesUi
from ....libs import tools_qgis, tools_qt
from .... import global_vars
from ...utils import tools_gw


# ---------------------------------------------------------------------------
# Chilean precipitation data from MDU Tables 4.3.1 / 4.3.2
# ---------------------------------------------------------------------------

# Macro-zones defined in the MDU
MACROZONES = [
    "Estepa de Altura",
    "Desierto Arido",
    "Semiarido",
    "Mediterraneo Costero",
    "Metropolitano",
    "Mediterraneo Interior",
    "Templado Lluvioso",
    "Templado Frio",
    "Continental Trasandino",
]

# Stations: {city_name: {"p10_60": P(10,60) in mm, "macrozone": macro-zone name}}
STATIONS = {
    # Estepa de Altura
    "Putre": {"p10_60": 2.5, "macrozone": "Estepa de Altura"},
    "Olague": {"p10_60": 3.0, "macrozone": "Estepa de Altura"},

    # Desierto Arido
    "Arica": {"p10_60": 0.0, "macrozone": "Desierto Arido"},
    "Iquique": {"p10_60": 0.8, "macrozone": "Desierto Arido"},
    "Antofagasta": {"p10_60": 1.5, "macrozone": "Desierto Arido"},
    "Copiapo": {"p10_60": 3.4, "macrozone": "Desierto Arido"},

    # Semiarido
    "La Serena": {"p10_60": 8.1, "macrozone": "Semiarido"},
    "Ovalle": {"p10_60": 9.2, "macrozone": "Semiarido"},
    "Illapel": {"p10_60": 10.5, "macrozone": "Semiarido"},

    # Mediterraneo Costero
    "Valparaiso": {"p10_60": 16.3, "macrozone": "Mediterraneo Costero"},
    "Vina del Mar": {"p10_60": 15.8, "macrozone": "Mediterraneo Costero"},
    "Constitucion": {"p10_60": 17.0, "macrozone": "Mediterraneo Costero"},

    # Metropolitano
    "Santiago (Quinta Normal)": {"p10_60": 12.3, "macrozone": "Metropolitano"},
    "Santiago (Pudahuel)": {"p10_60": 11.8, "macrozone": "Metropolitano"},
    "Santiago (Tobalaba)": {"p10_60": 13.0, "macrozone": "Metropolitano"},

    # Mediterraneo Interior
    "Rancagua": {"p10_60": 14.8, "macrozone": "Mediterraneo Interior"},
    "Talca": {"p10_60": 16.5, "macrozone": "Mediterraneo Interior"},
    "Chillan": {"p10_60": 18.2, "macrozone": "Mediterraneo Interior"},
    "Concepcion": {"p10_60": 18.6, "macrozone": "Mediterraneo Interior"},
    "Los Angeles": {"p10_60": 19.0, "macrozone": "Mediterraneo Interior"},

    # Templado Lluvioso
    "Temuco": {"p10_60": 17.8, "macrozone": "Templado Lluvioso"},
    "Valdivia": {"p10_60": 22.7, "macrozone": "Templado Lluvioso"},
    "Osorno": {"p10_60": 21.5, "macrozone": "Templado Lluvioso"},
    "Puerto Montt": {"p10_60": 18.0, "macrozone": "Templado Lluvioso"},

    # Templado Frio
    "Coyhaique": {"p10_60": 12.0, "macrozone": "Templado Frio"},
    "Chile Chico": {"p10_60": 8.5, "macrozone": "Templado Frio"},
    "Cochrane": {"p10_60": 14.0, "macrozone": "Templado Frio"},

    # Continental Trasandino
    "Punta Arenas": {"p10_60": 5.3, "macrozone": "Continental Trasandino"},
    "Puerto Natales": {"p10_60": 6.8, "macrozone": "Continental Trasandino"},
    "Porvenir": {"p10_60": 4.5, "macrozone": "Continental Trasandino"},
}

# Default return periods (years) and durations (minutes) for IDF curves
DEFAULT_RETURN_PERIODS = [2, 5, 10, 25, 50, 100]
DEFAULT_DURATIONS = [5, 10, 15, 20, 30, 45, 60, 90, 120]


class IdfCurves:
    """Chilean IDF (Intensity-Duration-Frequency) curve generator.

    Implements Bell's relation for sub-hourly rainfall disaggregation as
    described in Chile's Manual de Drenaje Urbano (MDU), plus an alternating
    block design storm generator.
    """

    def __init__(self):

        self.dlg_idf = None
        self.idf_results = {}  # {T: {t: intensity}}
        self.storm_results = []  # [(time_step, incremental_P)]

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def clicked_event(self):
        """Open the IDF curves dialog and wire all signals."""

        self.dlg_idf = MduIdfCurvesUi()
        dlg = self.dlg_idf
        tools_gw.load_settings(dlg)

        macrozone_rows = [[mz, mz] for mz in MACROZONES]
        tools_qt.fill_combo_values(dlg.cmb_macrozone, macrozone_rows)

        rp_rows = [[str(T), T] for T in DEFAULT_RETURN_PERIODS]
        tools_qt.fill_combo_values(dlg.cmb_storm_T, rp_rows)

        tools_qt.set_widget_text(dlg, "txt_return_periods", "2, 5, 10, 25, 50, 100")
        tools_qt.set_widget_text(dlg, "txt_durations", "5, 10, 15, 20, 30, 45, 60, 90, 120")
        tools_qt.set_widget_text(dlg, "txt_storm_duration", "120")
        tools_qt.set_widget_text(dlg, "txt_storm_dt", "10")

        dlg.cmb_macrozone.currentIndexChanged.connect(
            partial(self._on_macrozone_changed)
        )
        dlg.cmb_city.currentIndexChanged.connect(
            partial(self._on_city_changed)
        )
        dlg.btn_calculate.clicked.connect(
            partial(self._on_calculate)
        )
        dlg.btn_export.clicked.connect(
            partial(self._on_export)
        )
        dlg.btn_close.clicked.connect(
            partial(tools_gw.close_dialog, dlg)
        )
        dlg.rejected.connect(
            partial(tools_gw.close_dialog, dlg)
        )

        self._on_macrozone_changed()

        tools_gw.open_dialog(dlg, dlg_name='mdu_idf_curves')

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_macrozone_changed(self):
        """Populate cmb_city with stations belonging to the selected macro-zone."""

        dlg = self.dlg_idf
        selected_mz = tools_qt.get_text(dlg, dlg.cmb_macrozone, return_string_null=False)
        if selected_mz in (None, '', 'null', -1):
            return

        city_rows = []
        for city_name, info in STATIONS.items():
            if info["macrozone"] == selected_mz:
                city_rows.append([city_name, city_name])

        dlg.cmb_city.blockSignals(True)
        dlg.cmb_city.clear()
        tools_qt.fill_combo_values(dlg.cmb_city, city_rows)
        dlg.cmb_city.blockSignals(False)

        self._on_city_changed()

    def _on_city_changed(self):
        """Auto-fill txt_p10_60 when a city is selected."""

        dlg = self.dlg_idf
        selected_city = tools_qt.get_text(dlg, dlg.cmb_city, return_string_null=False)
        if selected_city in (None, '', 'null', -1):
            tools_qt.set_widget_text(dlg, "txt_p10_60", "")
            return

        if selected_city in STATIONS:
            p10_60 = STATIONS[selected_city]["p10_60"]
            tools_qt.set_widget_text(dlg, "txt_p10_60", str(p10_60))
        else:
            tools_qt.set_widget_text(dlg, "txt_p10_60", "")

    def _on_calculate(self):
        """Calculate IDF table and, if on the storm tab, the design storm."""

        try:
            self._calculate_idf()
            self._calculate_design_storm()
        except Exception as e:
            tools_qgis.show_warning(f"Calculation error: {e}")

    def _on_export(self):
        """Export the current IDF results and design storm to a CSV file."""

        try:
            self._export_results()
        except Exception as e:
            tools_qgis.show_warning(f"Export error: {e}")

    # ------------------------------------------------------------------
    # Core IDF calculation
    # ------------------------------------------------------------------

    @staticmethod
    def bell_relation(t, T, p10_60):
        """Apply Bell's relation (MDU equation) to disaggregate rainfall.

        Parameters
        ----------
        t : float
            Duration in minutes (valid range 5 - 120).
        T : float
            Return period in years.
        p10_60 : float
            1-hour rainfall depth for T = 10 yr in mm  [P(10,60)].

        Returns
        -------
        float
            Rainfall depth P(t, T) in mm.
        """

        if p10_60 <= 0:
            return 0.0
        if T <= 0:
            return 0.0
        p_t_T = (0.21 * math.log(T) + 0.52) * (0.54 * t ** 0.25 - 0.50) * p10_60
        return max(p_t_T, 0.0)

    @staticmethod
    def intensity_from_depth(p_mm, t_min):
        """Convert rainfall depth (mm) and duration (min) to intensity (mm/hr).

        i = P / t * 60
        """

        if t_min <= 0:
            return 0.0
        return p_mm / t_min * 60.0

    def _calculate_idf(self):
        """Build the IDF table from user inputs and fill tbl_idf_results."""

        dlg = self.dlg_idf

        p10_60_text = tools_qt.get_text(dlg, dlg.txt_p10_60, return_string_null=False)
        if p10_60_text in (None, '', 'null'):
            tools_qgis.show_warning("Please select a city or enter a P(10,60) value.")
            return
        try:
            p10_60 = float(p10_60_text)
        except ValueError:
            tools_qgis.show_warning("P(10,60) must be a numeric value.")
            return

        rp_text = tools_qt.get_text(dlg, dlg.txt_return_periods, return_string_null=False)
        if rp_text in (None, '', 'null'):
            return_periods = DEFAULT_RETURN_PERIODS
        else:
            try:
                return_periods = sorted(set(int(x.strip()) for x in rp_text.split(',')))
            except ValueError:
                tools_qgis.show_warning("Return periods must be comma-separated integers.")
                return

        dur_text = tools_qt.get_text(dlg, dlg.txt_durations, return_string_null=False)
        if dur_text in (None, '', 'null'):
            durations = DEFAULT_DURATIONS
        else:
            try:
                durations = sorted(set(int(x.strip()) for x in dur_text.split(',')))
            except ValueError:
                tools_qgis.show_warning("Durations must be comma-separated integers.")
                return

        for d in durations:
            if d < 5 or d > 120:
                tools_qgis.show_warning(
                    f"Duration {d} min is outside Bell's valid range (5-120 min)."
                )
                return

        for T in return_periods:
            if T < 2:
                tools_qgis.show_warning(
                    f"Return period {T} yr is too small. Minimum is 2 yr."
                )
                return

        self.idf_results = {}
        for T in return_periods:
            self.idf_results[T] = {}
            for t in durations:
                p_t_T = self.bell_relation(t, T, p10_60)
                intensity = self.intensity_from_depth(p_t_T, t)
                self.idf_results[T][t] = round(intensity, 2)

        self._last_return_periods = return_periods
        self._last_durations = durations
        self._last_p10_60 = p10_60

        self._fill_idf_table(return_periods, durations)

    def _fill_idf_table(self, return_periods, durations):
        """Populate tbl_idf_results QTableWidget with computed intensities."""

        dlg = self.dlg_idf
        tbl = dlg.tbl_idf_results

        n_rows = len(durations)
        n_cols = len(return_periods) + 1

        tbl.clear()
        tbl.setRowCount(n_rows)
        tbl.setColumnCount(n_cols)

        headers = ["Duracion (min)"] + [f"T={T} yr" for T in return_periods]
        tbl.setHorizontalHeaderLabels(headers)

        for row_idx, t in enumerate(durations):
            item_dur = QTableWidgetItem(str(t))
            tbl.setItem(row_idx, 0, item_dur)

            for col_idx, T in enumerate(return_periods):
                intensity = self.idf_results[T][t]
                item_val = QTableWidgetItem(f"{intensity:.2f}")
                tbl.setItem(row_idx, col_idx + 1, item_val)

        tbl.resizeColumnsToContents()

    # ------------------------------------------------------------------
    # Design storm (alternating block method)
    # ------------------------------------------------------------------

    def _calculate_design_storm(self):
        """Generate a design storm using the alternating block method and
        fill tbl_storm_results."""

        dlg = self.dlg_idf

        p10_60_text = tools_qt.get_text(dlg, dlg.txt_p10_60, return_string_null=False)
        if p10_60_text in (None, '', 'null'):
            return
        try:
            p10_60 = float(p10_60_text)
        except ValueError:
            return

        storm_T_text = tools_qt.get_text(dlg, dlg.cmb_storm_T, return_string_null=False)
        if storm_T_text in (None, '', 'null'):
            return
        try:
            storm_T = int(storm_T_text)
        except ValueError:
            return

        dur_text = tools_qt.get_text(dlg, dlg.txt_storm_duration, return_string_null=False)
        if dur_text in (None, '', 'null'):
            return
        try:
            total_duration = int(dur_text)
        except ValueError:
            tools_qgis.show_warning("Storm duration must be a numeric value.")
            return

        dt_text = tools_qt.get_text(dlg, dlg.txt_storm_dt, return_string_null=False)
        if dt_text in (None, '', 'null'):
            return
        try:
            dt = int(dt_text)
        except ValueError:
            tools_qgis.show_warning("Time step (dt) must be a numeric value.")
            return

        if dt <= 0 or total_duration <= 0:
            tools_qgis.show_warning("Duration and dt must be positive values.")
            return

        if total_duration % dt != 0:
            tools_qgis.show_warning(
                "Total storm duration must be an exact multiple of the time step dt."
            )
            return

        n_blocks = total_duration // dt

        cumulative_depths = []
        for k in range(1, n_blocks + 1):
            t_k = k * dt
            t_bell = min(t_k, 120)
            p_depth = self.bell_relation(t_bell, storm_T, p10_60)
            if t_k > 120:
                p_120 = self.bell_relation(120, storm_T, p10_60)
                rate = p_120 / 120.0  # mm/min
                p_depth = p_120 + rate * (t_k - 120)
            cumulative_depths.append(p_depth)

        incremental_depths = [cumulative_depths[0]]
        for k in range(1, len(cumulative_depths)):
            inc = cumulative_depths[k] - cumulative_depths[k - 1]
            incremental_depths.append(max(inc, 0.0))

        incremental_sorted = sorted(incremental_depths, reverse=True)

        arranged = [0.0] * n_blocks
        center = n_blocks // 2

        left = center
        right = center + 1
        for idx, inc in enumerate(incremental_sorted):
            if idx == 0:
                arranged[center] = inc
            elif idx % 2 == 1:
                left -= 1
                if left >= 0:
                    arranged[left] = inc
            else:
                if right < n_blocks:
                    arranged[right] = inc
                    right += 1

        self.storm_results = []
        for k in range(n_blocks):
            time_start = k * dt
            time_end = (k + 1) * dt
            self.storm_results.append({
                "block": k + 1,
                "time_start": time_start,
                "time_end": time_end,
                "incremental_P_mm": round(arranged[k], 3),
                "intensity_mm_hr": round(arranged[k] / dt * 60.0, 2),
            })

        self._last_storm_T = storm_T
        self._last_storm_duration = total_duration
        self._last_storm_dt = dt

        self._fill_storm_table()

    def _fill_storm_table(self):
        """Populate tbl_storm_results QTableWidget with the design storm."""

        dlg = self.dlg_idf
        tbl = dlg.tbl_storm_results

        n_rows = len(self.storm_results)
        n_cols = 5

        tbl.clear()
        tbl.setRowCount(n_rows)
        tbl.setColumnCount(n_cols)

        headers = ["Bloque", "t inicio (min)", "t fin (min)", "P incr. (mm)", "i (mm/hr)"]
        tbl.setHorizontalHeaderLabels(headers)

        for row_idx, block in enumerate(self.storm_results):
            tbl.setItem(row_idx, 0, QTableWidgetItem(str(block["block"])))
            tbl.setItem(row_idx, 1, QTableWidgetItem(str(block["time_start"])))
            tbl.setItem(row_idx, 2, QTableWidgetItem(str(block["time_end"])))
            tbl.setItem(row_idx, 3, QTableWidgetItem(f"{block['incremental_P_mm']:.3f}"))
            tbl.setItem(row_idx, 4, QTableWidgetItem(f"{block['intensity_mm_hr']:.2f}"))

        tbl.resizeColumnsToContents()

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _export_results(self):
        """Export IDF table and design storm to a CSV file."""

        if not self.idf_results:
            tools_qgis.show_warning("No IDF results to export. Please calculate first.")
            return

        file_path, _ = QFileDialog.getSaveFileName(
            self.dlg_idf, "Export IDF Results", "", "CSV files (*.csv)"
        )
        if not file_path:
            return

        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write("# IDF Curves - Manual de Drenaje Urbano (Chile)\n")
                f.write(f"# P(10,60) = {self._last_p10_60} mm\n")

                rp_list = self._last_return_periods
                dur_list = self._last_durations
                f.write("Duracion (min)")
                for T in rp_list:
                    f.write(f",T={T} yr (mm/hr)")
                f.write("\n")

                for t in dur_list:
                    f.write(str(t))
                    for T in rp_list:
                        f.write(f",{self.idf_results[T][t]:.2f}")
                    f.write("\n")

                if self.storm_results:
                    f.write("\n")
                    f.write(f"# Design Storm - Alternating Block Method\n")
                    f.write(f"# T = {self._last_storm_T} yr, "
                            f"Duration = {self._last_storm_duration} min, "
                            f"dt = {self._last_storm_dt} min\n")
                    f.write("Bloque,t inicio (min),t fin (min),P incr. (mm),i (mm/hr)\n")
                    for block in self.storm_results:
                        f.write(
                            f"{block['block']},"
                            f"{block['time_start']},"
                            f"{block['time_end']},"
                            f"{block['incremental_P_mm']:.3f},"
                            f"{block['intensity_mm_hr']:.2f}\n"
                        )

            tools_qgis.show_info(f"Results exported to: {file_path}")

        except OSError as e:
            tools_qgis.show_warning(f"Error writing file: {e}")
