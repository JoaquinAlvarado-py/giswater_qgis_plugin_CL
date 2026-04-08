"""
This file is part of Giswater
The program is free software: you can redistribute it and/or modify it under the terms of the GNU
General Public License as published by the Free Software Foundation, either version 3 of the License,
or (at your option) any later version.
"""
# -*- coding: utf-8 -*-
import math
from functools import partial

from qgis.PyQt.QtWidgets import QTableWidgetItem, QHeaderView

from ....ui.ui_manager import MduTimeOfConcentrationUi
from .....libs import tools_qgis, tools_qt
from ..... import global_vars
from ....utils import tools_gw


# Minimum time of concentration for domiciliary networks (minutes) per MDU guidelines
MIN_TC_MINUTES = 5


class TimeOfConcentration:
    """Time of Concentration (Tc) calculator implementing multiple formulas from Chile's
    Manual de Drenaje Urbano (MDU), Chapter 4.3.

    Supported methods:
        - Kirpich (Eq. 4.3.16)
        - California Culverts Practice (Eq. 4.3.17)
        - Morgali & Linsley (Eq. 4.3.18)
        - Manning-based for channels (Eq. 4.3.19)
        - Velocity-based composite (Eq. 4.3.13 - 4.3.15)
    """

    def __init__(self):
        self.dlg_tc = None

    def clicked_event(self):
        """Main entry point: opens the Time of Concentration dialog and sets up widgets."""

        self.dlg_tc = MduTimeOfConcentrationUi(self)
        dlg = self.dlg_tc
        tools_gw.load_settings(dlg)

        tbl = dlg.tbl_tc_results
        tbl.setColumnCount(4)
        tbl.setHorizontalHeaderLabels(["Metodo", "Tc [min]", "Tc [hr]", "Observacion"])
        header = tbl.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        tbl.setRowCount(0)

        tbl_vel = dlg.tbl_velocity_segments
        tbl_vel.setColumnCount(3)
        tbl_vel.setHorizontalHeaderLabels(["Tramo", "Longitud [m]", "Velocidad [m/s]"])
        vel_header = tbl_vel.horizontalHeader()
        vel_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        vel_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        vel_header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        tbl_vel.setRowCount(0)

        dlg.btn_calculate.clicked.connect(partial(self._calculate))
        dlg.btn_add_segment.clicked.connect(partial(self._add_velocity_segment))
        dlg.btn_remove_segment.clicked.connect(partial(self._remove_velocity_segment))
        dlg.btn_close.clicked.connect(partial(tools_gw.close_dialog, dlg))
        dlg.rejected.connect(partial(tools_gw.close_dialog, dlg))

        tools_gw.open_dialog(dlg, dlg_name='mdu_time_of_concentration')

    # ------------------------------------------------------------------
    # Segment management for velocity-based method
    # ------------------------------------------------------------------

    def _add_velocity_segment(self):
        """Add a new empty row to the velocity segments table."""

        tbl = self.dlg_tc.tbl_velocity_segments
        row = tbl.rowCount()
        tbl.insertRow(row)
        tbl.setItem(row, 0, QTableWidgetItem(str(row + 1)))
        tbl.setItem(row, 1, QTableWidgetItem(""))
        tbl.setItem(row, 2, QTableWidgetItem(""))

    def _remove_velocity_segment(self):
        """Remove the currently selected row (or the last row) from the velocity segments table."""

        tbl = self.dlg_tc.tbl_velocity_segments
        current_row = tbl.currentRow()
        if current_row >= 0:
            tbl.removeRow(current_row)
        elif tbl.rowCount() > 0:
            tbl.removeRow(tbl.rowCount() - 1)

        # Re-number the 'Tramo' column after removal
        for row in range(tbl.rowCount()):
            tbl.setItem(row, 0, QTableWidgetItem(str(row + 1)))

    # ------------------------------------------------------------------
    # Calculation engine
    # ------------------------------------------------------------------

    def _calculate(self):
        """Read inputs, compute Tc for every selected method, fill results table and summary."""

        dlg = self.dlg_tc
        results = []  # list of tuples: (method_name, tc_min, observation)

        length = self._get_float(dlg.txt_length)
        slope = self._get_float(dlg.txt_slope)
        height_diff = self._get_float(dlg.txt_height_diff)
        manning_n = self._get_float(dlg.txt_manning_n)
        intensity = self._get_float(dlg.txt_intensity)

        # ------------------------------------------------------------------
        # 1) Kirpich (Eq. 4.3.16)
        #    Tc = 0.0195 * L^0.77 / S^0.385
        # ------------------------------------------------------------------
        if dlg.chk_kirpich.isChecked():
            if length is not None and slope is not None and slope > 0:
                tc = 0.0195 * math.pow(length, 0.77) / math.pow(slope, 0.385)
                tc, obs = self._apply_min_tc(tc)
                results.append(("Kirpich (Eq. 4.3.16)", tc, obs))
            else:
                results.append(("Kirpich (Eq. 4.3.16)", None,
                                "Requiere Longitud (L) y Pendiente (S) > 0"))

        # ------------------------------------------------------------------
        # 2) California Culverts Practice (Eq. 4.3.17)
        #    Tc = 0.0203 * (L1^3 / H)^0.385
        # ------------------------------------------------------------------
        if dlg.chk_california.isChecked():
            if length is not None and height_diff is not None and height_diff > 0:
                tc = 0.0203 * math.pow(math.pow(length, 3) / height_diff, 0.385)
                tc, obs = self._apply_min_tc(tc)
                results.append(("California Culverts Practice (Eq. 4.3.17)", tc, obs))
            else:
                results.append(("California Culverts Practice (Eq. 4.3.17)", None,
                                "Requiere Longitud (L1) y Desnivel (H) > 0"))

        # ------------------------------------------------------------------
        # 3) Morgali & Linsley (Eq. 4.3.18)
        #    Tc = 7 * L^0.6 * n^0.6 / (i^0.4 * S^0.3)
        # ------------------------------------------------------------------
        if dlg.chk_morgali.isChecked():
            if (length is not None and manning_n is not None and intensity is not None
                    and slope is not None and intensity > 0 and slope > 0):
                tc = (7.0 * math.pow(length, 0.6) * math.pow(manning_n, 0.6)
                      / (math.pow(intensity, 0.4) * math.pow(slope, 0.3)))
                tc, obs = self._apply_min_tc(tc)
                results.append(("Morgali & Linsley (Eq. 4.3.18)", tc, obs))
            else:
                results.append(("Morgali & Linsley (Eq. 4.3.18)", None,
                                "Requiere L, n, i > 0 y S > 0"))

        # ------------------------------------------------------------------
        # 4) Manning-based for channels (Eq. 4.3.19)
        #    V = (1/n) * R^(2/3) * S^(1/2)   then   Tc = L / (60 * V)
        #    Approximate hydraulic radius R for trapezoidal channel
        # ------------------------------------------------------------------
        if dlg.chk_manning.isChecked():
            if (length is not None and manning_n is not None and slope is not None
                    and manning_n > 0 and slope > 0):
                # Use an approximate hydraulic radius.  For a trapezoidal channel the exact
                # R depends on base width, depth and side slopes which are not individual
                # inputs in this simplified tool.  A reasonable default approximation is
                # R ~ 0.3 m (typical urban drainage channel).  This value can be refined
                # by future UI fields if needed.
                r_approx = 0.3  # [m] approximate hydraulic radius
                velocity = (1.0 / manning_n) * math.pow(r_approx, 2.0 / 3.0) * math.pow(slope, 0.5)
                if velocity > 0:
                    tc = length / (60.0 * velocity)
                    tc, obs_tc = self._apply_min_tc(tc)
                    obs = f"R aprox.= {r_approx} m, V= {velocity:.3f} m/s"
                    if obs_tc:
                        obs = f"{obs}. {obs_tc}"
                    results.append(("Manning - Canal (Eq. 4.3.19)", tc, obs))
                else:
                    results.append(("Manning - Canal (Eq. 4.3.19)", None,
                                    "Velocidad calculada = 0"))
            else:
                results.append(("Manning - Canal (Eq. 4.3.19)", None,
                                "Requiere L, n > 0 y S > 0"))

        # ------------------------------------------------------------------
        # 5) Velocity-based composite (Eq. 4.3.13 - 4.3.15)
        #    Tc = Sum(Li / Vi) / 60
        # ------------------------------------------------------------------
        if dlg.chk_velocity.isChecked():
            tc_vel = self._calculate_velocity_method()
            if tc_vel is not None:
                tc_vel, obs = self._apply_min_tc(tc_vel)
                results.append(("Velocidad compuesta (Eq. 4.3.13-15)", tc_vel, obs))
            else:
                results.append(("Velocidad compuesta (Eq. 4.3.13-15)", None,
                                "Verificar tramos: L > 0 y V > 0"))

        self._fill_results_table(results)
        self._fill_summary(results)

    def _calculate_velocity_method(self):
        """Compute Tc using the velocity-based composite method from the segments table.

        Tc = Sum(Li / Vi) / 60   [minutes]

        Returns:
            float or None: Tc in minutes, or None if input is invalid.
        """

        tbl = self.dlg_tc.tbl_velocity_segments
        total_time_seconds = 0.0
        valid_segments = 0

        for row in range(tbl.rowCount()):
            length_item = tbl.item(row, 1)
            velocity_item = tbl.item(row, 2)
            if length_item is None or velocity_item is None:
                continue
            try:
                seg_length = float(length_item.text())
                seg_velocity = float(velocity_item.text())
            except (ValueError, TypeError):
                continue

            if seg_length <= 0 or seg_velocity <= 0:
                continue

            total_time_seconds += seg_length / seg_velocity
            valid_segments += 1

        if valid_segments == 0:
            return None

        return total_time_seconds / 60.0

    # ------------------------------------------------------------------
    # Output helpers
    # ------------------------------------------------------------------

    def _fill_results_table(self, results):
        """Populate tbl_tc_results with computed values.

        Args:
            results: list of tuples (method_name, tc_minutes_or_None, observation_str)
        """

        tbl = self.dlg_tc.tbl_tc_results
        tbl.setRowCount(0)
        tbl.setRowCount(len(results))

        for row, (method, tc_min, obs) in enumerate(results):
            tbl.setItem(row, 0, QTableWidgetItem(str(method)))
            if tc_min is not None:
                tbl.setItem(row, 1, QTableWidgetItem(f"{tc_min:.2f}"))
                tbl.setItem(row, 2, QTableWidgetItem(f"{tc_min / 60.0:.4f}"))
            else:
                tbl.setItem(row, 1, QTableWidgetItem("--"))
                tbl.setItem(row, 2, QTableWidgetItem("--"))
            tbl.setItem(row, 3, QTableWidgetItem(str(obs) if obs else ""))

    def _fill_summary(self, results):
        """Build a text summary of computed Tc values and write it to txt_tc_summary.

        The recommended Tc is the average of all valid (non-None) computed values.

        Args:
            results: list of tuples (method_name, tc_minutes_or_None, observation_str)
        """

        valid = [(name, tc) for name, tc, _ in results if tc is not None]

        lines = []
        lines.append("=" * 55)
        lines.append("RESUMEN - Tiempo de Concentracion (Tc)")
        lines.append("Manual de Drenaje Urbano - Chile")
        lines.append("=" * 55)
        lines.append("")

        if not valid:
            lines.append("No se obtuvieron resultados validos.")
            lines.append("Revise los datos de entrada y los metodos seleccionados.")
        else:
            lines.append(f"{'Metodo':<45} {'Tc [min]':>10}")
            lines.append("-" * 55)
            for name, tc in valid:
                lines.append(f"{name:<45} {tc:>10.2f}")

            lines.append("-" * 55)

            avg_tc = sum(tc for _, tc in valid) / len(valid)
            avg_tc_hr = avg_tc / 60.0

            lines.append("")
            lines.append(f"Tc promedio (recomendado):  {avg_tc:.2f} min  ({avg_tc_hr:.4f} hr)")

            if avg_tc <= MIN_TC_MINUTES:
                lines.append(f"NOTA: Tc minimo aplicable = {MIN_TC_MINUTES} min (red domiciliaria)")

            min_tc = min(tc for _, tc in valid)
            max_tc = max(tc for _, tc in valid)
            if len(valid) > 1:
                lines.append("")
                lines.append(f"Tc minimo calculado:       {min_tc:.2f} min")
                lines.append(f"Tc maximo calculado:       {max_tc:.2f} min")

        lines.append("")
        lines.append("=" * 55)

        self.dlg_tc.txt_tc_summary.setText("\n".join(lines))

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    @staticmethod
    def _get_float(widget):
        """Safely read a float value from a QLineEdit widget.

        Args:
            widget: QLineEdit (or compatible) widget.

        Returns:
            float or None: The parsed value, or None if empty / invalid.
        """

        try:
            text = tools_qt.get_text(widget, return_string_null=False, add_id=False)
            if text in (None, "", "null", "NULL"):
                return None
            return float(text)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _apply_min_tc(tc_value):
        """Enforce the minimum Tc = 5 minutes rule for domiciliary networks.

        Args:
            tc_value (float): Computed Tc in minutes.

        Returns:
            tuple: (adjusted_tc, observation_string)
                - adjusted_tc is max(tc_value, MIN_TC_MINUTES)
                - observation_string indicates if the minimum was applied
        """

        if tc_value < MIN_TC_MINUTES:
            return MIN_TC_MINUTES, f"Tc calculado ({tc_value:.2f} min) < minimo; se aplica Tc = {MIN_TC_MINUTES} min"
        return tc_value, ""
