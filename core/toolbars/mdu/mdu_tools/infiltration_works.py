"""
This file is part of Giswater
The program is free software: you can redistribute it and/or modify it under the terms of the GNU
General Public License as published by the Free Software Foundation, either version 3 of the License,
or (at your option) any later version.
"""
# -*- coding: utf-8 -*-
import math
from functools import partial

from ...ui.ui_manager import MduInfiltrationWorksUi
from ....libs import tools_qgis, tools_qt
from .... import global_vars
from ...utils import tools_gw


# ---------------------------------------------------------------------------
# Macro-zone precipitation base values (MDU Table 6.4.2)
# ---------------------------------------------------------------------------

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

# PB = precipitation base [mm] per macro-zone (Table 6.4.2)
PB_VALUES = {
    "Estepa de Altura": 8,
    "Desierto Arido": 0,
    "Semiarido": 8,
    "Mediterraneo Costero": 18,
    "Metropolitano": 10,
    "Mediterraneo Interior": 15,
    "Templado Lluvioso": 12,
    "Templado Frio": 5,
    "Continental Trasandino": 5,
}

# ---------------------------------------------------------------------------
# Work type definitions
# ---------------------------------------------------------------------------

WORK_TYPES = [
    "Techos Verdes",
    "Franjas Filtrantes",
    "Jardines de Lluvia",
    "Lagunas de Infiltracion",
    "Zanjas de Infiltracion",
    "Pozos de Infiltracion",
    "Pavimentos Porosos",
    "Pavimentos Celulares",
]

# Mapping of work type to its parameter labels (param1 .. param5).
# Each entry is a list of (label_text, default_value, unit_hint) tuples.
# Parameters beyond the list length will be hidden.
WORK_PARAMS = {
    "Techos Verdes": [
        ("Area techo verde Av [m2]", "", "m2"),
        ("Porosidad sustrato p [-]", "0.40", "-"),
        ("Carga estructural max [kPa]", "1.5", "kPa"),
    ],
    "Franjas Filtrantes": [
        ("Caudal Q [l/s]", "", "l/s"),
        ("Pendiente S [m/m]", "0.01", "m/m"),
        ("Coef. Manning n", "0.25", "-"),
    ],
    "Jardines de Lluvia": [
        ("Prof. encharcamiento [m]", "0.15", "m"),
        ("Prof. medio filtrante [m]", "0.90", "m"),
        ("Tiempo drenaje max [hr]", "48", "hr"),
    ],
    "Lagunas de Infiltracion": [
        ("Tasa infiltracion f [m/hr]", "0.01", "m/hr"),
        ("Area fondo A [m2]", "", "m2"),
        ("Tiempo vaciado t [hr]", "72", "hr"),
        ("Razon de vacios [-]", "0.40", "-"),
    ],
    "Zanjas de Infiltracion": [
        ("Largo L [m]", "", "m"),
        ("Ancho W [m]", "1.0", "m"),
        ("Profundidad D [m]", "1.5", "m"),
        ("Razon de vacios [-]", "0.35", "-"),
        ("Caudal rebalse Q [l/s]", "0", "l/s"),
    ],
    "Pozos de Infiltracion": [
        ("Conductividad K [m/hr]", "0.01", "m/hr"),
        ("Diametro pozo [m]", "1.0", "m"),
        ("Profundidad pozo [m]", "3.0", "m"),
    ],
    "Pavimentos Porosos": [
        ("Area pavimento [m2]", "", "m2"),
        ("Razon de vacios [-]", "0.30", "-"),
        ("Carga trafico [kN]", "40", "kN"),
    ],
    "Pavimentos Celulares": [
        ("Area pavimento [m2]", "", "m2"),
        ("Capacidad carga [kPa]", "200", "kPa"),
        ("Porcentaje infiltracion [%]", "40", "%"),
        ("Razon de vacios [-]", "0.30", "-"),
    ],
}


class InfiltrationWorks:
    """Infiltration Works Dimensioning calculator.

    Implements formulas from Chile's Manual de Drenaje Urbano (MDU),
    Chapters 6.3-6.4, covering eight types of sustainable urban drainage
    infiltration works.
    """

    def __init__(self):

        self.dlg_inf = None

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def clicked_event(self):
        """Open the Infiltration Works dialog and wire all signals."""

        self.dlg_inf = MduInfiltrationWorksUi()
        dlg = self.dlg_inf
        tools_gw.load_settings(dlg)

        macrozone_rows = [[mz, mz] for mz in MACROZONES]
        tools_qt.fill_combo_values(dlg.cmb_macrozone, macrozone_rows)

        work_type_rows = [[wt, wt] for wt in WORK_TYPES]
        tools_qt.fill_combo_values(dlg.cmb_work_type, work_type_rows)

        dlg.cmb_macrozone.currentIndexChanged.connect(
            partial(self._on_macrozone_changed)
        )
        dlg.cmb_work_type.currentIndexChanged.connect(
            partial(self._on_work_type_changed)
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

        self._on_macrozone_changed()
        self._on_work_type_changed()

        tools_gw.open_dialog(dlg, dlg_name='mdu_infiltration_works')

    # ------------------------------------------------------------------
    # Signal handlers
    # ------------------------------------------------------------------

    def _on_macrozone_changed(self):
        """Auto-fill txt_pb when a macro-zone is selected."""

        dlg = self.dlg_inf
        selected_mz = tools_qt.get_text(dlg, dlg.cmb_macrozone, return_string_null=False)
        if selected_mz in (None, '', 'null', -1):
            tools_qt.set_widget_text(dlg, "txt_pb", "")
            return

        pb = PB_VALUES.get(selected_mz, None)
        if pb is not None:
            tools_qt.set_widget_text(dlg, "txt_pb", str(pb))
        else:
            tools_qt.set_widget_text(dlg, "txt_pb", "")

    def _on_work_type_changed(self):
        """Dynamically update parameter labels and show/hide fields based on
        the selected work type."""

        dlg = self.dlg_inf
        selected_wt = tools_qt.get_text(dlg, dlg.cmb_work_type, return_string_null=False)
        if selected_wt in (None, '', 'null', -1):
            return

        params = WORK_PARAMS.get(selected_wt, [])

        for i in range(1, 6):
            lbl = getattr(dlg, f"lbl_param{i}", None)
            txt = getattr(dlg, f"txt_param{i}", None)
            if lbl is None or txt is None:
                continue

            if i <= len(params):
                label_text, default_val, _unit = params[i - 1]
                lbl.setText(label_text)
                lbl.setVisible(True)
                txt.setVisible(True)
                tools_qt.set_widget_text(dlg, f"txt_param{i}", default_val)
            else:
                lbl.setVisible(False)
                txt.setVisible(False)
                tools_qt.set_widget_text(dlg, f"txt_param{i}", "")

    def _on_calculate(self):
        """Calculate capture volume and work-specific dimensioning."""

        try:
            vc = self._calculate_capture_volume()
            if vc is None:
                return
            self._calculate_work_dimensioning(vc)
        except Exception as e:
            tools_qgis.show_warning(f"Calculation error: {e}")

    # ------------------------------------------------------------------
    # Capture volume calculation (MDU Eq.)
    # ------------------------------------------------------------------

    @staticmethod
    def capture_volume(pb, at):
        """Calculate capture volume.

        Vc = PB * AT / 1000  [m3]

        Parameters
        ----------
        pb : float
            Precipitation base [mm].
        at : float
            Tributary area [m2].

        Returns
        -------
        float
            Capture volume Vc [m3].
        """

        return pb * at / 1000.0

    def _calculate_capture_volume(self):
        """Read PB and AT from dialog, compute Vc, and display it."""

        dlg = self.dlg_inf

        pb_text = tools_qt.get_text(dlg, dlg.txt_pb, return_string_null=False)
        if pb_text in (None, '', 'null'):
            tools_qgis.show_warning("Seleccione una macro-zona para obtener la precipitacion base (PB).")
            return None
        try:
            pb = float(pb_text)
        except ValueError:
            tools_qgis.show_warning("La precipitacion base (PB) debe ser un valor numerico.")
            return None

        at_text = tools_qt.get_text(dlg, dlg.txt_area_t, return_string_null=False)
        if at_text in (None, '', 'null'):
            tools_qgis.show_warning("Ingrese el area tributaria (AT) en m2.")
            return None
        try:
            at = float(at_text)
        except ValueError:
            tools_qgis.show_warning("El area tributaria (AT) debe ser un valor numerico.")
            return None

        if at <= 0:
            tools_qgis.show_warning("El area tributaria debe ser mayor que cero.")
            return None

        vc = self.capture_volume(pb, at)
        tools_qt.set_widget_text(dlg, "txt_vc", f"{vc:.4f}")
        return vc

    # ------------------------------------------------------------------
    # Work-specific dimensioning
    # ------------------------------------------------------------------

    def _calculate_work_dimensioning(self, vc):
        """Dispatch to the correct dimensioning method based on the selected
        work type and display results in txt_results."""

        dlg = self.dlg_inf
        selected_wt = tools_qt.get_text(dlg, dlg.cmb_work_type, return_string_null=False)
        if selected_wt in (None, '', 'null', -1):
            return

        params = self._read_params(selected_wt)
        if params is None:
            return

        dispatch = {
            "Techos Verdes": self._dim_green_roof,
            "Franjas Filtrantes": self._dim_filter_strip,
            "Jardines de Lluvia": self._dim_rain_garden,
            "Lagunas de Infiltracion": self._dim_infiltration_pond,
            "Zanjas de Infiltracion": self._dim_infiltration_trench,
            "Pozos de Infiltracion": self._dim_infiltration_well,
            "Pavimentos Porosos": self._dim_porous_pavement,
            "Pavimentos Celulares": self._dim_cellular_pavement,
        }

        func = dispatch.get(selected_wt)
        if func is None:
            tools_qgis.show_warning(f"Tipo de obra no reconocido: {selected_wt}")
            return

        result_text = func(vc, params)
        dlg.txt_results.setText(result_text)

    def _read_params(self, work_type):
        """Read the visible parameter text fields and return them as a list of
        floats.  Returns None on validation failure."""

        dlg = self.dlg_inf
        param_defs = WORK_PARAMS.get(work_type, [])
        values = []

        for i in range(1, len(param_defs) + 1):
            txt = getattr(dlg, f"txt_param{i}", None)
            if txt is None:
                values.append(0.0)
                continue

            raw = tools_qt.get_text(dlg, txt, return_string_null=False)
            if raw in (None, '', 'null'):
                label_text = param_defs[i - 1][0]
                tools_qgis.show_warning(f"Ingrese un valor para: {label_text}")
                return None
            try:
                values.append(float(raw))
            except ValueError:
                label_text = param_defs[i - 1][0]
                tools_qgis.show_warning(f"El valor de '{label_text}' debe ser numerico.")
                return None

        return values

    # ------------------------------------------------------------------
    # a) Green Roofs - Techos Verdes (Eq. 6.3.1)
    # ------------------------------------------------------------------

    @staticmethod
    def _dim_green_roof(vc, params):
        """Dimensioning for green roofs (Techos Verdes).

        Substrate thickness: e = Vc / (Av * p)  [m]

        Parameters
        ----------
        vc : float
            Capture volume [m3].
        params : list
            [Av (m2), p (-), structural_load_limit (kPa)]
        """

        av = params[0]   # green roof area [m2]
        p = params[1]    # porosity of substrate [-]
        load_limit = params[2]  # structural load limit [kPa]

        lines = []
        lines.append("=" * 55)
        lines.append("  TECHOS VERDES (Green Roofs) - MDU Eq. 6.3.1")
        lines.append("=" * 55)
        lines.append(f"  Volumen de captura (Vc): {vc:.4f} m3")
        lines.append(f"  Area techo verde (Av):   {av:.2f} m2")
        lines.append(f"  Porosidad sustrato (p):  {p:.2f}")
        lines.append(f"  Carga estructural max:   {load_limit:.2f} kPa")
        lines.append("-" * 55)

        if av <= 0:
            lines.append("  ERROR: El area del techo verde debe ser > 0.")
            return "\n".join(lines)

        if p <= 0 or p > 1:
            lines.append("  ERROR: La porosidad debe estar entre 0 y 1.")
            return "\n".join(lines)

        e = vc / (av * p)

        lines.append(f"  Espesor sustrato requerido (e): {e:.4f} m")
        lines.append(f"                                  {e * 100:.2f} cm")

        if p < 0.3 or p > 0.5:
            lines.append("  AVISO: Porosidad fuera del rango tipico (0.3 - 0.5).")

        # Estimate weight (saturated substrate approx. 1200-1600 kg/m3)
        substrate_density = 1400  # kg/m3 (saturated, approximate)
        weight_per_m2 = substrate_density * e * 9.81 / 1000  # kPa
        lines.append(f"  Carga estimada (sustrato saturado): {weight_per_m2:.2f} kPa")

        if weight_per_m2 > load_limit:
            lines.append("  ADVERTENCIA: La carga estimada SUPERA el limite estructural.")
        else:
            lines.append("  OK: La carga estimada esta dentro del limite estructural.")

        lines.append("-" * 55)
        lines.append(f"  Formula: e = Vc / (Av * p) = {vc:.4f} / ({av:.2f} * {p:.2f})")
        lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # b) Filter Strips - Franjas Filtrantes (Eq. 6.3.3-6.3.4)
    # ------------------------------------------------------------------

    @staticmethod
    def _dim_filter_strip(vc, params):
        """Dimensioning for filter strips (Franjas Filtrantes).

        Width:  Bf = Q / 4.5  [m]  (Q in l/s)
        Min length: 3 m
        Flow depth via Manning: y = (n*Q / (Bf * S^0.5))^0.6

        Parameters
        ----------
        vc : float
            Capture volume [m3].
        params : list
            [Q (l/s), S (m/m), n (-)]
        """

        q = params[0]   # flow rate [l/s]
        s = params[1]   # longitudinal slope [m/m]
        n = params[2]   # Manning roughness coefficient

        lines = []
        lines.append("=" * 55)
        lines.append("  FRANJAS FILTRANTES (Filter Strips) - MDU Eq. 6.3.3-6.3.4")
        lines.append("=" * 55)
        lines.append(f"  Volumen de captura (Vc): {vc:.4f} m3")
        lines.append(f"  Caudal (Q):              {q:.2f} l/s")
        lines.append(f"  Pendiente (S):           {s:.4f} m/m")
        lines.append(f"  Coef. Manning (n):       {n:.3f}")
        lines.append("-" * 55)

        if q <= 0:
            lines.append("  ERROR: El caudal debe ser > 0.")
            return "\n".join(lines)

        if s <= 0:
            lines.append("  ERROR: La pendiente debe ser > 0.")
            return "\n".join(lines)

        # Width (Eq. 6.3.3)
        bf = q / 4.5

        lines.append(f"  Ancho franja (Bf):          {bf:.3f} m")
        lines.append(f"  Formula: Bf = Q / 4.5 = {q:.2f} / 4.5")

        min_length = 3.0
        lines.append(f"  Largo minimo recomendado:   {min_length:.1f} m")

        # Flow depth via Manning (Eq. 6.3.4)
        # Assuming wide shallow flow (Rh ~ y):
        # Q_m3s = (1/n) * Bf * y * y^(2/3) * S^(1/2)
        # For a wide rectangular channel approximation:
        # y = (n * Q_m3s / (Bf * S^0.5))^0.6
        q_m3s = q / 1000.0  # convert l/s to m3/s
        if bf > 0 and s > 0:
            y = math.pow(n * q_m3s / (bf * math.pow(s, 0.5)), 0.6)
            lines.append(f"  Profundidad flujo (y):      {y:.4f} m")
            lines.append(f"                              {y * 100:.2f} cm")
            lines.append(f"  Formula: y = (n*Q / (Bf * S^0.5))^0.6")
        else:
            lines.append("  No se puede calcular la profundidad de flujo.")

        if bf > 0:
            filter_area = vc / (y if y > 0 else 0.01)
            filter_length = filter_area / bf
            lines.append(f"  Largo estimado para capturar Vc: {filter_length:.2f} m")
            if filter_length < min_length:
                lines.append(f"  -> Se adopta largo minimo: {min_length:.1f} m")

        lines.append("-" * 55)
        lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # c) Rain Gardens - Jardines de Lluvia / Bioretention
    # ------------------------------------------------------------------

    @staticmethod
    def _dim_rain_garden(vc, params):
        """Dimensioning for rain gardens (Jardines de Lluvia / Bioretention).

        Ponding area = Vc / ponding_depth
        Soil media depth: typically 0.6-1.2 m
        Drain time < 48 hours

        Parameters
        ----------
        vc : float
            Capture volume [m3].
        params : list
            [ponding_depth (m), soil_media_depth (m), max_drain_time (hr)]
        """

        ponding_depth = params[0]   # ponding depth [m]
        soil_depth = params[1]      # soil media depth [m]
        max_drain = params[2]       # max drain time [hr]

        lines = []
        lines.append("=" * 55)
        lines.append("  JARDINES DE LLUVIA (Rain Gardens / Bioretention)")
        lines.append("=" * 55)
        lines.append(f"  Volumen de captura (Vc):        {vc:.4f} m3")
        lines.append(f"  Prof. encharcamiento:           {ponding_depth:.3f} m")
        lines.append(f"  Prof. medio filtrante:          {soil_depth:.2f} m")
        lines.append(f"  Tiempo drenaje maximo:          {max_drain:.1f} hr")
        lines.append("-" * 55)

        if ponding_depth <= 0:
            lines.append("  ERROR: La profundidad de encharcamiento debe ser > 0.")
            return "\n".join(lines)

        ponding_area = vc / ponding_depth

        lines.append(f"  Area encharcamiento requerida:  {ponding_area:.2f} m2")
        lines.append(f"  Formula: A = Vc / d = {vc:.4f} / {ponding_depth:.3f}")

        if soil_depth < 0.6 or soil_depth > 1.2:
            lines.append("  AVISO: Prof. medio filtrante fuera del rango tipico (0.6-1.2 m).")
        else:
            lines.append("  OK: Prof. medio filtrante dentro del rango tipico.")

        if max_drain > 0:
            req_infiltration = ponding_depth / max_drain  # m/hr
            lines.append(f"  Tasa infiltracion requerida:    {req_infiltration:.6f} m/hr")
            lines.append(f"                                  {req_infiltration * 1000:.4f} mm/hr")
            lines.append(f"  (para vaciar en {max_drain:.0f} horas)")

        if max_drain > 48:
            lines.append("  ADVERTENCIA: Tiempo de drenaje supera 48 horas.")
        else:
            lines.append("  OK: Tiempo de drenaje dentro del limite recomendado (<= 48 hr).")

        side = math.sqrt(ponding_area)
        lines.append(f"  Lado equivalente (cuadrado):    {side:.2f} m")

        lines.append("-" * 55)
        lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # d) Infiltration Ponds - Lagunas de Infiltracion
    # ------------------------------------------------------------------

    @staticmethod
    def _dim_infiltration_pond(vc, params):
        """Dimensioning for infiltration ponds (Lagunas de Infiltracion).

        Volume from percolation: V = f * A * t_drain
        Include void ratio for storage media.

        Parameters
        ----------
        vc : float
            Capture volume [m3].
        params : list
            [f (m/hr), A (m2), t_drain (hr), void_ratio (-)]
        """

        f = params[0]           # infiltration rate [m/hr]
        a_bottom = params[1]    # bottom area [m2]
        t_drain = params[2]     # drawdown time [hr]
        void_ratio = params[3]  # void ratio for storage media [-]

        lines = []
        lines.append("=" * 55)
        lines.append("  LAGUNAS DE INFILTRACION (Infiltration Ponds)")
        lines.append("=" * 55)
        lines.append(f"  Volumen de captura (Vc):     {vc:.4f} m3")
        lines.append(f"  Tasa infiltracion (f):       {f:.4f} m/hr")
        lines.append(f"  Area fondo (A):              {a_bottom:.2f} m2")
        lines.append(f"  Tiempo vaciado (t):          {t_drain:.1f} hr")
        lines.append(f"  Razon de vacios:             {void_ratio:.2f}")
        lines.append("-" * 55)

        if a_bottom <= 0:
            lines.append("  ERROR: El area del fondo debe ser > 0.")
            return "\n".join(lines)

        if f < 0:
            lines.append("  ERROR: La tasa de infiltracion no puede ser negativa.")
            return "\n".join(lines)

        v_infiltrated = f * a_bottom * t_drain

        lines.append(f"  Volumen infiltrado (V_inf):  {v_infiltrated:.4f} m3")
        lines.append(f"  Formula: V_inf = f * A * t = {f:.4f} * {a_bottom:.2f} * {t_drain:.1f}")

        # Required storage depth (accounting for void ratio in storage media)
        # The pond must store Vc minus what infiltrates during filling
        # Simplified: storage depth d = Vc / (A * void_ratio) if using storage media
        # or d = Vc / A for open pond
        if void_ratio > 0 and void_ratio <= 1:
            storage_depth = vc / (a_bottom * void_ratio)
            lines.append(f"  Prof. almacenamiento (con vacios): {storage_depth:.4f} m")
        else:
            storage_depth = vc / a_bottom
            lines.append(f"  Prof. almacenamiento (sin vacios): {storage_depth:.4f} m")

        # Open pond depth (no media)
        open_depth = vc / a_bottom
        lines.append(f"  Prof. laguna abierta:        {open_depth:.4f} m")

        if v_infiltrated >= vc:
            lines.append("  OK: La capacidad de infiltracion es suficiente para drenar Vc.")
        else:
            deficit = vc - v_infiltrated
            lines.append(f"  AVISO: Deficit de infiltracion: {deficit:.4f} m3")
            lines.append("  Considere aumentar area, tasa de infiltracion o tiempo de vaciado.")

        if f > 0 and t_drain > 0:
            a_required = vc / (f * t_drain)
            lines.append(f"  Area requerida (para drenar Vc en t): {a_required:.2f} m2")

        lines.append("-" * 55)
        lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # e) Infiltration Trenches - Zanjas de Infiltracion
    # ------------------------------------------------------------------

    @staticmethod
    def _dim_infiltration_trench(vc, params):
        """Dimensioning for infiltration trenches (Zanjas de Infiltracion).

        Volume: V = L * W * D * void_ratio
        Overflow design for excess flow.

        Parameters
        ----------
        vc : float
            Capture volume [m3].
        params : list
            [L (m), W (m), D (m), void_ratio (-), Q_overflow (l/s)]
        """

        length = params[0]      # trench length [m]
        width = params[1]       # trench width [m]
        depth = params[2]       # trench depth [m]
        void_ratio = params[3]  # void ratio [-]
        q_overflow = params[4]  # overflow discharge [l/s]

        lines = []
        lines.append("=" * 55)
        lines.append("  ZANJAS DE INFILTRACION (Infiltration Trenches)")
        lines.append("=" * 55)
        lines.append(f"  Volumen de captura (Vc):    {vc:.4f} m3")
        lines.append(f"  Largo (L):                  {length:.2f} m")
        lines.append(f"  Ancho (W):                  {width:.2f} m")
        lines.append(f"  Profundidad (D):            {depth:.2f} m")
        lines.append(f"  Razon de vacios:            {void_ratio:.2f}")
        lines.append(f"  Caudal rebalse (Q):         {q_overflow:.2f} l/s")
        lines.append("-" * 55)

        if void_ratio < 0.35 or void_ratio > 0.40:
            lines.append("  AVISO: Razon de vacios fuera del rango tipico (0.35-0.40).")

        v_storage = length * width * depth * void_ratio

        lines.append(f"  Volumen almacenamiento (V): {v_storage:.4f} m3")
        lines.append(f"  Formula: V = L * W * D * n_v")
        lines.append(f"         = {length:.2f} * {width:.2f} * {depth:.2f} * {void_ratio:.2f}")

        if v_storage >= vc:
            lines.append(f"  OK: Volumen de zanja ({v_storage:.4f} m3) >= Vc ({vc:.4f} m3)")
            excess = v_storage - vc
            lines.append(f"  Exceso de volumen:          {excess:.4f} m3")
        else:
            deficit = vc - v_storage
            lines.append(f"  DEFICIT: Falta {deficit:.4f} m3 de almacenamiento.")

            if width > 0 and depth > 0 and void_ratio > 0:
                l_required = vc / (width * depth * void_ratio)
                lines.append(f"  Largo requerido (L):        {l_required:.2f} m")

        # Gross volume (without voids)
        v_gross = length * width * depth
        lines.append(f"  Volumen bruto (L*W*D):      {v_gross:.4f} m3")

        if q_overflow > 0:
            lines.append("-" * 55)
            lines.append("  DISENO DE REBALSE:")
            # Simple weir overflow: Q = C * L_weir * h^1.5
            # Assume broad-crested weir coefficient C = 1.7
            c_weir = 1.7
            q_overflow_m3s = q_overflow / 1000.0
            # Assume overflow weir length = trench width
            l_weir = width
            if l_weir > 0:
                h_overflow = math.pow(q_overflow_m3s / (c_weir * l_weir), 2.0 / 3.0)
                lines.append(f"  Largo vertedero (= ancho zanja): {l_weir:.2f} m")
                lines.append(f"  Altura de rebalse:          {h_overflow:.4f} m")
                lines.append(f"                              {h_overflow * 100:.2f} cm")

        lines.append("-" * 55)
        lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # f) Infiltration Wells - Pozos de Infiltracion
    # ------------------------------------------------------------------

    @staticmethod
    def _dim_infiltration_well(vc, params):
        """Dimensioning for infiltration wells (Pozos de Infiltracion).

        Capacity: Q = K * A_lateral
        Depth calculation based on required volume and diameter.

        Parameters
        ----------
        vc : float
            Capture volume [m3].
        params : list
            [K (m/hr), diameter (m), depth (m)]
        """

        k = params[0]          # hydraulic conductivity [m/hr]
        diameter = params[1]   # well diameter [m]
        depth = params[2]      # well depth [m]

        lines = []
        lines.append("=" * 55)
        lines.append("  POZOS DE INFILTRACION (Infiltration Wells)")
        lines.append("=" * 55)
        lines.append(f"  Volumen de captura (Vc):    {vc:.4f} m3")
        lines.append(f"  Conductividad (K):          {k:.4f} m/hr")
        lines.append(f"  Diametro pozo:              {diameter:.2f} m")
        lines.append(f"  Profundidad pozo:           {depth:.2f} m")
        lines.append("-" * 55)

        if diameter <= 0:
            lines.append("  ERROR: El diametro del pozo debe ser > 0.")
            return "\n".join(lines)

        if depth <= 0:
            lines.append("  ERROR: La profundidad del pozo debe ser > 0.")
            return "\n".join(lines)

        radius = diameter / 2.0

        a_lateral = math.pi * diameter * depth
        lines.append(f"  Area lateral (A_lat):       {a_lateral:.4f} m2")
        lines.append(f"  Formula: A_lat = pi * D * H = pi * {diameter:.2f} * {depth:.2f}")

        a_bottom = math.pi * radius ** 2
        lines.append(f"  Area fondo (A_fondo):       {a_bottom:.4f} m2")

        a_total = a_lateral + a_bottom
        lines.append(f"  Area infiltracion total:    {a_total:.4f} m2")

        q_capacity = k * a_lateral
        lines.append(f"  Capacidad infiltracion (Q): {q_capacity:.6f} m3/hr")
        lines.append(f"  Formula: Q = K * A_lat = {k:.4f} * {a_lateral:.4f}")
        lines.append(f"  Capacidad (con fondo):      {k * a_total:.6f} m3/hr")

        v_well = math.pi * radius ** 2 * depth
        lines.append(f"  Volumen pozo:               {v_well:.4f} m3")

        if q_capacity > 0:
            t_drain = vc / q_capacity
            lines.append(f"  Tiempo vaciado estimado:    {t_drain:.2f} hr")
        else:
            lines.append("  AVISO: Capacidad de infiltracion es cero (K=0).")

        if radius > 0:
            depth_required = vc / (math.pi * radius ** 2)
            lines.append(f"  Prof. requerida (para almacenar Vc): {depth_required:.2f} m")
            if depth_required > depth:
                lines.append(f"  AVISO: La profundidad actual ({depth:.2f} m) es insuficiente.")
                lines.append(f"         Se requiere al menos {depth_required:.2f} m.")
            else:
                lines.append("  OK: La profundidad actual es suficiente para almacenar Vc.")

        if v_well > 0:
            n_wells = math.ceil(vc / v_well)
            lines.append(f"  Pozos necesarios (para Vc): {n_wells}")

        lines.append("-" * 55)
        lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # g) Porous Pavements - Pavimentos Porosos
    # ------------------------------------------------------------------

    @staticmethod
    def _dim_porous_pavement(vc, params):
        """Dimensioning for porous pavements (Pavimentos Porosos).

        Reservoir depth: d = Vc / (A_pavement * void_ratio)
        Subbase requirements based on traffic loads.

        Parameters
        ----------
        vc : float
            Capture volume [m3].
        params : list
            [A_pavement (m2), void_ratio (-), traffic_load (kN)]
        """

        a_pav = params[0]      # pavement area [m2]
        void_ratio = params[1]  # void ratio [-]
        traffic = params[2]     # traffic load [kN]

        lines = []
        lines.append("=" * 55)
        lines.append("  PAVIMENTOS POROSOS (Porous Pavements)")
        lines.append("=" * 55)
        lines.append(f"  Volumen de captura (Vc):    {vc:.4f} m3")
        lines.append(f"  Area pavimento:             {a_pav:.2f} m2")
        lines.append(f"  Razon de vacios:            {void_ratio:.2f}")
        lines.append(f"  Carga trafico:              {traffic:.1f} kN")
        lines.append("-" * 55)

        if a_pav <= 0:
            lines.append("  ERROR: El area del pavimento debe ser > 0.")
            return "\n".join(lines)

        if void_ratio <= 0 or void_ratio > 1:
            lines.append("  ERROR: La razon de vacios debe estar entre 0 y 1.")
            return "\n".join(lines)

        d = vc / (a_pav * void_ratio)

        lines.append(f"  Prof. reservorio (d):       {d:.4f} m")
        lines.append(f"                              {d * 100:.2f} cm")
        lines.append(f"  Formula: d = Vc / (A * n_v)")
        lines.append(f"         = {vc:.4f} / ({a_pav:.2f} * {void_ratio:.2f})")

        v_gross = a_pav * d
        lines.append(f"  Volumen bruto reservorio:   {v_gross:.4f} m3")

        lines.append("-" * 55)
        lines.append("  REQUERIMIENTOS DE SUBBASE:")
        if traffic <= 20:
            subbase = 0.15
            category = "Liviano (peatonal/ciclovia)"
        elif traffic <= 40:
            subbase = 0.20
            category = "Ligero (vehiculos livianos)"
        elif traffic <= 80:
            subbase = 0.30
            category = "Medio (vehiculos medianos)"
        elif traffic <= 120:
            subbase = 0.40
            category = "Pesado (vehiculos pesados)"
        else:
            subbase = 0.50
            category = "Muy Pesado (camiones)"

        lines.append(f"  Categoria trafico:          {category}")
        lines.append(f"  Espesor subbase recomendado: {subbase:.2f} m")

        total_depth = d + subbase
        lines.append(f"  Prof. total excavacion:     {total_depth:.2f} m")

        if d > 1.0:
            lines.append("  AVISO: Prof. reservorio > 1.0 m. Considere aumentar el area.")
        elif d < 0.10:
            lines.append("  AVISO: Prof. reservorio < 0.10 m. Verifique parametros.")

        lines.append("-" * 55)
        lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # h) Cellular Pavements - Pavimentos Celulares
    # ------------------------------------------------------------------

    @staticmethod
    def _dim_cellular_pavement(vc, params):
        """Dimensioning for cellular pavements (Pavimentos Celulares).

        Grid sizing based on load capacity and infiltration area percentage.

        Parameters
        ----------
        vc : float
            Capture volume [m3].
        params : list
            [A_pavement (m2), load_capacity (kPa), infiltration_pct (%),
             void_ratio (-)]
        """

        a_pav = params[0]            # pavement area [m2]
        load_capacity = params[1]    # load capacity [kPa]
        infiltration_pct = params[2] # infiltration area percentage [%]
        void_ratio = params[3]       # void ratio [-]

        lines = []
        lines.append("=" * 55)
        lines.append("  PAVIMENTOS CELULARES (Cellular Pavements)")
        lines.append("=" * 55)
        lines.append(f"  Volumen de captura (Vc):    {vc:.4f} m3")
        lines.append(f"  Area pavimento:             {a_pav:.2f} m2")
        lines.append(f"  Capacidad carga:            {load_capacity:.1f} kPa")
        lines.append(f"  Porcentaje infiltracion:    {infiltration_pct:.1f} %")
        lines.append(f"  Razon de vacios:            {void_ratio:.2f}")
        lines.append("-" * 55)

        if a_pav <= 0:
            lines.append("  ERROR: El area del pavimento debe ser > 0.")
            return "\n".join(lines)

        if infiltration_pct <= 0 or infiltration_pct > 100:
            lines.append("  ERROR: El porcentaje de infiltracion debe estar entre 0 y 100.")
            return "\n".join(lines)

        if void_ratio <= 0 or void_ratio > 1:
            lines.append("  ERROR: La razon de vacios debe estar entre 0 y 1.")
            return "\n".join(lines)

        a_infiltration = a_pav * (infiltration_pct / 100.0)
        a_solid = a_pav - a_infiltration

        lines.append(f"  Area infiltracion efectiva: {a_infiltration:.2f} m2")
        lines.append(f"  Area solida (celdas):       {a_solid:.2f} m2")

        # Reservoir depth (using void ratio of subbase material)
        d = vc / (a_pav * void_ratio)

        lines.append(f"  Prof. reservorio (d):       {d:.4f} m")
        lines.append(f"                              {d * 100:.2f} cm")
        lines.append(f"  Formula: d = Vc / (A * n_v)")
        lines.append(f"         = {vc:.4f} / ({a_pav:.2f} * {void_ratio:.2f})")

        lines.append("-" * 55)
        lines.append("  DIMENSIONAMIENTO DE GRILLA:")

        if load_capacity <= 100:
            cell_size = "Celda pequena: 30x30 cm"
            wall_thickness = 3.0  # cm
        elif load_capacity <= 300:
            cell_size = "Celda mediana: 40x40 cm"
            wall_thickness = 4.0
        elif load_capacity <= 500:
            cell_size = "Celda grande: 50x50 cm"
            wall_thickness = 5.0
        else:
            cell_size = "Celda reforzada: 60x60 cm"
            wall_thickness = 6.0

        lines.append(f"  Tamano celda recomendado:   {cell_size}")
        lines.append(f"  Espesor pared celda:        {wall_thickness:.1f} cm")

        cell_area_m2 = (0.30 if load_capacity <= 100
                        else 0.40 if load_capacity <= 300
                        else 0.50 if load_capacity <= 500
                        else 0.60) ** 2
        n_cells = math.ceil(a_pav / cell_area_m2)
        lines.append(f"  Numero estimado de celdas:  {n_cells}")

        v_stored = a_pav * d * void_ratio
        lines.append(f"  Volumen almacenado:         {v_stored:.4f} m3")

        if v_stored >= vc:
            lines.append(f"  OK: Volumen almacenado ({v_stored:.4f} m3) >= Vc ({vc:.4f} m3)")
        else:
            lines.append(f"  DEFICIT: Falta {vc - v_stored:.4f} m3")

        if d > 0.80:
            lines.append("  AVISO: Prof. reservorio > 0.80 m. Considere aumentar el area.")

        lines.append("-" * 55)
        lines.append("")

        return "\n".join(lines)
