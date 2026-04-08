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
        self._fill_action_menu()

        if toolbar is not None:
            self.action.setMenu(self.menu)
            toolbar.addAction(self.action)

    def clicked_event(self):
        self._fill_action_menu()
        if hasattr(self.action, 'associatedObjects'):
            button = QWidget(self.action.associatedObjects()[1])
        elif hasattr(self.action, 'associatedWidgets'):
            button = self.action.associatedWidgets()[1]
        menu_point = button.mapToGlobal(QPoint(0, button.height()))
        self.menu.exec(menu_point)

    def _fill_action_menu(self):
        """ Fill action menu with MDU tool options """

        actions = self.menu.actions()
        for action in actions:
            action.disconnect()
            self.menu.removeAction(action)
            del action
        ag = QActionGroup(self.iface.mainWindow())

        hydro_menu = self.menu.addMenu(tools_qt.tr("Hidrologia"))
        design_menu = self.menu.addMenu(tools_qt.tr("Diseno de Obras"))
        network_menu = self.menu.addMenu(tools_qt.tr("Red de Drenaje"))

        new_actions = [
            (hydro_menu, ('ud', 'ws'), tools_qt.tr('Curvas IDF Chile'), None),
            (hydro_menu, ('ud', 'ws'), tools_qt.tr('Metodo Racional'), None),
            (hydro_menu, ('ud', 'ws'), tools_qt.tr('Tiempo de Concentracion'), None),
            (design_menu, ('ud', 'ws'), tools_qt.tr('Diseno de Sumideros'), None),
            (design_menu, ('ud', 'ws'), tools_qt.tr('Obras de Infiltracion'), None),
            (design_menu, ('ud', 'ws'), tools_qt.tr('Obras de Retencion'), None),
            (network_menu, ('ud', 'ws'), tools_qt.tr('Clasificacion Jerarquica'), None),
        ]

        for menu, types, action, icon in new_actions:
            if global_vars.project_type in types:
                if icon:
                    obj_action = QAction(icon, f"{action}", ag)
                else:
                    obj_action = QAction(f"{action}", ag)
                menu.addAction(obj_action)
                obj_action.triggered.connect(partial(self._get_selected_action, action))

        for menu in self.menu.findChildren(QMenu):
            if not len(menu.actions()):
                menu.menuAction().setParent(None)

    def _get_selected_action(self, name):
        """ Gets selected action """

        if name == tools_qt.tr('Curvas IDF Chile'):
            tool = IdfCurves()
            tool.clicked_event()

        elif name == tools_qt.tr('Metodo Racional'):
            tool = RationalMethod()
            tool.clicked_event()

        elif name == tools_qt.tr('Tiempo de Concentracion'):
            tool = TimeOfConcentration()
            tool.clicked_event()

        elif name == tools_qt.tr('Diseno de Sumideros'):
            tool = InletDesign()
            tool.clicked_event()

        elif name == tools_qt.tr('Obras de Infiltracion'):
            tool = InfiltrationWorks()
            tool.clicked_event()

        elif name == tools_qt.tr('Obras de Retencion'):
            tool = RetentionWorks()
            tool.clicked_event()

        elif name == tools_qt.tr('Clasificacion Jerarquica'):
            tool = NetworkHierarchy()
            tool.clicked_event()
