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
from qtpy.QtCore import Qt, Signal, QRect, QEvent
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

class GroupAssignmentWindow(QDialog):
    def __init__(self, file_group_mapping, group, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Group Assignment")

        QSS = ("""
            QDialog {
                background-color: #282a36;
                color: #f8f8f2;
            }
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
            QLabel {
                color: #f8f8f2;
            }
            QSpinBox {
                 min-width: 35px;
            }
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
        self.setStyleSheet(QSS)

        self.files_to_add = []
        self.setFont(QFont("Arial", 10))
        self.file_check_buttons = QVBoxLayout(self)
        self.file_check_buttons.setSpacing(8)
        self.file_check_buttons.setContentsMargins(5, 5, 5, 5)
        self.file_check_buttons.addWidget(QLabel(f"Select files to add to group {group}:"))
        for file in file_group_mapping.keys():
            h = QHBoxLayout()
            check = QCheckBox()
            file_name = QLabel(file)
            current_group = QLabel(f"Current Group: {file_group_mapping[file]}")
            h.addWidget(check)
            h.addWidget(file_name)
            h.addWidget(current_group)
            self.file_check_buttons.addLayout(h)

        save_btn = QPushButton("Save changes")
        save_btn.clicked.connect(self.save_groups)
        self.file_check_buttons.addWidget(save_btn)

    def save_groups(self):
        self.files_to_add = []
        for row in [self.file_check_buttons.itemAt(i).layout() for i in range(1, self.file_check_buttons.count()-1)]:
            check_box = row.itemAt(0).widget()
            label = row.itemAt(1).widget()
            if (check_box.isChecked()):
                self.files_to_add.append(label.text())
        self.accept()
    
    def get_group_assignments(self):
        return self.files_to_add