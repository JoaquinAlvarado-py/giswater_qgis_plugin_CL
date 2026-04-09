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

from ....ui.ui_manager import MduInletDesignUi
from .....libs import tools_qgis, tools_qt
from ..... import global_vars
from ....utils import tools_gw


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GRAVITY = 9.81  # m/s^2

# Chilean DOH/SERVIU standard inlet types (Tables 6.5.2 - 6.5.6)
# Each entry: (length_m, width_m, description)
INLET_TYPES = {
    "DOH Simple":   {"L": 0.90, "W": 0.45, "desc": "DOH Simple - 0.90 x 0.45 m"},
    "DOH Doble":    {"L": 1.80, "W": 0.45, "desc": "DOH Doble - 1.80 x 0.45 m"},
    "SERVIU S1":    {"L": 1.00, "W": 0.30, "desc": "SERVIU S1 - 1.00 x 0.30 m"},
    "Las Condes":   {"L": 0.60, "W": 0.30, "desc": "Las Condes - 0.60 x 0.30 m"},
    "DOH Especial": {"L": 1.20, "W": 0.60, "desc": "DOH Especial - 1.20 x 0.60 m"},
    "Personalizado": {"L": 0.00, "W": 0.00, "desc": "Personalizado (usuario)"},
}

# Gomez & Russo (2011) empirical coefficients E = a * y^b  (Eq. 6.5.4 - 6.5.6)
# Coefficients derived from experimental data for Chilean DOH/SERVIU inlets.
# y = flow depth at the inlet location (m).
GOMEZ_RUSSO_COEFFS = {
    "DOH Simple":   {"a": 3.24, "b": 0.58},
    "DOH Doble":    {"a": 4.76, "b": 0.63},
    "SERVIU S1":    {"a": 2.95, "b": 0.55},
    "Las Condes":   {"a": 2.10, "b": 0.50},
    "DOH Especial": {"a": 5.10, "b": 0.65},
}

# FHWA default coefficients
FHWA_CW_GRATE = 1.66   # Weir coefficient for horizontal (grate) inlets
FHWA_CO_GRATE = 0.67   # Orifice coefficient for horizontal (grate) inlets
FHWA_CW_CURB = 1.25    # Weir coefficient for lateral (curb) inlets
FHWA_CO_CURB = 0.67    # Orifice coefficient for lateral (curb) inlets

# Efficiency table (simplified) for "Tabla Eficiencia" method
# Maps (inlet_type, flow_range_label) -> efficiency
# Flow ranges: "Bajo" (< 0.020 m3/s), "Medio" (0.020 - 0.060), "Alto" (> 0.060)
EFFICIENCY_TABLE = {
    "DOH Simple":   {"Bajo": 0.95, "Medio": 0.70, "Alto": 0.45},
    "DOH Doble":    {"Bajo": 0.98, "Medio": 0.85, "Alto": 0.65},
    "SERVIU S1":    {"Bajo": 0.90, "Medio": 0.65, "Alto": 0.40},
    "Las Condes":   {"Bajo": 0.85, "Medio": 0.55, "Alto": 0.35},
    "DOH Especial": {"Bajo": 0.99, "Medio": 0.90, "Alto": 0.75},
}


class InletDesign:
    """Sumidero (Inlet) Design calculator.

    Implements formulas from Chile's Manual de Drenaje Urbano (MDU), Chapter 6.5.
    Covers gutter flow (Manning), FHWA horizontal/lateral inlet capacity,
    Gomez & Russo (2011) empirical efficiency, and inlet spacing optimisation.
    """

    def __init__(self):
        self.dlg_inlet = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def clicked_event(self):
        """Open the Inlet Design dialog and wire up all widgets."""

        self.dlg_inlet = MduInletDesignUi(self)
        dlg = self.dlg_inlet
        tools_gw.load_settings(dlg)

        inlet_type_items = [
            "DOH Simple", "DOH Doble", "SERVIU S1",
            "Las Condes", "DOH Especial", "Personalizado",
        ]
        dlg.cmb_inlet_type.clear()
        for item in inlet_type_items:
            dlg.cmb_inlet_type.addItem(item)

        method_items = [
            "FHWA Horizontal", "FHWA Lateral",
            "Gomez & Russo", "Tabla Eficiencia",
        ]
        dlg.cmb_inlet_method.clear()
        for item in method_items:
            dlg.cmb_inlet_method.addItem(item)

        self._set_default_values()

        self._on_inlet_type_changed()

        dlg.cmb_inlet_type.currentIndexChanged.connect(
            partial(self._on_inlet_type_changed)
        )
        dlg.btn_calculate.clicked.connect(partial(self._calculate))
        dlg.btn_close.clicked.connect(partial(self._close_dialog))
        dlg.rejected.connect(partial(tools_gw.close_dialog, dlg))

        self._init_spacing_table()

        tools_gw.open_dialog(dlg, dlg_name="mdu_inlet_design")

    # ------------------------------------------------------------------
    # Private helpers – UI
    # ------------------------------------------------------------------

    def _set_default_values(self):
        """Populate widgets with sensible defaults."""
        dlg = self.dlg_inlet
        tools_qt.set_widget_text(dlg, "txt_gutter_n", "0.016")
        tools_qt.set_widget_text(dlg, "txt_long_slope", "0.01")
        tools_qt.set_widget_text(dlg, "txt_cross_slope", "0.02")
        tools_qt.set_widget_text(dlg, "txt_gutter_width", "0.60")
        tools_qt.set_widget_text(dlg, "txt_flow_q", "")
        tools_qt.set_widget_text(dlg, "txt_perimeter", "")
        tools_qt.set_widget_text(dlg, "txt_clogging", "0")

    def _on_inlet_type_changed(self, index=None):
        """Auto-fill inlet length and width when the user selects a type."""
        dlg = self.dlg_inlet
        inlet_name = dlg.cmb_inlet_type.currentText()
        info = INLET_TYPES.get(inlet_name)
        if info is None:
            return

        if inlet_name == "Personalizado":
            tools_qt.set_widget_text(dlg, "txt_inlet_length", "")
            tools_qt.set_widget_text(dlg, "txt_inlet_width", "")
            dlg.txt_inlet_length.setReadOnly(False)
            dlg.txt_inlet_width.setReadOnly(False)
        else:
            tools_qt.set_widget_text(dlg, "txt_inlet_length", str(info["L"]))
            tools_qt.set_widget_text(dlg, "txt_inlet_width", str(info["W"]))
            dlg.txt_inlet_length.setReadOnly(True)
            dlg.txt_inlet_width.setReadOnly(True)

    def _init_spacing_table(self):
        """Prepare the tbl_spacing QTableWidget headers."""
        dlg = self.dlg_inlet
        tbl = dlg.tbl_spacing
        columns = [
            "Eficiencia objetivo (%)",
            "Q captado (m\u00b3/s)",
            "Q bypass (m\u00b3/s)",
            "Espaciamiento (m)",
        ]
        tbl.setColumnCount(len(columns))
        tbl.setHorizontalHeaderLabels(columns)
        header = tbl.horizontalHeader()
        for col in range(len(columns)):
            header.setSectionResizeMode(col, QHeaderView.Stretch)

    def _close_dialog(self):
        """Close the dialog and save settings."""
        dlg = self.dlg_inlet
        tools_gw.close_dialog(dlg)

    # ------------------------------------------------------------------
    # Private helpers – read widget values
    # ------------------------------------------------------------------

    def _get_float(self, widget_name, default=0.0):
        """Read a float from a dialog widget, returning *default* on failure."""
        text = tools_qt.get_text(self.dlg_inlet, widget_name, return_string_null=False)
        if text in (None, "", "null"):
            return default
        try:
            return float(text)
        except (ValueError, TypeError):
            return default

    # ------------------------------------------------------------------
    # Hydraulic calculations
    # ------------------------------------------------------------------

    @staticmethod
    def gutter_flow_manning(n, sl, st, t):
        """Gutter flow using Manning equation with cross-slope (Eq. 6.5.2).

        Q = (0.375 / n) * SL^0.5 * ST^(5/3) * T^(8/3)

        Parameters
        ----------
        n  : float – Manning roughness coefficient
        sl : float – Longitudinal slope (m/m)
        st : float – Cross (transverse) slope (m/m)
        t  : float – Spread width (m)

        Returns
        -------
        float – Gutter flow Q (m^3/s)
        """
        if n <= 0 or sl <= 0 or st <= 0 or t <= 0:
            return 0.0
        q = (0.375 / n) * math.pow(sl, 0.5) * math.pow(st, 5.0 / 3.0) * math.pow(t, 8.0 / 3.0)
        return q

    @staticmethod
    def flow_depth_from_spread(st, t):
        """Compute the flow depth at the curb from spread and cross slope.

        d = ST * T

        Parameters
        ----------
        st : float – Cross slope (m/m)
        t  : float – Spread width (m)

        Returns
        -------
        float – Flow depth at curb (m)
        """
        return st * t

    # --- FHWA Horizontal (grate) inlet (Eq. 6.5.7 - 6.5.8) ---

    @staticmethod
    def fhwa_horizontal_weir(perimeter, depth, cw=FHWA_CW_GRATE):
        """FHWA weir-mode capacity for a horizontal (grate) inlet.

        Q_weir = Cw * P * d^1.5

        Parameters
        ----------
        perimeter : float – Effective wetted perimeter of the grate (m)
        depth     : float – Flow depth over the grate (m)
        cw        : float – Weir coefficient (default 1.66)

        Returns
        -------
        float – Inlet capacity in weir mode (m^3/s)
        """
        if perimeter <= 0 or depth <= 0:
            return 0.0
        return cw * perimeter * math.pow(depth, 1.5)

    @staticmethod
    def fhwa_horizontal_orifice(area, depth, co=FHWA_CO_GRATE):
        """FHWA orifice-mode capacity for a horizontal (grate) inlet.

        Q_orifice = Co * Ag * sqrt(2 * g * d)

        Parameters
        ----------
        area  : float – Clear opening area of the grate (m^2)
        depth : float – Flow depth over the grate (m)
        co    : float – Orifice coefficient (default 0.67)

        Returns
        -------
        float – Inlet capacity in orifice mode (m^3/s)
        """
        if area <= 0 or depth <= 0:
            return 0.0
        return co * area * math.sqrt(2.0 * GRAVITY * depth)

    @staticmethod
    def fhwa_horizontal_capacity(length, width, depth, perimeter=None):
        """Select controlling mode (weir vs orifice) for a grate inlet.

        The transition occurs approximately when d equals the grate opening
        height, which is estimated as W (width) for a flat grate.

        Parameters
        ----------
        length    : float – Grate length (m)
        width     : float – Grate width (m)
        depth     : float – Flow depth at the inlet (m)
        perimeter : float | None – If None, computed as 2*L + W (one side
                    against the curb).

        Returns
        -------
        tuple(float, str) – (Q capacity m^3/s, mode label)
        """
        if perimeter is None or perimeter <= 0:
            perimeter = 2.0 * length + width  # one side against curb

        area = length * width
        q_weir = InletDesign.fhwa_horizontal_weir(perimeter, depth)
        q_orifice = InletDesign.fhwa_horizontal_orifice(area, depth)

        # Controlling capacity is the *lesser* of the two modes
        if depth <= 0:
            return 0.0, "N/A"
        if q_weir <= q_orifice:
            return q_weir, "Vertedero (weir)"
        else:
            return q_orifice, "Orificio (orifice)"

    # --- FHWA Lateral (curb) inlet (Eq. 6.5.9 - 6.5.10) ---

    @staticmethod
    def fhwa_lateral_weir(length, depth, cw=FHWA_CW_CURB):
        """FHWA weir-mode capacity for a lateral (curb-opening) inlet.

        Q_weir = Cw * L * d^1.5

        Parameters
        ----------
        length : float – Opening length along the curb (m)
        depth  : float – Flow depth at the curb (m)
        cw     : float – Weir coefficient (default 1.25)

        Returns
        -------
        float – Capacity in weir mode (m^3/s)
        """
        if length <= 0 or depth <= 0:
            return 0.0
        return cw * length * math.pow(depth, 1.5)

    @staticmethod
    def fhwa_lateral_orifice(length, height, depth_i, co=FHWA_CO_CURB):
        """FHWA orifice-mode capacity for a lateral (curb-opening) inlet.

        Q_orifice = Co * h * L * sqrt(2 * g * di)

        Parameters
        ----------
        length  : float – Opening length (m)
        height  : float – Opening height (m) – typically the curb cut height
        depth_i : float – Effective depth at the inlet (m)
        co      : float – Orifice coefficient (default 0.67)

        Returns
        -------
        float – Capacity in orifice mode (m^3/s)
        """
        if length <= 0 or height <= 0 or depth_i <= 0:
            return 0.0
        return co * height * length * math.sqrt(2.0 * GRAVITY * depth_i)

    @staticmethod
    def fhwa_lateral_capacity(length, width, depth):
        """Select controlling mode for a lateral (curb) inlet.

        Parameters
        ----------
        length : float – Opening length along the curb (m)
        width  : float – Opening height / width (m)
        depth  : float – Flow depth at curb face (m)

        Returns
        -------
        tuple(float, str) – (Q capacity m^3/s, mode label)
        """
        q_weir = InletDesign.fhwa_lateral_weir(length, depth)
        q_orifice = InletDesign.fhwa_lateral_orifice(length, width, depth)

        if depth <= 0:
            return 0.0, "N/A"
        if q_weir <= q_orifice:
            return q_weir, "Vertedero (weir)"
        else:
            return q_orifice, "Orificio (orifice)"

    # --- Gomez & Russo (2011) (Eq. 6.5.4 - 6.5.6) ---

    @staticmethod
    def gomez_russo_efficiency(inlet_type, depth):
        """Efficiency from Gomez & Russo (2011) empirical equation.

        E = a * y^b   (capped at 1.0)

        Parameters
        ----------
        inlet_type : str  – Key into GOMEZ_RUSSO_COEFFS
        depth      : float – Flow depth at the inlet (m)

        Returns
        -------
        float – Efficiency (0 to 1)
        """
        coeffs = GOMEZ_RUSSO_COEFFS.get(inlet_type)
        if coeffs is None or depth <= 0:
            return 0.0
        e = coeffs["a"] * math.pow(depth, coeffs["b"])
        return min(e, 1.0)

    # --- Tabla de eficiencia experimental ---

    @staticmethod
    def table_efficiency(inlet_type, q_total):
        """Look up efficiency from the experimental efficiency table.

        Parameters
        ----------
        inlet_type : str   – Inlet type key
        q_total    : float – Total gutter flow (m^3/s)

        Returns
        -------
        float – Efficiency (0 to 1)
        """
        table = EFFICIENCY_TABLE.get(inlet_type)
        if table is None:
            return 0.0
        if q_total < 0.020:
            return table["Bajo"]
        elif q_total <= 0.060:
            return table["Medio"]
        else:
            return table["Alto"]

    # --- Efficiency & bypass ---

    @staticmethod
    def efficiency(q_captured, q_total):
        """E = Qs / Q"""
        if q_total <= 0:
            return 0.0
        return min(q_captured / q_total, 1.0)

    @staticmethod
    def bypass_flow(q_total, eff):
        """Qbypass = Q * (1 - E)"""
        return q_total * (1.0 - eff)

    # --- Inlet spacing optimisation ---

    @staticmethod
    def inlet_spacing(q_total, q_captured, unit_runoff=None):
        """Estimate spacing between inlets along the gutter.

        If *unit_runoff* (m^3/s per metre of street) is provided the spacing
        is computed as the distance that generates enough runoff to equal the
        captured flow:
            S = Qs / q_unit

        If *unit_runoff* is not available a simplified geometric estimate is
        used:
            S = Qs / Q * 100  (linear proportion, reference block = 100 m)

        Parameters
        ----------
        q_total     : float – Total approach flow (m^3/s)
        q_captured  : float – Flow captured by one inlet (m^3/s)
        unit_runoff : float | None – Runoff per unit length of gutter (m^3/s/m)

        Returns
        -------
        float – Recommended centre-to-centre spacing (m)
        """
        if q_captured <= 0:
            return 0.0
        if unit_runoff is not None and unit_runoff > 0:
            return q_captured / unit_runoff
        # Simplified: proportional to 100 m reference block
        if q_total <= 0:
            return 0.0
        return (q_captured / q_total) * 100.0

    # ------------------------------------------------------------------
    # Main calculation routine
    # ------------------------------------------------------------------

    def _calculate(self):
        """Run all calculations and display results."""
        dlg = self.dlg_inlet

        n = self._get_float("txt_gutter_n", 0.016)
        sl = self._get_float("txt_long_slope", 0.01)
        st = self._get_float("txt_cross_slope", 0.02)
        t = self._get_float("txt_gutter_width", 0.60)
        q_input = self._get_float("txt_flow_q", 0.0)
        clogging = self._get_float("txt_clogging", 0.0)  # percentage 0-100

        inlet_type = dlg.cmb_inlet_type.currentText()
        method = dlg.cmb_inlet_method.currentText()

        inlet_l = self._get_float("txt_inlet_length", 0.0)
        inlet_w = self._get_float("txt_inlet_width", 0.0)
        perimeter_input = self._get_float("txt_perimeter", 0.0)

        errors = []
        if n <= 0:
            errors.append("Manning n debe ser > 0")
        if sl <= 0:
            errors.append("Pendiente longitudinal (SL) debe ser > 0")
        if st <= 0:
            errors.append("Pendiente transversal (ST) debe ser > 0")
        if t <= 0:
            errors.append("Ancho de cuneta (T) debe ser > 0")
        if inlet_l <= 0:
            errors.append("Largo del sumidero debe ser > 0")
        if inlet_w <= 0:
            errors.append("Ancho del sumidero debe ser > 0")

        if errors:
            dlg.txt_results.setPlainText(
                "ERRORES DE ENTRADA:\n" + "\n".join(f"  - {e}" for e in errors)
            )
            return

        q_manning = self.gutter_flow_manning(n, sl, st, t)
        q_total = q_input if q_input > 0 else q_manning

        depth = self.flow_depth_from_spread(st, t)

        clogging_factor = max(0.0, min(clogging, 100.0)) / 100.0
        effective_l = inlet_l * (1.0 - clogging_factor)
        effective_w = inlet_w * (1.0 - clogging_factor)
        effective_area = effective_l * effective_w

        q_captured = 0.0
        eff = 0.0
        mode_label = ""
        method_detail = ""

        if method == "FHWA Horizontal":
            perimeter = perimeter_input if perimeter_input > 0 else (2.0 * effective_l + effective_w)
            q_captured, mode_label = self.fhwa_horizontal_capacity(
                effective_l, effective_w, depth, perimeter
            )
            eff = self.efficiency(q_captured, q_total)
            method_detail = (
                f"  Modo controlante: {mode_label}\n"
                f"  Perimetro efectivo P = {perimeter:.3f} m\n"
                f"  Area efectiva Ag = {effective_area:.4f} m2\n"
                f"  Cw = {FHWA_CW_GRATE}, Co = {FHWA_CO_GRATE}"
            )

        elif method == "FHWA Lateral":
            q_captured, mode_label = self.fhwa_lateral_capacity(
                effective_l, effective_w, depth
            )
            eff = self.efficiency(q_captured, q_total)
            method_detail = (
                f"  Modo controlante: {mode_label}\n"
                f"  Altura abertura h = {effective_w:.3f} m\n"
                f"  Cw = {FHWA_CW_CURB}, Co = {FHWA_CO_CURB}"
            )

        elif method == "Gomez & Russo":
            if inlet_type == "Personalizado":
                dlg.txt_results.setPlainText(
                    "ERROR: El metodo Gomez & Russo no esta disponible para "
                    "tipo 'Personalizado'.\nSeleccione un tipo estandar DOH/SERVIU."
                )
                return
            eff = self.gomez_russo_efficiency(inlet_type, depth)
            q_captured = q_total * eff
            coeffs = GOMEZ_RUSSO_COEFFS.get(inlet_type, {})
            method_detail = (
                f"  E = a * y^b\n"
                f"  a = {coeffs.get('a', 'N/A')}, b = {coeffs.get('b', 'N/A')}\n"
                f"  y (profundidad) = {depth:.4f} m"
            )

        elif method == "Tabla Eficiencia":
            if inlet_type == "Personalizado":
                dlg.txt_results.setPlainText(
                    "ERROR: El metodo 'Tabla Eficiencia' no esta disponible para "
                    "tipo 'Personalizado'.\nSeleccione un tipo estandar DOH/SERVIU."
                )
                return
            eff = self.table_efficiency(inlet_type, q_total)
            eff = eff * (1.0 - clogging_factor)
            q_captured = q_total * eff
            flow_range = "Bajo" if q_total < 0.020 else ("Medio" if q_total <= 0.060 else "Alto")
            method_detail = (
                f"  Rango de caudal: {flow_range}\n"
                f"  Eficiencia tabla (sin colmatacion): "
                f"{self.table_efficiency(inlet_type, q_total):.2%}\n"
                f"  Factor colmatacion: {clogging_factor:.0%}"
            )

        q_bypass = self.bypass_flow(q_total, eff)

        separator = "-" * 55
        results = (
            f"{'=' * 55}\n"
            f"  DISENO DE SUMIDEROS - MDU Cap. 6.5\n"
            f"{'=' * 55}\n"
            f"\n"
            f"PARAMETROS DE CUNETA\n"
            f"{separator}\n"
            f"  Coef. Manning (n)       = {n}\n"
            f"  Pendiente longitudinal  = {sl:.4f} m/m\n"
            f"  Pendiente transversal   = {st:.4f} m/m\n"
            f"  Ancho de escurrimiento  = {t:.3f} m\n"
            f"  Profundidad en cuneta   = {depth:.4f} m\n"
            f"\n"
            f"CAUDAL EN CUNETA (Ec. 6.5.2 - Manning)\n"
            f"{separator}\n"
            f"  Q_Manning = (0.375/n) * SL^0.5 * ST^(5/3) * T^(8/3)\n"
            f"  Q_Manning = {q_manning:.6f} m3/s  ({q_manning * 1000:.3f} L/s)\n"
        )
        if q_input > 0:
            results += (
                f"  Q_usuario = {q_input:.6f} m3/s  (valor ingresado)\n"
                f"  ** Se usa Q_usuario para el diseno **\n"
            )
        results += (
            f"  Q_total   = {q_total:.6f} m3/s  ({q_total * 1000:.3f} L/s)\n"
            f"\n"
            f"SUMIDERO\n"
            f"{separator}\n"
            f"  Tipo       : {inlet_type}\n"
            f"  Largo (L)  : {inlet_l:.3f} m\n"
            f"  Ancho (W)  : {inlet_w:.3f} m\n"
            f"  Colmatacion: {clogging:.0f}%\n"
            f"  L efectivo : {effective_l:.3f} m\n"
            f"  W efectivo : {effective_w:.3f} m\n"
            f"\n"
            f"METODO: {method}\n"
            f"{separator}\n"
            f"{method_detail}\n"
            f"\n"
            f"RESULTADOS\n"
            f"{separator}\n"
            f"  Capacidad sumidero (Qs) = {q_captured:.6f} m3/s  ({q_captured * 1000:.3f} L/s)\n"
            f"  Eficiencia (E = Qs/Q)   = {eff:.2%}\n"
            f"  Caudal bypass           = {q_bypass:.6f} m3/s  ({q_bypass * 1000:.3f} L/s)\n"
            f"{'=' * 55}\n"
        )

        dlg.txt_results.setPlainText(results)

        self._fill_spacing_table(q_total, eff)

    # ------------------------------------------------------------------
    # Spacing table
    # ------------------------------------------------------------------

    def _fill_spacing_table(self, q_total, efficiency_base):
        """Populate tbl_spacing with spacing for several target efficiencies."""
        dlg = self.dlg_inlet
        tbl = dlg.tbl_spacing

        target_efficiencies = [1.00, 0.90, 0.80, 0.70, 0.60, 0.50]
        tbl.setRowCount(len(target_efficiencies))

        for row_idx, e_target in enumerate(target_efficiencies):
            if efficiency_base > 0:
                q_captured_target = q_total * e_target
                q_bypass_target = q_total - q_captured_target

                q_captured_base = q_total * efficiency_base
                if q_captured_base > 0:
                    n_inlets = q_captured_target / q_captured_base
                    if n_inlets > 0:
                        spacing = 100.0 / n_inlets
                    else:
                        spacing = 0.0
                else:
                    spacing = 0.0
            else:
                q_captured_target = 0.0
                q_bypass_target = q_total
                spacing = 0.0

            items = [
                f"{e_target:.0%}",
                f"{q_captured_target:.6f}",
                f"{q_bypass_target:.6f}",
                f"{spacing:.1f}",
            ]
            for col_idx, text in enumerate(items):
                item = QTableWidgetItem(text)
                tbl.setItem(row_idx, col_idx, item)
