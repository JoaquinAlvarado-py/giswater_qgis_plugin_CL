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

from ....ui.ui_manager import MduRetentionWorksUi
from .....libs import tools_qgis, tools_qt
from ..... import global_vars
from ....utils import tools_gw


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GRAVITY = 9.81  # m/s2

# Pond type identifiers
POND_RECTANGULAR = "Estanque rectangular"
POND_TRAPEZOIDAL = "Estanque trapezoidal"
POND_UNDERGROUND = "Almacenamiento subterraneo"
POND_BARRELS = "Barriles/Cisternas"

POND_TYPES = [
    POND_RECTANGULAR,
    POND_TRAPEZOIDAL,
    POND_UNDERGROUND,
    POND_BARRELS,
]

# Standard rain barrel sizes [litres]
BARREL_SIZES = [200, 350]


# ---------------------------------------------------------------------------
# Pure computation helpers (no GUI dependency)
# ---------------------------------------------------------------------------

def orifice_flow(cd, area, head):
    """Orifice discharge: Q = Cd * A * sqrt(2 * g * h).

    Parameters
    ----------
    cd : float
        Discharge coefficient (dimensionless, typically ~0.62).
    area : float
        Orifice cross-section area [m2].
    head : float
        Head above orifice centre [m].

    Returns
    -------
    float
        Discharge [m3/s].
    """
    if head <= 0:
        return 0.0
    return cd * area * math.sqrt(2.0 * GRAVITY * head)


def weir_flow(cd, length, head):
    """Weir discharge: Q = Cd * L * h^1.5.

    Parameters
    ----------
    cd : float
        Weir discharge coefficient (typically ~1.84 for broad-crested weir).
    length : float
        Weir crest length [m].
    head : float
        Head above weir crest [m].

    Returns
    -------
    float
        Discharge [m3/s].
    """
    if head <= 0:
        return 0.0
    return cd * length * math.pow(head, 1.5)


def combined_outlet_flow(h, orifice_cd, orifice_area, weir_cd, weir_length,
                         weir_crest_elev):
    """Total outlet flow combining orifice and weir.

    Parameters
    ----------
    h : float
        Water surface elevation above datum (pond bottom) [m].
    orifice_cd : float
        Orifice discharge coefficient.
    orifice_area : float
        Orifice area [m2].
    weir_cd : float
        Weir discharge coefficient.
    weir_length : float
        Weir crest length [m].
    weir_crest_elev : float
        Elevation of weir crest above pond bottom [m].

    Returns
    -------
    float
        Combined outflow [m3/s].
    """
    # Orifice head is measured from water surface to orifice centre.
    # Assume orifice centre at the bottom (datum = 0).
    q_ori = orifice_flow(orifice_cd, orifice_area, h)

    head_weir = h - weir_crest_elev
    q_weir = weir_flow(weir_cd, weir_length, head_weir)

    return q_ori + q_weir


def volume_rectangular(area_base, h):
    """Volume of a prismatic (rectangular) pond.

    V(h) = A_base * h

    Parameters
    ----------
    area_base : float
        Bottom area [m2].
    h : float
        Water depth [m].

    Returns
    -------
    float
        Volume [m3].
    """
    return area_base * h


def volume_trapezoidal(area_base, side_slope, h):
    """Volume of a trapezoidal pond using the prismoidal formula.

    V(h) = h/3 * (A_base + A_top + sqrt(A_base * A_top))

    The top area is derived by expanding the base assuming a square base
    footprint growing by side_slope on each side:
        side_base = sqrt(A_base)
        side_top  = side_base + 2 * side_slope * h
        A_top     = side_top^2

    Parameters
    ----------
    area_base : float
        Bottom area [m2].
    side_slope : float
        Horizontal run per unit vertical rise (z:1, e.g. 3 means 3H:1V).
    h : float
        Water depth [m].

    Returns
    -------
    float
        Volume [m3].
    """
    side_base = math.sqrt(area_base)
    side_top = side_base + 2.0 * side_slope * h
    area_top = side_top * side_top
    return (h / 3.0) * (area_base + area_top + math.sqrt(area_base * area_top))


def surface_area_trapezoidal(area_base, side_slope, h):
    """Water surface area at depth *h* for a trapezoidal pond.

    Parameters
    ----------
    area_base : float
        Bottom area [m2].
    side_slope : float
        Horizontal run per unit vertical rise.
    h : float
        Water depth [m].

    Returns
    -------
    float
        Surface area [m2].
    """
    side_base = math.sqrt(area_base)
    side_top = side_base + 2.0 * side_slope * h
    return side_top * side_top


def build_volume_elevation_table(pond_type, area_base, total_depth,
                                 side_slope=0.0, n_steps=20):
    """Generate an elevation-volume-surface area table.

    Parameters
    ----------
    pond_type : str
        One of the POND_* constants.
    area_base : float
        Bottom area [m2].
    total_depth : float
        Maximum water depth to tabulate [m].
    side_slope : float
        Side slope for trapezoidal ponds (z:1).
    n_steps : int
        Number of depth increments.

    Returns
    -------
    list[dict]
        Each dict has keys: 'h' [m], 'volume' [m3], 'area' [m2].
    """
    table = []
    dh = total_depth / max(n_steps, 1)

    for i in range(n_steps + 1):
        h = i * dh
        if pond_type == POND_TRAPEZOIDAL:
            vol = volume_trapezoidal(area_base, side_slope, h)
            sa = surface_area_trapezoidal(area_base, side_slope, h)
        else:
            # Rectangular / underground -> prismatic
            vol = volume_rectangular(area_base, h)
            sa = area_base
        table.append({"h": h, "volume": vol, "area": sa})

    return table


def triangular_inflow(t, qp, tb):
    """Triangular unit hydrograph ordinate at time *t*.

    Parameters
    ----------
    t : float
        Current time [s].
    qp : float
        Peak inflow [m3/s].
    tb : float
        Base time of the hydrograph [s].

    Returns
    -------
    float
        Inflow [m3/s] at time *t*.
    """
    if t < 0 or t > tb:
        return 0.0
    tp = tb / 2.0  # time to peak assumed at mid-point
    if t <= tp:
        return qp * (t / tp) if tp > 0 else qp
    else:
        return qp * (1.0 - (t - tp) / (tb - tp)) if (tb - tp) > 0 else 0.0


def _storage_from_depth(pond_type, area_base, side_slope, h):
    """Return storage volume at depth *h* for the given pond geometry."""
    if pond_type == POND_TRAPEZOIDAL:
        return volume_trapezoidal(area_base, side_slope, h)
    return volume_rectangular(area_base, h)


def _depth_from_storage(pond_type, area_base, side_slope, target_vol):
    """Inverse lookup: find depth *h* corresponding to *target_vol*.

    Uses a simple bisection method.
    """
    if target_vol <= 0:
        return 0.0

    h_lo = 0.0
    h_hi = target_vol / max(area_base, 1.0) * 2.0

    for _ in range(20):
        if _storage_from_depth(pond_type, area_base, side_slope, h_hi) >= target_vol:
            break
        h_hi *= 2.0

    for _ in range(100):
        h_mid = 0.5 * (h_lo + h_hi)
        v_mid = _storage_from_depth(pond_type, area_base, side_slope, h_mid)
        if abs(v_mid - target_vol) < 1.0e-8:
            return h_mid
        if v_mid < target_vol:
            h_lo = h_mid
        else:
            h_hi = h_mid

    return 0.5 * (h_lo + h_hi)


def level_pool_routing(qp_in, tb, dt, pond_type, area_base, side_slope,
                       orifice_cd, orifice_area, weir_cd, weir_length,
                       weir_crest_elev, max_steps=500):
    """Simplified flood routing using the storage-indication (level pool) method.

    Algorithm (Modified Puls / Storage Indication):
        For each time step:
            (2*S2/dt + O2) = (2*S1/dt - O1) + I1 + I2

        where S = storage, O = outflow, I = inflow, dt = time step.

    A triangular inflow hydrograph is assumed.

    Parameters
    ----------
    qp_in : float
        Peak inflow [m3/s].
    tb : float
        Hydrograph base time [s].
    dt : float
        Routing time step [s].
    pond_type : str
        Pond geometry type.
    area_base : float
        Pond bottom area [m2].
    side_slope : float
        Side slope (trapezoidal only).
    orifice_cd : float
        Orifice discharge coefficient.
    orifice_area : float
        Orifice area [m2].
    weir_cd : float
        Weir discharge coefficient.
    weir_length : float
        Weir crest length [m].
    weir_crest_elev : float
        Weir crest elevation above pond bottom [m].
    max_steps : int
        Maximum number of routing time steps.

    Returns
    -------
    list[dict]
        Routing table.  Each entry: {'time_s', 'inflow', 'outflow',
        'storage', 'depth'}.
    """
    results = []

    S = 0.0
    O = 0.0
    h = 0.0

    for step in range(max_steps + 1):
        t = step * dt
        I_current = triangular_inflow(t, qp_in, tb)

        results.append({
            "time_s": t,
            "inflow": I_current,
            "outflow": O,
            "storage": S,
            "depth": h,
        })

        # Stop if well past the hydrograph end and outflow is negligible
        if t > tb and O < 1.0e-6 and I_current < 1.0e-6:
            break

        t_next = (step + 1) * dt
        I_next = triangular_inflow(t_next, qp_in, tb)

        # Storage indication: solve (2*S2/dt + O2) = (2*S1/dt - O1) + I1 + I2
        rhs = (2.0 * S / dt - O) + I_current + I_next

        # Iteratively find S2, O2 such that (2*S2/dt + O2) = rhs
        # Use bisection on depth h2
        h_lo = 0.0
        h_hi = h + (I_current + I_next) * dt / max(area_base, 1.0)
        h_hi = max(h_hi, 0.01)

        # Widen upper bound if necessary
        for _ in range(30):
            S_hi = _storage_from_depth(pond_type, area_base, side_slope, h_hi)
            O_hi = combined_outlet_flow(h_hi, orifice_cd, orifice_area,
                                        weir_cd, weir_length, weir_crest_elev)
            lhs_hi = 2.0 * S_hi / dt + O_hi
            if lhs_hi >= rhs:
                break
            h_hi *= 2.0

        h2 = 0.0
        for _ in range(100):
            h_mid = 0.5 * (h_lo + h_hi)
            S_mid = _storage_from_depth(pond_type, area_base, side_slope, h_mid)
            O_mid = combined_outlet_flow(h_mid, orifice_cd, orifice_area,
                                         weir_cd, weir_length, weir_crest_elev)
            lhs_mid = 2.0 * S_mid / dt + O_mid
            if abs(lhs_mid - rhs) < 1.0e-8:
                h2 = h_mid
                break
            if lhs_mid < rhs:
                h_lo = h_mid
            else:
                h_hi = h_mid
            h2 = 0.5 * (h_lo + h_hi)

        h2 = max(h2, 0.0)
        S2 = _storage_from_depth(pond_type, area_base, side_slope, h2)
        O2 = combined_outlet_flow(h2, orifice_cd, orifice_area,
                                  weir_cd, weir_length, weir_crest_elev)

        S = S2
        O = O2
        h = h2

    return results


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class RetentionWorks:
    """Retention / Storage Works Design calculator.

    Implements formulas from Chile's Manual de Drenaje Urbano (MDU),
    Chapter 6.4, including:
      - Two-level retention pond design (T=2yr lower + T=10-100yr upper).
      - Simplified flood routing (level-pool / storage-indication method).
      - Combined orifice + weir outlet sizing.
      - Volume-elevation curve generation.
      - Emergency spillway activation check.
      - Local storage elements (rain barrels / cisterns).
    """

    def __init__(self):
        self.dlg_ret = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def clicked_event(self):
        """Open the Retention Works dialog and wire all signals."""

        self.dlg_ret = MduRetentionWorksUi(self)
        dlg = self.dlg_ret
        tools_gw.load_settings(dlg)

        pond_rows = [[pt, pt] for pt in POND_TYPES]
        tools_qt.fill_combo_values(dlg.cmb_pond_type, pond_rows)

        tools_qt.set_widget_text(dlg, "txt_orifice_cd", "0.62")
        tools_qt.set_widget_text(dlg, "txt_weir_cd", "1.84")

        dlg.cmb_pond_type.currentIndexChanged.connect(
            partial(self._on_pond_type_changed)
        )
        dlg.btn_calculate.clicked.connect(
            partial(self._on_calculate)
        )
        dlg.btn_close.clicked.connect(
            partial(tools_gw.close_dialog, dlg)
        )
        dlg.rejected.connect(
            partial(tools_gw.close_dialog, dlg)
        )

        self._on_pond_type_changed()

        tools_gw.open_dialog(dlg, dlg_name='mdu_retention_works')

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_pond_type_changed(self):
        """Show/hide widgets depending on pond type."""

        dlg = self.dlg_ret
        selected = tools_qt.get_text(dlg, dlg.cmb_pond_type,
                                     return_string_null=False)
        if selected in (None, '', 'null', -1):
            return

        is_barrel = (selected == POND_BARRELS)

        for widget_name in ("txt_depth_lower", "txt_depth_upper",
                            "txt_orifice_d", "txt_orifice_cd",
                            "txt_weir_l", "txt_weir_cd"):
            widget = getattr(dlg, widget_name, None)
            if widget is not None:
                widget.setEnabled(not is_barrel)

    def _on_calculate(self):
        """Main calculation dispatcher."""

        try:
            dlg = self.dlg_ret
            selected = tools_qt.get_text(dlg, dlg.cmb_pond_type,
                                         return_string_null=False)
            if selected in (None, '', 'null', -1):
                tools_qgis.show_warning("Seleccione un tipo de estanque.")
                return

            if selected == POND_BARRELS:
                self._calculate_barrels_cisterns()
            else:
                self._calculate_pond_routing(selected)

        except Exception as e:
            tools_qgis.show_warning(f"Error en el calculo: {e}")

    # ------------------------------------------------------------------
    # Pond routing calculation
    # ------------------------------------------------------------------

    def _calculate_pond_routing(self, pond_type):
        """Run flood routing for a retention pond and populate tables."""

        dlg = self.dlg_ret

        qp_in = self._read_float("txt_qp_in", "Caudal peak de entrada (Qp)")
        if qp_in is None:
            return
        vol_in = self._read_float("txt_vol_in", "Volumen de entrada")
        if vol_in is None:
            return
        tb = self._read_float("txt_tb", "Tiempo base del hidrograma (tb)")
        if tb is None:
            return

        area_pond = self._read_float("txt_area_pond", "Area del estanque")
        if area_pond is None:
            return
        depth_lower = self._read_float("txt_depth_lower",
                                       "Profundidad nivel inferior")
        if depth_lower is None:
            return
        depth_upper = self._read_float("txt_depth_upper",
                                       "Profundidad nivel superior")
        if depth_upper is None:
            return

        total_depth = depth_lower + depth_upper

        orifice_d = self._read_float("txt_orifice_d",
                                     "Diametro orificio (m)")
        if orifice_d is None:
            return
        orifice_cd = self._read_float("txt_orifice_cd",
                                      "Coef. descarga orificio")
        if orifice_cd is None:
            return
        weir_l = self._read_float("txt_weir_l", "Largo del vertedero (m)")
        if weir_l is None:
            return
        weir_cd = self._read_float("txt_weir_cd",
                                   "Coef. descarga vertedero")
        if weir_cd is None:
            return

        orifice_area = math.pi * (orifice_d / 2.0) ** 2

        # Side slope for trapezoidal ponds (assume z=3 H:1V default)
        side_slope = 3.0 if pond_type == POND_TRAPEZOIDAL else 0.0

        # Weir crest is placed at the lower level boundary
        weir_crest_elev = depth_lower

        vol_lower = _storage_from_depth(pond_type, area_pond, side_slope,
                                        depth_lower)
        vol_upper = _storage_from_depth(pond_type, area_pond, side_slope,
                                        total_depth) - vol_lower
        vol_total = vol_lower + vol_upper

        # Use tb / 50 as a reasonable routing time step (capped)
        n_routing_steps = 100
        dt = max(tb / 50.0, 1.0)

        routing_results = level_pool_routing(
            qp_in=qp_in,
            tb=tb,
            dt=dt,
            pond_type=pond_type,
            area_base=area_pond,
            side_slope=side_slope,
            orifice_cd=orifice_cd,
            orifice_area=orifice_area,
            weir_cd=weir_cd,
            weir_length=weir_l,
            weir_crest_elev=weir_crest_elev,
            max_steps=n_routing_steps,
        )

        peak_outflow = 0.0
        max_depth = 0.0
        peak_outflow_time = 0.0
        for row in routing_results:
            if row["outflow"] > peak_outflow:
                peak_outflow = row["outflow"]
                peak_outflow_time = row["time_s"]
            if row["depth"] > max_depth:
                max_depth = row["depth"]

        emergency_active = max_depth > total_depth

        self._fill_routing_table(routing_results)

        vel_table = build_volume_elevation_table(
            pond_type, area_pond, total_depth, side_slope, n_steps=20
        )
        self._fill_vol_elev_table(vel_table)

        summary_lines = []
        summary_lines.append("=" * 58)
        summary_lines.append("  OBRAS DE RETENCION - MDU Cap. 6.4")
        summary_lines.append("=" * 58)
        summary_lines.append(f"  Tipo de estanque:         {pond_type}")
        summary_lines.append(f"  Area base:                {area_pond:.2f} m2")
        summary_lines.append(f"  Prof. nivel inferior:     {depth_lower:.2f} m  "
                             f"(T=2 anios)")
        summary_lines.append(f"  Prof. nivel superior:     {depth_upper:.2f} m  "
                             f"(T=10-100 anios)")
        summary_lines.append(f"  Profundidad total:        {total_depth:.2f} m")
        summary_lines.append("-" * 58)
        summary_lines.append(f"  Volumen nivel inferior:   {vol_lower:.2f} m3")
        summary_lines.append(f"  Volumen nivel superior:   {vol_upper:.2f} m3")
        summary_lines.append(f"  Volumen total estanque:   {vol_total:.2f} m3")
        summary_lines.append("-" * 58)
        summary_lines.append("  HIDROGRAMA DE ENTRADA")
        summary_lines.append(f"    Qp entrada:             {qp_in:.4f} m3/s")
        summary_lines.append(f"    Vol. entrada:           {vol_in:.2f} m3")
        summary_lines.append(f"    Tiempo base:            {tb:.0f} s")
        summary_lines.append("-" * 58)
        summary_lines.append("  ESTRUCTURA DE SALIDA")
        summary_lines.append(f"    Orificio d:             {orifice_d:.3f} m  "
                             f"(A={orifice_area:.4f} m2)")
        summary_lines.append(f"    Orificio Cd:            {orifice_cd:.2f}")
        summary_lines.append(f"    Vertedero L:            {weir_l:.2f} m")
        summary_lines.append(f"    Vertedero Cd:           {weir_cd:.2f}")
        summary_lines.append(f"    Cota cresta vertedero:  {weir_crest_elev:.2f} m")
        summary_lines.append("-" * 58)
        summary_lines.append("  RESULTADOS DEL TRANSITO")
        summary_lines.append(f"    Qp salida (peak):       {peak_outflow:.4f} m3/s")
        summary_lines.append(f"    Tiempo peak salida:     {peak_outflow_time:.0f} s")
        if qp_in > 0:
            attenuation = (1.0 - peak_outflow / qp_in) * 100.0
            summary_lines.append(f"    Atenuacion peak:        "
                                 f"{attenuation:.1f} %")
        summary_lines.append(f"    Prof. max alcanzada:    {max_depth:.3f} m")
        summary_lines.append("-" * 58)

        if emergency_active:
            summary_lines.append("  *** ALIVIADERO DE EMERGENCIA ACTIVADO ***")
            summary_lines.append(f"  La profundidad maxima ({max_depth:.3f} m) "
                                 f"excede la profundidad de diseno "
                                 f"({total_depth:.2f} m).")
            summary_lines.append("  Se requiere un aliviadero de emergencia "
                                 "o redimensionar el estanque.")
        else:
            summary_lines.append("  Estanque opera dentro de los niveles de "
                                 "diseno.")
            summary_lines.append("  No se activa aliviadero de emergencia.")

        summary_lines.append("=" * 58)

        dlg.txt_routing_summary.setText("\n".join(summary_lines))

    # ------------------------------------------------------------------
    # Barrels / Cisterns calculation
    # ------------------------------------------------------------------

    def _calculate_barrels_cisterns(self):
        """Calculate number of rain barrels or cisterns required."""

        dlg = self.dlg_ret

        vol_in = self._read_float("txt_vol_in", "Volumen de captura (Vc)")
        if vol_in is None:
            return
        area_pond = self._read_float("txt_area_pond",
                                     "Volumen unitario cisterna [L]")

        # For barrels, txt_area_pond is reused as the unit volume in litres.
        # If not provided, we use standard barrel sizes.
        summary_lines = []
        summary_lines.append("=" * 58)
        summary_lines.append("  BARRILES / CISTERNAS - MDU Cap. 6.4")
        summary_lines.append("=" * 58)
        summary_lines.append(f"  Volumen de captura (Vc):  {vol_in:.2f} m3")
        summary_lines.append(f"                            "
                             f"{vol_in * 1000.0:.0f} L")
        summary_lines.append("-" * 58)

        vc_litres = vol_in * 1000.0

        for size in BARREL_SIZES:
            n_units = math.ceil(vc_litres / size)
            summary_lines.append(f"  Barriles de {size} L:       "
                                 f"{n_units} unidades")

        if area_pond is not None and area_pond > 0:
            n_custom = math.ceil(vc_litres / area_pond)
            summary_lines.append(f"  Cisterna de {area_pond:.0f} L:      "
                                 f"{n_custom} unidades")
        else:
            summary_lines.append("  (Ingrese volumen unitario en 'Area/Vol' "
                                 "para cisternas personalizadas)")

        summary_lines.append("=" * 58)

        dlg.txt_routing_summary.setText("\n".join(summary_lines))

        tbl_routing = getattr(dlg, "tbl_routing", None)
        if tbl_routing is not None:
            tbl_routing.setRowCount(0)
        tbl_vel = getattr(dlg, "tbl_vol_elev", None)
        if tbl_vel is not None:
            tbl_vel.setRowCount(0)

    # ------------------------------------------------------------------
    # Table population helpers
    # ------------------------------------------------------------------

    def _fill_routing_table(self, routing_results):
        """Populate the routing results table widget."""

        dlg = self.dlg_ret
        tbl = getattr(dlg, "tbl_routing", None)
        if tbl is None:
            return

        headers = ["Tiempo [s]", "Qin [m3/s]", "Qout [m3/s]",
                    "Almac. [m3]", "Prof. [m]"]
        tbl.setColumnCount(len(headers))
        tbl.setHorizontalHeaderLabels(headers)
        tbl.setRowCount(len(routing_results))

        for row_idx, row in enumerate(routing_results):
            tbl.setItem(row_idx, 0,
                        QTableWidgetItem(f"{row['time_s']:.0f}"))
            tbl.setItem(row_idx, 1,
                        QTableWidgetItem(f"{row['inflow']:.4f}"))
            tbl.setItem(row_idx, 2,
                        QTableWidgetItem(f"{row['outflow']:.4f}"))
            tbl.setItem(row_idx, 3,
                        QTableWidgetItem(f"{row['storage']:.4f}"))
            tbl.setItem(row_idx, 4,
                        QTableWidgetItem(f"{row['depth']:.4f}"))

        header = tbl.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(QHeaderView.ResizeToContents)

    def _fill_vol_elev_table(self, vel_table):
        """Populate the volume-elevation table widget."""

        dlg = self.dlg_ret
        tbl = getattr(dlg, "tbl_vol_elev", None)
        if tbl is None:
            return

        headers = ["Elevacion [m]", "Volumen [m3]", "Area sup. [m2]"]
        tbl.setColumnCount(len(headers))
        tbl.setHorizontalHeaderLabels(headers)
        tbl.setRowCount(len(vel_table))

        for row_idx, row in enumerate(vel_table):
            tbl.setItem(row_idx, 0,
                        QTableWidgetItem(f"{row['h']:.3f}"))
            tbl.setItem(row_idx, 1,
                        QTableWidgetItem(f"{row['volume']:.4f}"))
            tbl.setItem(row_idx, 2,
                        QTableWidgetItem(f"{row['area']:.2f}"))

        header = tbl.horizontalHeader()
        if header is not None:
            header.setSectionResizeMode(QHeaderView.ResizeToContents)

    # ------------------------------------------------------------------
    # Input reading helpers
    # ------------------------------------------------------------------

    def _read_float(self, widget_name, label):
        """Read a float from a dialog widget.  Returns None on failure,
        after showing a warning to the user.

        Parameters
        ----------
        widget_name : str
            Object name of the widget.
        label : str
            Human-readable label for error messages.

        Returns
        -------
        float or None
        """
        dlg = self.dlg_ret
        widget = getattr(dlg, widget_name, None)
        if widget is None:
            tools_qgis.show_warning(f"Widget no encontrado: {widget_name}")
            return None

        raw = tools_qt.get_text(dlg, widget, return_string_null=False)
        if raw in (None, '', 'null'):
            tools_qgis.show_warning(f"Ingrese un valor para: {label}")
            return None
        try:
            return float(raw)
        except ValueError:
            tools_qgis.show_warning(f"'{label}' debe ser un valor numerico.")
            return None
