import os
import numpy as np
import superqt as sqt
import matplotlib
import matplotlib.pyplot as plt
from math import ceil
from scipy import signal
from matplotlib.colors import CSS4_COLORS
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from napari.utils.colormaps import Colormap
from qtpy.QtCore import Qt, Signal, QRect, QEvent, QThread
from qtpy.QtGui import (
    QClipboard, QPixmap, QColor, QStandardItem, QStandardItemModel,
    QPainter, QFont, QBrush, QIcon, QDoubleValidator, QIntValidator
)
from qtpy.QtWidgets import (
    QApplication, QWidget, QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QCheckBox, QComboBox, QSpinBox, QDoubleSpinBox, QStyledItemDelegate,
    QStyle, QStyleOptionComboBox, QStyleOptionGroupBox, QScrollArea, QSizePolicy, QGroupBox, QLabel,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView, QFormLayout,
    QGridLayout, QFileDialog, QSlider, QToolTip
)
from qtpy.QtCore import QTimer
from functools import partial

from .utils import (
    ColorSelectorApp
)
from .config import CursorConfig

import imageio

# ---------------------------------------------------------------------------
# Cursor selection widget 

class CursorAnalysisWidget(QGroupBox):
    """
    A QTableWidget-based cursor analysis table with:
      - An "Active" checkbox column
      - A "Color" selector column
      - Numeric columns for R, G, S, τₘ, τₚ
      - A fixed-width "Remove" column with an ✕ button to delete the row
    """
    def __init__(self, parent=None, title="🛈 &Cursor Analysis", font=None):
        super().__init__(title, parent)
        self._phasorwidget_ptr = parent
        self.default_font = font or QFont("Arial", 12)
        self.setFont(self.default_font)
        self._title_tooltip = "sample tooltip"
        self.installEventFilter(self)

        self.setStyleSheet("""
            QGroupBox {
                border: 1px solid #707070;
                background-color: qlineargradient(
                    x1:0, y1:0, x2:0, y2:1,
                    stop:0 #282a36, stop:1 #33353b
                );
                margin-top: 10px;
                padding: 5px;
                border-radius: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #f8f8f2;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)

        # 1) Create the table with 8 columns instead of 7
        self.table = QTableWidget(0, 8, self)
        self.table.setFont(self.default_font)
        self.table.setHorizontalHeaderLabels([
            "Active", "Color", "R", "G", "S", "τₘ", "τₚ", ""
        ])
        # Remove extra margins on the table itself
        self.table.setContentsMargins(0, 0, 0, 0)

        # 2) Fix the last column to button width (no stretch)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(7, QHeaderView.Fixed)
        self.table.setColumnWidth(7, 24)
        self.table.itemChanged.connect(self._update_cursor_position)

        # Optionally set reasonable widths for other columns
        widths = [50, 60, 40, 40, 40, 50, 50]
        for idx, w in enumerate(widths):
            self.table.setColumnWidth(idx, w)

        layout.addWidget(self.table)

        # “Add Cursor” button
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        add_cursor_btn = QPushButton("Add Cursor")
        add_cursor_btn.setFont(self.default_font)
        add_cursor_btn.setStyleSheet("""
            QPushButton {
                background-color: #007acc;
                color: white;
                border-radius: 4px;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background-color: #005f99;
            }
        """)
        add_cursor_btn.clicked.connect(self.add_cursor_row)
        btn_layout.addWidget(add_cursor_btn)
        layout.addLayout(btn_layout)

        self.cursor_rows_data = []

    def eventFilter(self, source, event):
        if source == self and event.type() == QEvent.ToolTip:
            options = QStyleOptionGroupBox()
            control = self.style().hitTestComplexControl(
                QStyle.CC_GroupBox, options, event.pos()
            )
            if control == QStyle.SC_GroupBoxLabel or control == QStyle.SC_GroupBoxCheckBox:
                QToolTip.showText(event.globalPos(), self._title_tooltip)
                return True
            else:
                QToolTip.hideText()
                return True
            
        return super().eventFilter(source, event)

    def add_cursor_row(self):
        """Insert a new row with Active, Color, R, G, S, τₘ, τₚ, and Remove."""
        self.table.blockSignals(True)
        #QApplication.setOverrideCursor(QtCore.Qt.WaitCursor)
        row = self.table.rowCount()
        self.table.insertRow(row)
        row_data = {}

        # Column 0: Active checkbox
        checkbox = QCheckBox()
        wrapper = QWidget()
        hl = QHBoxLayout(wrapper)
        hl.setContentsMargins(0,0,0,0)
        hl.addStretch(); hl.addWidget(checkbox); hl.addStretch()
        self.table.setCellWidget(row, 0, wrapper)
        checkbox.stateChanged.connect(
            lambda state, idx=row: self.parent().cursor_checkbox_state_changed(state, idx)
        )
        row_data["checkbox"] = checkbox

        # Column 1: Color selector
        color_selector = ColorSelectorApp()
        color_selector.setFixedWidth(50)
        self.table.setCellWidget(row, 1, color_selector)
        row_data["color_selector"] = color_selector

        # Columns 2–6: Numeric defaults
        defaults = ["0.05","0.00","0.00","0.00","0.00"]
        for i, col in enumerate([2,3,4,5,6]):
            item = QTableWidgetItem(defaults[i])
            item.setTextAlignment(Qt.AlignCenter)
            item.setBackground(QBrush(QColor("white")))
            item.setForeground(QBrush(QColor("black")))
            self.table.setItem(row, col, item)
            row_data[f"col_{col}"] = item

        # Column 7: Remove button (fixed, no margins)
        remove_btn = QPushButton("✕")
        remove_btn.setFixedWidth(24)
        remove_btn.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        remove_btn.setStyleSheet("""
            QPushButton {
                border: none;
                font-weight: bold;
                color: #c0392b;
            }
            QPushButton:hover {
                background-color: rgba(192, 57, 43, 0.1);
            }
        """)
        # wrap to center with zero margins
        btn_container = QWidget()
        ph = QHBoxLayout(btn_container)
        ph.setContentsMargins(0,0,0,0)
        ph.addStretch(); ph.addWidget(remove_btn); ph.addStretch()
        self.table.setCellWidget(row, 7, btn_container)
        remove_btn.clicked.connect(partial(self._remove_cursor_row, row))
        row_data["remove_btn"] = remove_btn

        self.cursor_rows_data.append(row_data)
        self.table.blockSignals(False)
        #QApplication.restoreOverrideCursor()
    
    def _update_cursor_position(self, item):
        row = item.row()
        x = float(self.cursor_rows_data[row]["col_3"].text())
        y = float(self.cursor_rows_data[row]["col_4"].text())
        self.table.blockSignals(True)
        self._phasorwidget_ptr.update_g_s_values(row, x, y)
        self.table.blockSignals(False)

    def _remove_cursor_row(self, row):
        """Remove the row and any associated cursor patch."""
        rd = self.cursor_rows_data[row]
        # If still active, toggle off to remove patch
        if rd["checkbox"].isChecked():
            rd["checkbox"].setChecked(False)
        else:
            # ensure no lingering patch
            self.parent().dialog.remove_cursor(row)

        # Remove the UI row and data
        self.table.removeRow(row)
        self.cursor_rows_data.pop(row)

        # Re-wire indices
        for new_row, rd in enumerate(self.cursor_rows_data):
            cb = rd["checkbox"]
            cb.stateChanged.disconnect()
            cb.stateChanged.connect(
                lambda state, idx=new_row: self.parent().cursor_checkbox_state_changed(state, idx)
            )
            btn = rd["remove_btn"]
            btn.clicked.disconnect()
            btn.clicked.connect(partial(self._remove_cursor_row, new_row))

    def get_cursor_settings(self):
        """Return settings for all active cursors."""
        settings = []
        for rd in self.cursor_rows_data:
            if rd["checkbox"].isChecked():
                settings.append({
                    "active": True,
                    "color": rd["color_selector"].currentText(),
                    "radius": float(rd["col_2"].text()),
                    "g_value": float(rd["col_3"].text()),
                    "s_value": float(rd["col_4"].text()),
                    "tau_m": float(rd["col_5"].text()),
                    "tau_p": float(rd["col_6"].text()),
                })
        return settings

    def clear_cursors(self):
        """Remove all cursor rows."""
        while self.table.rowCount() > 0:
            self._remove_cursor_row(0)

    def get_all_cursor_configs(self) -> list:
        """Return list of CursorConfig for all rows (both active and inactive)."""
        configs = []
        for rd in self.cursor_rows_data:
            configs.append(CursorConfig(
                active=rd["checkbox"].isChecked(),
                color=rd["color_selector"].currentText(),
                radius=float(rd["col_2"].text()),
                g_value=float(rd["col_3"].text()),
                s_value=float(rd["col_4"].text()),
                tau_m=float(rd["col_5"].text()),
                tau_p=float(rd["col_6"].text()),
            ))
        return configs

    def set_cursor_settings(self, cursor_configs: list):
        """Clear existing rows and populate cursor table from cursor configs."""
        self.clear_cursors()
        for cfg in cursor_configs:
            self.add_cursor_row()
            row = self.table.rowCount() - 1
            rd = self.cursor_rows_data[row]
            
            if isinstance(cfg, CursorConfig):
                active = cfg.active
                color = cfg.color
                radius = cfg.radius
                g_val = cfg.g_value
                s_val = cfg.s_value
                tau_m = cfg.tau_m
                tau_p = cfg.tau_p
            else:
                active = cfg.get("active", True)
                color = cfg.get("color", "red")
                radius = cfg.get("radius", 0.05)
                g_val = cfg.get("g_value", 0.0)
                s_val = cfg.get("s_value", 0.0)
                tau_m = cfg.get("tau_m", 0.0)
                tau_p = cfg.get("tau_p", 0.0)

            rd["checkbox"].setChecked(active)
            if color in [rd["color_selector"].itemText(i) for i in range(rd["color_selector"].count())]:
                rd["color_selector"].setCurrentText(color)
            
            self.table.blockSignals(True)
            rd["col_2"].setText(str(radius))
            rd["col_3"].setText(str(g_val))
            rd["col_4"].setText(str(s_val))
            rd["col_5"].setText(str(tau_m))
            rd["col_6"].setText(str(tau_p))
            self.table.blockSignals(False)