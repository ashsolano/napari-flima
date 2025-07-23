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

        self.setStyleSheet("""
            QDialog {
                background-color: #282a36;
                color: #f8f8f2;
            }
            QLabel {
                color: #f8f8f2;
            }
            QSpinBox {
                 min-width: 35px;
            }

        """)
        self.files_to_add = []
        self.setFont(QFont("Arial", 10))
        self.file_check_buttons = QVBoxLayout(self)
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
        for row in [self.file_check_buttons.itemAt(i) for i in range(0, self.file_check_buttons.count())]:
            if row.check.isChecked():
                self.files_to_add.append(row.file_name.getText())
        self.accept()
    
    def get_group_assignments(self):
        return self.files_to_add