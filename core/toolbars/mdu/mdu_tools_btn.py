"""
This file is part of Giswater
The program is free software: you can redistribute it and/or modify it under the terms of the GNU
General Public License as published by the Free Software Foundation, either version 3 of the License,
or (at your option) any later version.
"""
# -*- coding: utf-8 -*-
from functools import partial

from qgis.PyQt.QtCore import QPoint
from qgis.PyQt.QtWidgets import QMenu, QAction, QActionGroup, QWidget

from ..dialog import GwAction
from .... import global_vars
from ....libs import tools_qgis, tools_qt
from .mdu_tools.idf_curves import IdfCurves
from .mdu_tools.rational_method import RationalMethod
from .mdu_tools.time_of_concentration import TimeOfConcentration
from .mdu_tools.inlet_design import InletDesign
from .mdu_tools.infiltration_works import InfiltrationWorks
from .mdu_tools.retention_works import RetentionWorks
from .mdu_tools.network_hierarchy import NetworkHierarchy


class GwMduTools(GwAction):
    """ Button 91: MDU Tools - Manual de Drenaje Urbano (Chile) """

    def __init__(self, icon_path, action_name, text, toolbar, action_group):

        super().__init__(icon_path, action_name, text, toolbar, action_group)
        self.iface = global_vars.iface

        self.menu = QMenu()
        self.menu.setObjectName("GW_mdu_tools")

        if toolbar is not None:
            self.action.setMenu(self.menu)
            toolbar.addAction(self.action)

    def clicked_event(self):
        self.menu.clear()
        self._fill_action_menu()
        if hasattr(self.action, 'associatedObjects'):
            button = QWidget(self.action.associatedObjects()[1])
        elif hasattr(self.action, 'associatedWidgets'):
            button = self.action.associatedWidgets()[1]
        menu_point = button.mapToGlobal(QPoint(0, button.height()))
        self.menu.exec(menu_point)

    def _fill_action_menu(self):
        """ Fill action menu with MDU tool options """

        ag = QActionGroup(self.iface.mainWindow())

        hydro_menu = self.menu.addMenu("Hidrologia")
        design_menu = self.menu.addMenu("Diseno de Obras")
        network_menu = self.menu.addMenu("Red de Drenaje")

        tool_actions = [
            (hydro_menu, 'Curvas IDF Chile'),
            (hydro_menu, 'Metodo Racional'),
            (hydro_menu, 'Tiempo de Concentracion'),
            (design_menu, 'Diseno de Sumideros'),
            (design_menu, 'Obras de Infiltracion'),
            (design_menu, 'Obras de Retencion'),
            (network_menu, 'Clasificacion Jerarquica'),
        ]

        for menu, action_name in tool_actions:
            obj_action = QAction(f"{action_name}", ag)
            menu.addAction(obj_action)
            obj_action.triggered.connect(partial(self._get_selected_action, action_name))

    def _get_selected_action(self, name):
        """ Gets selected action """

        tools = {
            'Curvas IDF Chile': IdfCurves,
            'Metodo Racional': RationalMethod,
            'Tiempo de Concentracion': TimeOfConcentration,
            'Diseno de Sumideros': InletDesign,
            'Obras de Infiltracion': InfiltrationWorks,
            'Obras de Retencion': RetentionWorks,
            'Clasificacion Jerarquica': NetworkHierarchy,
        }

        tool_class = tools.get(name)
        if tool_class:
            tool = tool_class()
            tool.clicked_event()
