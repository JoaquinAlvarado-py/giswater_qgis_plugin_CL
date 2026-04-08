"""
This file is part of Giswater
The program is free software: you can redistribute it and/or modify it under the terms of the GNU
General Public License as published by the Free Software Foundation, either version 3 of the License,
or (at your option) any later version.
"""
# -*- coding: utf-8 -*-
from functools import partial

from qgis.PyQt.QtWidgets import QTableWidgetItem, QHeaderView

from ...ui.ui_manager import MduNetworkHierarchyUi
from ....libs import tools_qgis, tools_qt
from .... import global_vars
from ...utils import tools_gw


# ---------------------------------------------------------------------------
# MDU Chapter 5 -- Network hierarchy constants
# ---------------------------------------------------------------------------

NETWORK_TYPES = [
    "Aguas lluvias separada",
    "Unitaria (combinada)",
    "Cauce natural",
]

HIERARCHY_LEVELS = {
    "Domiciliaria": {
        "area_min": 0.0,       # ha (inclusive)
        "area_max": 2.0,       # ha (exclusive)
        "return_period": "T = 2 - 5 anos",
        "allowed_methods": "Metodo Racional",
    },
    "Secundaria": {
        "area_min": 2.0,       # ha (inclusive)
        "area_max": 10.0,      # ha (exclusive)
        "return_period": "T = 2 - 10 anos",
        "allowed_methods_small": "Metodo Racional",
        "allowed_methods_large": "Metodo Racional, Hidrograma Unitario",
    },
    "Primaria": {
        "area_min": 10.0,      # ha (inclusive)
        "area_max": None,      # no upper limit
        "return_period": "T = 10 - 100 anos",
        "allowed_methods": "Hidrograma Unitario, HEC-HMS, SWMM",
    },
    "Natural": {
        "area_min": None,
        "area_max": None,
        "return_period": "T = 100+ anos",
        "allowed_methods": "Modelacion hidrologica/hidraulica completa requerida",
    },
}

# MDU Chapter 5 tables
DESIGN_STANDARDS = {
    "Domiciliaria": {
        "Diametro minimo tuberia [mm]":   300,
        "Velocidad maxima [m/s]":         3.0,
        "Velocidad minima [m/s]":         0.6,
        "Profundidad minima cobertura [m]": 1.0,
        "Pendiente minima [-]":           0.003,
        "Borde libre [m]":               0.10,
    },
    "Secundaria": {
        "Diametro minimo tuberia [mm]":   400,
        "Velocidad maxima [m/s]":         4.0,
        "Velocidad minima [m/s]":         0.6,
        "Profundidad minima cobertura [m]": 1.2,
        "Pendiente minima [-]":           0.002,
        "Borde libre [m]":               0.15,
    },
    "Primaria": {
        "Diametro minimo tuberia [mm]":   600,
        "Velocidad maxima [m/s]":         5.0,
        "Velocidad minima [m/s]":         0.9,
        "Profundidad minima cobertura [m]": 1.5,
        "Pendiente minima [-]":           0.001,
        "Borde libre [m]":               0.20,
    },
    "Natural": {
        "Diametro minimo tuberia [mm]":   None,
        "Velocidad maxima [m/s]":         6.0,
        "Velocidad minima [m/s]":         None,
        "Profundidad minima cobertura [m]": None,
        "Pendiente minima [-]":           None,
        "Borde libre [m]":               0.30,
    },
}

SECUNDARIA_METHOD_THRESHOLD = 5.0  # ha


class NetworkHierarchy:
    """Network Hierarchy Classification tool (MDU Chapter 5)."""

    def __init__(self):

        self.dlg_nh = None
        self.current_level = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def clicked_event(self):

        self.dlg_nh = MduNetworkHierarchyUi()
        dlg = self.dlg_nh
        tools_gw.load_settings(dlg)

        network_type_rows = [[nt, nt] for nt in NETWORK_TYPES]
        tools_qt.fill_combo_values(dlg.cmb_network_type, network_type_rows)

        tbl = dlg.tbl_standards
        tbl.setColumnCount(2)
        tbl.setHorizontalHeaderLabels(["Parametro", "Valor normativo"])
        header = tbl.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        tbl.setRowCount(0)

        dlg.btn_classify.clicked.connect(partial(self._classify))
        dlg.btn_validate.clicked.connect(partial(self._validate))
        dlg.btn_close.clicked.connect(partial(tools_gw.close_dialog, dlg))
        dlg.rejected.connect(partial(tools_gw.close_dialog, dlg))

        tools_gw.open_dialog(dlg, dlg_name='mdu_network_hierarchy')

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _classify(self):

        dlg = self.dlg_nh

        network_type = tools_qt.get_text(dlg, dlg.cmb_network_type, return_string_null=False)
        if network_type in (None, '', 'null', -1):
            tools_qgis.show_warning("Seleccione un tipo de red.")
            return

        if network_type == "Cauce natural":
            self._apply_level("Natural", None)
            return

        area_text = tools_qt.get_text(dlg, dlg.txt_area, return_string_null=False)
        if area_text in (None, '', 'null'):
            tools_qgis.show_warning("Ingrese el area aportante (ha).")
            return
        try:
            area = float(area_text)
        except ValueError:
            tools_qgis.show_warning("El area aportante debe ser un valor numerico.")
            return

        if area < 0:
            tools_qgis.show_warning("El area aportante no puede ser negativa.")
            return

        if area < 2.0:
            level = "Domiciliaria"
        elif area < 10.0:
            level = "Secundaria"
        else:
            level = "Primaria"

        self._apply_level(level, area)

    def _apply_level(self, level, area):

        dlg = self.dlg_nh
        self.current_level = level
        level_info = HIERARCHY_LEVELS[level]

        tools_qt.set_widget_text(dlg, "txt_hierarchy", level)
        tools_qt.set_widget_text(dlg, "txt_return_period", level_info["return_period"])

        if level == "Secundaria" and area is not None:
            if area < SECUNDARIA_METHOD_THRESHOLD:
                methods = level_info["allowed_methods_small"]
            else:
                methods = level_info["allowed_methods_large"]
        elif level == "Secundaria":
            methods = (f"{level_info['allowed_methods_small']} "
                       f"(< {SECUNDARIA_METHOD_THRESHOLD} ha) / "
                       f"{level_info['allowed_methods_large']} "
                       f"(>= {SECUNDARIA_METHOD_THRESHOLD} ha)")
        else:
            methods = level_info["allowed_methods"]

        tools_qt.set_widget_text(dlg, "txt_allowed_methods", methods)

        self._fill_standards_table(level)
        dlg.txt_val_results.clear()

    def _fill_standards_table(self, level):

        dlg = self.dlg_nh
        tbl = dlg.tbl_standards
        standards = DESIGN_STANDARDS[level]

        tbl.setRowCount(0)
        tbl.setRowCount(len(standards))

        for row, (param, value) in enumerate(standards.items()):
            tbl.setItem(row, 0, QTableWidgetItem(param))
            if value is not None:
                tbl.setItem(row, 1, QTableWidgetItem(str(value)))
            else:
                tbl.setItem(row, 1, QTableWidgetItem("N/A"))

        tbl.resizeColumnsToContents()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate(self):

        dlg = self.dlg_nh

        if self.current_level is None:
            tools_qgis.show_warning(
                "Primero clasifique la red (btn_classify) antes de validar."
            )
            return

        standards = DESIGN_STANDARDS[self.current_level]
        lines = []
        lines.append("=" * 60)
        lines.append(f"VALIDACION - Nivel: {self.current_level}")
        lines.append("Manual de Drenaje Urbano (MDU) - Capitulo 5")
        lines.append("=" * 60)
        lines.append("")

        pass_count = 0
        fail_count = 0
        skip_count = 0

        # --- Velocity ---
        velocity = self._get_float(dlg.txt_val_velocity)
        v_max = standards.get("Velocidad maxima [m/s]")
        v_min = standards.get("Velocidad minima [m/s]")

        if velocity is not None:
            if v_max is not None and velocity > v_max:
                lines.append(
                    f"[FAIL] Velocidad: {velocity} m/s > maximo permitido {v_max} m/s"
                )
                fail_count += 1
            elif v_min is not None and velocity < v_min:
                lines.append(
                    f"[FAIL] Velocidad: {velocity} m/s < minimo permitido {v_min} m/s"
                )
                fail_count += 1
            else:
                vel_range = ""
                if v_min is not None and v_max is not None:
                    vel_range = f" (rango: {v_min} - {v_max} m/s)"
                elif v_max is not None:
                    vel_range = f" (maximo: {v_max} m/s)"
                lines.append(f"[PASS] Velocidad: {velocity} m/s{vel_range}")
                pass_count += 1
        else:
            lines.append("[--]   Velocidad: no ingresada")
            skip_count += 1

        # --- Pipe diameter ---
        diameter = self._get_float(dlg.txt_val_diameter)
        d_min = standards.get("Diametro minimo tuberia [mm]")

        if diameter is not None:
            if d_min is not None:
                if diameter < d_min:
                    lines.append(
                        f"[FAIL] Diametro: {diameter} mm < minimo {d_min} mm"
                    )
                    fail_count += 1
                else:
                    lines.append(
                        f"[PASS] Diametro: {diameter} mm >= minimo {d_min} mm"
                    )
                    pass_count += 1
            else:
                lines.append(
                    f"[--]   Diametro: {diameter} mm (parametro N/A para nivel {self.current_level})"
                )
                skip_count += 1
        else:
            lines.append("[--]   Diametro: no ingresado")
            skip_count += 1

        # --- Cover depth ---
        cover = self._get_float(dlg.txt_val_cover)
        c_min = standards.get("Profundidad minima cobertura [m]")

        if cover is not None:
            if c_min is not None:
                if cover < c_min:
                    lines.append(
                        f"[FAIL] Cobertura: {cover} m < minimo {c_min} m"
                    )
                    fail_count += 1
                else:
                    lines.append(
                        f"[PASS] Cobertura: {cover} m >= minimo {c_min} m"
                    )
                    pass_count += 1
            else:
                lines.append(
                    f"[--]   Cobertura: {cover} m (parametro N/A para nivel {self.current_level})"
                )
                skip_count += 1
        else:
            lines.append("[--]   Cobertura: no ingresada")
            skip_count += 1

        # --- Slope ---
        slope = self._get_float(dlg.txt_val_slope)
        s_min = standards.get("Pendiente minima [-]")

        if slope is not None:
            if s_min is not None:
                if slope < s_min:
                    lines.append(
                        f"[FAIL] Pendiente: {slope} < minimo {s_min}"
                    )
                    fail_count += 1
                else:
                    lines.append(
                        f"[PASS] Pendiente: {slope} >= minimo {s_min}"
                    )
                    pass_count += 1
            else:
                lines.append(
                    f"[--]   Pendiente: {slope} (parametro N/A para nivel {self.current_level})"
                )
                skip_count += 1
        else:
            lines.append("[--]   Pendiente: no ingresada")
            skip_count += 1

        # --- Depth / Freeboard ---
        depth = self._get_float(dlg.txt_val_depth)
        freeboard = standards.get("Borde libre [m]")

        if depth is not None:
            if freeboard is not None:
                if depth < freeboard:
                    lines.append(
                        f"[FAIL] Borde libre: {depth} m < minimo requerido {freeboard} m"
                    )
                    fail_count += 1
                else:
                    lines.append(
                        f"[PASS] Borde libre: {depth} m >= minimo requerido {freeboard} m"
                    )
                    pass_count += 1
            else:
                lines.append(
                    f"[--]   Borde libre: {depth} m (parametro N/A para nivel {self.current_level})"
                )
                skip_count += 1
        else:
            lines.append("[--]   Borde libre: no ingresado")
            skip_count += 1

        # --- Summary ---
        lines.append("")
        lines.append("-" * 60)
        total_checked = pass_count + fail_count
        lines.append(
            f"Resultado: {pass_count} PASS, {fail_count} FAIL "
            f"(de {total_checked} parametros evaluados, {skip_count} omitidos)"
        )
        if fail_count == 0 and total_checked > 0:
            lines.append("ESTADO GENERAL: CUMPLE con la norma MDU Cap. 5")
        elif fail_count > 0:
            lines.append("ESTADO GENERAL: NO CUMPLE - revisar parametros marcados FAIL")
        else:
            lines.append("ESTADO GENERAL: Sin parametros evaluados")
        lines.append("=" * 60)

        dlg.txt_val_results.setText("\n".join(lines))

    # ------------------------------------------------------------------
    # Utility methods
    # ------------------------------------------------------------------

    @staticmethod
    def _get_float(widget):

        try:
            text = tools_qt.get_text(widget, return_string_null=False, add_id=False)
            if text in (None, "", "null", "NULL"):
                return None
            return float(text)
        except (ValueError, TypeError):
            return None
