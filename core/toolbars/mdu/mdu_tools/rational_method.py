"""
This file is part of Giswater
The program is free software: you can redistribute it and/or modify it under the terms of the GNU
General Public License as published by the Free Software Foundation, either version 3 of the License,
or (at your option) any later version.
"""
# -*- coding: utf-8 -*-
from functools import partial

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import (
    QComboBox,
    QHeaderView,
    QTableWidgetItem,
)

from .... import global_vars
from ....libs import tools_qgis, tools_qt
from ...utils import tools_gw
from ...ui.ui_manager import MduRationalMethodUi


# Chilean runoff coefficient reference values (MDU Tables 4.3.15 - 4.3.17)
LAND_USE_COEFFICIENTS = {
    "Techos/Tejados": (0.75, 0.95),
    "Pavimento asfaltico": (0.70, 0.95),
    "Pavimento hormigon": (0.80, 0.95),
    "Adoquin": (0.50, 0.70),
    "Grava/Ripio": (0.25, 0.60),
    "Areas verdes (plano <2%)": (0.05, 0.25),
    "Areas verdes (pendiente 2-7%)": (0.10, 0.35),
    "Areas verdes (pendiente >7%)": (0.15, 0.45),
    "Zonas boscosas": (0.05, 0.25),
    "Terreno sin vegetacion": (0.20, 0.60),
}

LAND_USE_NAMES = list(LAND_USE_COEFFICIENTS.keys())


class RationalMethod:
    """Rational Method / Modified Rational Method calculator.

    Implements the formulas from Chile's Manual de Drenaje Urbano (MDU):
      - Simple Rational Method (Eq. 4.3.20): Q = C * i * A / 3.6
      - Modified Rational Method with Temez coefficient (Eq. 4.3.22):
            Q = K * C * i * A / 3.6
            K = 1 + Tc^1.25 / (Tc^1.25 + 14)
      - Weighted runoff coefficient from land use areas
      - Hydrograph generation (triangular / trapezoidal)
    """

    def __init__(self):

        self.iface = global_vars.iface
        self.dlg = None

    # -------------------------------------------------------------------------
    # Public entry point
    # -------------------------------------------------------------------------

    def clicked_event(self):
        """Open the Rational Method dialog and wire up all signals."""

        self.dlg = MduRationalMethodUi()
        tools_gw.load_settings(self.dlg)

        self.dlg.cmb_c_method.clear()
        self.dlg.cmb_c_method.addItems([
            "Valor directo",
            "Ponderado por uso de suelo",
        ])

        self._setup_landuse_table()
        self._setup_hydrograph_table()
        self._toggle_landuse_panel(self.dlg.cmb_c_method.currentText())

        self.dlg.cmb_c_method.currentTextChanged.connect(
            partial(self._on_c_method_changed)
        )
        self.dlg.btn_add_landuse.clicked.connect(
            partial(self._add_landuse_row)
        )
        self.dlg.btn_remove_landuse.clicked.connect(
            partial(self._remove_landuse_row)
        )
        self.dlg.btn_calc_c.clicked.connect(
            partial(self._calculate_weighted_c)
        )
        self.dlg.btn_calculate.clicked.connect(
            partial(self._calculate)
        )
        self.dlg.btn_close.clicked.connect(
            partial(tools_gw.close_dialog, self.dlg)
        )

        tools_gw.open_dialog(self.dlg, dlg_name="mdu_rational_method")

    # -------------------------------------------------------------------------
    # UI helpers
    # -------------------------------------------------------------------------

    def _setup_landuse_table(self):
        """Configure tbl_landuse columns and headers."""

        tbl = self.dlg.tbl_landuse
        headers = ["Uso de suelo", "Area [m2]", "C min", "C max", "C adoptado"]
        tbl.setColumnCount(len(headers))
        tbl.setHorizontalHeaderLabels(headers)
        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tbl.setSelectionBehavior(tbl.SelectionBehavior.SelectRows)
        tbl.setRowCount(0)

    def _setup_hydrograph_table(self):
        """Configure tbl_hydrograph columns and headers."""

        tbl = self.dlg.tbl_hydrograph
        headers = ["Tiempo [min]", "Q [l/s]"]
        tbl.setColumnCount(len(headers))
        tbl.setHorizontalHeaderLabels(headers)
        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        tbl.setRowCount(0)

    def _toggle_landuse_panel(self, method_text):
        """Show / hide land-use table and related buttons based on C method."""

        is_weighted = (method_text == "Ponderado por uso de suelo")
        self.dlg.tbl_landuse.setVisible(is_weighted)
        self.dlg.btn_add_landuse.setVisible(is_weighted)
        self.dlg.btn_remove_landuse.setVisible(is_weighted)
        self.dlg.btn_calc_c.setVisible(is_weighted)
        # When using direct value, allow manual editing of txt_c_value
        self.dlg.txt_c_value.setReadOnly(is_weighted)

    # -------------------------------------------------------------------------
    # Signal handlers
    # -------------------------------------------------------------------------

    def _on_c_method_changed(self, text=None):
        """Handle change in cmb_c_method."""

        if text is None:
            text = self.dlg.cmb_c_method.currentText()
        self._toggle_landuse_panel(text)

    def _add_landuse_row(self):
        """Add a new row to tbl_landuse with a QComboBox for land-use type."""

        tbl = self.dlg.tbl_landuse
        row = tbl.rowCount()
        tbl.insertRow(row)

        cmb_landuse = QComboBox()
        cmb_landuse.addItems(LAND_USE_NAMES)
        cmb_landuse.currentTextChanged.connect(
            partial(self._on_landuse_type_changed, row)
        )
        tbl.setCellWidget(row, 0, cmb_landuse)

        tbl.setItem(row, 1, QTableWidgetItem(""))

        default_name = LAND_USE_NAMES[0]
        c_min, c_max = LAND_USE_COEFFICIENTS[default_name]

        item_cmin = QTableWidgetItem(f"{c_min:.2f}")
        item_cmin.setFlags(item_cmin.flags() & ~Qt.ItemFlag.ItemIsEditable)
        tbl.setItem(row, 2, item_cmin)

        item_cmax = QTableWidgetItem(f"{c_max:.2f}")
        item_cmax.setFlags(item_cmax.flags() & ~Qt.ItemFlag.ItemIsEditable)
        tbl.setItem(row, 3, item_cmax)

        c_adopted = round((c_min + c_max) / 2, 2)
        tbl.setItem(row, 4, QTableWidgetItem(f"{c_adopted:.2f}"))

    def _remove_landuse_row(self):
        """Remove the currently selected row from tbl_landuse."""

        tbl = self.dlg.tbl_landuse
        current_row = tbl.currentRow()
        if current_row >= 0:
            tbl.removeRow(current_row)
        elif tbl.rowCount() > 0:
            # If nothing selected, remove the last row
            tbl.removeRow(tbl.rowCount() - 1)

    def _on_landuse_type_changed(self, row, text):
        """Update C min / C max when the land-use combo changes."""

        tbl = self.dlg.tbl_landuse
        if text not in LAND_USE_COEFFICIENTS:
            return

        c_min, c_max = LAND_USE_COEFFICIENTS[text]

        item_cmin = QTableWidgetItem(f"{c_min:.2f}")
        item_cmin.setFlags(item_cmin.flags() & ~Qt.ItemFlag.ItemIsEditable)
        tbl.setItem(row, 2, item_cmin)

        item_cmax = QTableWidgetItem(f"{c_max:.2f}")
        item_cmax.setFlags(item_cmax.flags() & ~Qt.ItemFlag.ItemIsEditable)
        tbl.setItem(row, 3, item_cmax)

        c_adopted = round((c_min + c_max) / 2, 2)
        tbl.setItem(row, 4, QTableWidgetItem(f"{c_adopted:.2f}"))

    def _calculate_weighted_c(self):
        """Calculate the area-weighted runoff coefficient and display in txt_c_value."""

        tbl = self.dlg.tbl_landuse
        sum_ca = 0.0
        sum_a = 0.0

        for row in range(tbl.rowCount()):
            try:
                area = float(tbl.item(row, 1).text())
                c_adopted = float(tbl.item(row, 4).text())
            except (ValueError, TypeError, AttributeError):
                msg = f"Fila {row + 1}: valores invalidos de area o coeficiente C adoptado."
                tools_qgis.show_warning(msg)
                return

            if area <= 0:
                msg = f"Fila {row + 1}: el area debe ser mayor que cero."
                tools_qgis.show_warning(msg)
                return

            sum_ca += c_adopted * area
            sum_a += area

        if sum_a == 0:
            msg = "No hay filas en la tabla de usos de suelo o el area total es cero."
            tools_qgis.show_warning(msg)
            return

        c_weighted = round(sum_ca / sum_a, 4)
        tools_qt.set_widget_text(self.dlg, "txt_c_value", f"{c_weighted:.4f}")

    # -------------------------------------------------------------------------
    # Core calculation
    # -------------------------------------------------------------------------

    def _calculate(self):
        """Run the Rational Method calculation, fill results and hydrograph."""

        try:
            area = float(tools_qt.get_text(self.dlg, "txt_area", False, False))
        except (ValueError, TypeError):
            tools_qgis.show_warning("Ingrese un valor valido para el area (m2).")
            return

        try:
            intensity = float(tools_qt.get_text(self.dlg, "txt_intensity", False, False))
        except (ValueError, TypeError):
            tools_qgis.show_warning("Ingrese un valor valido para la intensidad (mm/hr).")
            return

        try:
            c_value = float(tools_qt.get_text(self.dlg, "txt_c_value", False, False))
        except (ValueError, TypeError):
            tools_qgis.show_warning("Ingrese o calcule un valor valido para el coeficiente C.")
            return

        if area <= 0 or intensity <= 0 or c_value <= 0:
            tools_qgis.show_warning("Area, intensidad y coeficiente C deben ser mayores que cero.")
            return

        use_modified = self.dlg.rbt_modified.isChecked()
        tc = None
        K = 1.0

        if use_modified:
            try:
                tc = float(tools_qt.get_text(self.dlg, "txt_tc", False, False))
            except (ValueError, TypeError):
                tools_qgis.show_warning(
                    "Ingrese un valor valido para el tiempo de concentracion Tc (min)."
                )
                return
            if tc <= 0:
                tools_qgis.show_warning("El tiempo de concentracion debe ser mayor que cero.")
                return

            # Temez coefficient (MDU Eq. 4.3.22)
            K = self._calc_temez_K(tc)

        # Eq. 4.3.20 / 4.3.22: Q = K * C * i * A / 3.6
        Q = K * c_value * intensity * area / 3.6

        try:
            duration = float(tools_qt.get_text(self.dlg, "txt_duration", False, False))
        except (ValueError, TypeError):
            tools_qgis.show_warning(
                "Ingrese un valor valido para la duracion de la lluvia D (min)."
            )
            return
        if duration <= 0:
            tools_qgis.show_warning("La duracion de la lluvia debe ser mayor que cero.")
            return

        # If simple method and no Tc provided, default Tc = D (steady-state)
        if not use_modified:
            tc_text = tools_qt.get_text(self.dlg, "txt_tc", False, False)
            try:
                tc = float(tc_text) if tc_text else duration
            except (ValueError, TypeError):
                tc = duration
            if tc <= 0:
                tc = duration

        hydrograph = self._generate_hydrograph(Q, duration, tc)
        self._fill_results(Q, K, c_value, intensity, area, tc, duration, use_modified)
        self._fill_hydrograph_table(hydrograph)

    # -------------------------------------------------------------------------
    # Formulas
    # -------------------------------------------------------------------------

    @staticmethod
    def _calc_temez_K(tc):
        """Temez uniformity coefficient K (MDU Eq. 4.3.22)."""

        tc_pow = tc ** 1.25
        K = 1.0 + tc_pow / (tc_pow + 14.0)
        return K

    @staticmethod
    def calc_simple_rational(C, i, A):
        """Simple Rational Method (MDU Eq. 4.3.20): Q = C * i * A / 3.6"""

        return C * i * A / 3.6

    @staticmethod
    def calc_modified_rational(C, i, A, tc):
        """Modified Rational Method (MDU Eq. 4.3.22): Q = K * C * i * A / 3.6"""

        tc_pow = tc ** 1.25
        K = 1.0 + tc_pow / (tc_pow + 14.0)
        Q = K * C * i * A / 3.6
        return Q, K

    @staticmethod
    def calc_weighted_c(areas, coefficients):
        """Area-weighted runoff coefficient: C = Sum(Ci * Ai) / Sum(Ai)"""

        total_ca = sum(c * a for c, a in zip(coefficients, areas))
        total_a = sum(areas)
        if total_a == 0:
            return 0.0
        return total_ca / total_a

    # -------------------------------------------------------------------------
    # Hydrograph generation
    # -------------------------------------------------------------------------

    @staticmethod
    def _generate_hydrograph(Q, D, Tc, dt=1.0):
        """Generate the design hydrograph (triangular if D < Tc, trapezoidal if D >= Tc)."""

        hydrograph = []
        t_end = Tc + D

        if D < Tc:
            # Triangular hydrograph (short storm)
            Q_peak = Q * D / Tc
            t = 0.0
            while t <= t_end + dt / 2:
                if t <= D:
                    # Rising limb
                    q = Q_peak * (t / D) if D > 0 else 0.0
                else:
                    # Falling limb from Q_peak at t=D to 0 at t=Tc+D
                    fall_duration = Tc
                    if fall_duration > 0:
                        q = Q_peak * (1.0 - (t - D) / fall_duration)
                    else:
                        q = 0.0
                    q = max(q, 0.0)
                hydrograph.append((round(t, 2), round(q, 4)))
                t += dt
        else:
            # Trapezoidal hydrograph (long storm, D >= Tc)
            t = 0.0
            while t <= t_end + dt / 2:
                if t <= Tc:
                    # Rising limb
                    q = Q * (t / Tc) if Tc > 0 else Q
                elif t <= D:
                    # Plateau
                    q = Q
                else:
                    # Falling limb from Q at t=D to 0 at t=Tc+D
                    fall_duration = Tc
                    if fall_duration > 0:
                        q = Q * (1.0 - (t - D) / fall_duration)
                    else:
                        q = 0.0
                    q = max(q, 0.0)
                hydrograph.append((round(t, 2), round(q, 4)))
                t += dt

        return hydrograph

    # -------------------------------------------------------------------------
    # Results display
    # -------------------------------------------------------------------------

    def _fill_results(self, Q, K, C, i, A, Tc, D, use_modified):
        """Write a summary of the calculation to txt_results."""

        lines = []
        lines.append("=" * 50)
        lines.append("RESULTADOS - METODO RACIONAL")
        if use_modified:
            lines.append("(Metodo Racional Modificado - MDU Ec. 4.3.22)")
        else:
            lines.append("(Metodo Racional Simple - MDU Ec. 4.3.20)")
        lines.append("=" * 50)
        lines.append("")
        lines.append("DATOS DE ENTRADA:")
        lines.append(f"  Area (A)                  = {A:.2f} m2")
        lines.append(f"  Intensidad (i)            = {i:.2f} mm/hr")
        lines.append(f"  Coeficiente C             = {C:.4f}")
        lines.append(f"  Tiempo concentracion (Tc) = {Tc:.2f} min")
        lines.append(f"  Duracion lluvia (D)        = {D:.2f} min")
        lines.append("")

        if use_modified:
            lines.append("COEFICIENTE DE TEMEZ:")
            lines.append(f"  K = 1 + Tc^1.25 / (Tc^1.25 + 14)")
            lines.append(f"  K = {K:.4f}")
            lines.append("")
            lines.append("CAUDAL PICO:")
            lines.append(f"  Q = K * C * i * A / 3.6")
            lines.append(f"  Q = {K:.4f} * {C:.4f} * {i:.2f} * {A:.2f} / 3.6")
        else:
            lines.append("CAUDAL PICO:")
            lines.append(f"  Q = C * i * A / 3.6")
            lines.append(f"  Q = {C:.4f} * {i:.2f} * {A:.2f} / 3.6")

        lines.append(f"  Q = {Q:.4f} l/s")
        lines.append(f"  Q = {Q / 1000.0:.6f} m3/s")
        lines.append("")

        if D < Tc:
            Q_peak = Q * D / Tc
            lines.append("HIDROGRAMA: Triangular (D < Tc)")
            lines.append(f"  Caudal pico hidrograma = Q * D/Tc = {Q_peak:.4f} l/s")
            lines.append(f"  Tiempo al pico         = {D:.2f} min")
            lines.append(f"  Tiempo base            = {Tc + D:.2f} min")
        else:
            lines.append("HIDROGRAMA: Trapezoidal (D >= Tc)")
            lines.append(f"  Caudal plateau         = {Q:.4f} l/s")
            lines.append(f"  Inicio plateau         = {Tc:.2f} min")
            lines.append(f"  Fin plateau            = {D:.2f} min")
            lines.append(f"  Tiempo base            = {Tc + D:.2f} min")

        lines.append("")
        lines.append("=" * 50)

        self.dlg.txt_results.setPlainText("\n".join(lines))

    def _fill_hydrograph_table(self, hydrograph):
        """Populate tbl_hydrograph with time-flow data."""

        tbl = self.dlg.tbl_hydrograph
        tbl.setRowCount(0)

        for row_idx, (t, q) in enumerate(hydrograph):
            tbl.insertRow(row_idx)

            item_t = QTableWidgetItem(f"{t:.2f}")
            item_t.setFlags(item_t.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(row_idx, 0, item_t)

            item_q = QTableWidgetItem(f"{q:.4f}")
            item_q.setFlags(item_q.flags() & ~Qt.ItemFlag.ItemIsEditable)
            tbl.setItem(row_idx, 1, item_q)
