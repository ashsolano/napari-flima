import os
import numpy as np
import superqt as sqt
import matplotlib
import matplotlib.pyplot as plt
from math import ceil
from scipy import signal

from napari.utils.colormaps import Colormap
from qtpy.QtCore import Qt, Signal, QRect, QEvent, QTimer, QThread
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
from functools import partial

from .group_assignment_dialog import GroupAssignmentWindow

import imageio

# ---------------------------------------------------------------------------
# File selection table widget               

class FileSelectionTable(QGroupBox):
    """
    A compact, gradient-style file selection widget (like channel config).
    - At the top: "Add Group" line + button so the user can define new group names.
    - A scroll area listing each file row:
    [File label | checkbox | group combo | threshold slider + numeric label].

    - Non-editable group combo (the user must add new groups via the "Add Group" field).
    - Minimal spacing to reduce vertical space.

    :signal threshold_changed: emits when the intensity threshold of an image changes
        (file_name -> string, (threshold_value_lower -> int, threshold_value_upper -> int))

    :signal groups_updated: emits when the list of image groups is updated
        (group_list -> list(string))
    """

    threshold_changed = Signal(str, object)  # (file_name, (threshold_value_lower, threshold_value_upper))
    groups_updated = Signal(list)  # Signal to emit updated group list
    mask_changed = Signal(str, str) # (file_name, mask_layer_name)

    def __init__(self, parent=None, title="🛈 &File Selection", font=None):
        super().__init__(title, parent)
        self.parent_widget = parent
        self.default_font = font if font else QFont("Arial", 12)
        self.setFont(self.default_font)
        self._title_tooltip = "sample tooltip"
        self.installEventFilter(self)

        # Style it like the channel config
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

        self.file_rows = {}   # {file_name: {... row references ...}}
        self.known_groups = ["None", "Condition 1", "Condition 2"]  # Default group names
        #self.analysis_data["group_list"] = self.known_groups
        
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(5, 5, 5, 5)

        # (A) Add a small "Add Group" row at the top
        group_row = QHBoxLayout()
        group_row.setSpacing(5)
        group_label = QLabel("Add Group:")
        group_label.setStyleSheet("color: #f8f8f2;")
        group_label.setFont(self.default_font)

        self.group_line_edit = QLineEdit()
        self.group_line_edit.setFont(self.default_font)
        self.group_line_edit.setPlaceholderText("Enter new group name")

        add_group_btn = QPushButton("Add")
        add_group_btn.setFont(self.default_font)
        add_group_btn.setStyleSheet("""
            QPushButton {
                background-color: #007acc;
                color: white;
                font-weight: bold;
                border-radius: 4px;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background-color: #005f99;
            }
        """)
        add_group_btn.clicked.connect(self.on_add_group)
        self.group_line_edit.editingFinished.connect(self.on_add_group)

        group_row.addWidget(group_label)
        group_row.addWidget(self.group_line_edit)
        group_row.addWidget(add_group_btn)
        main_layout.addLayout(group_row)

        # (B) Instruction label (optional)
        instruct_label = QLabel("For each file, select a group and threshold:")
        instruct_label.setFont(self.default_font)
        instruct_label.setStyleSheet("color: #f8f8f2;")
        main_layout.addWidget(instruct_label)

        # (C) Scroll area to list file rows
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.files_container = QWidget()
        self.files_layout = QVBoxLayout(self.files_container)
        self.files_layout.setSpacing(4)
        self.files_layout.setContentsMargins(0, 0, 0, 0)
        self.scroll_area.setWidget(self.files_container)
        main_layout.addWidget(self.scroll_area)

        # (D) Select all files in group
        self.group_select = QHBoxLayout()
        add_to_phasor_button = QPushButton("Add Group to Phasor Plot")
        add_to_phasor_button.setStyleSheet("""
            QPushButton {
                background-color: #007acc;
                color: white;
                font-weight: bold;
                border-radius: 4px;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background-color: #005f99;
            }
        """)
        group_select_combo = QComboBox()
        group_select_combo.setFont(self.default_font)
        group_select_combo.setEditable(False)
        group_select_combo.addItems(self.known_groups)
        group_select_combo.setFixedWidth(100)  # align combos
        self.group_select.addWidget(group_select_combo)
        add_to_phasor_button.clicked.connect(lambda: self.add_group_to_phasor(selected_group=group_select_combo.currentText()))
        self.group_select.addWidget(add_to_phasor_button)
        main_layout.addLayout(self.group_select)
        
        # (E) Load Mask Button
        load_mask_btn = QPushButton("Load Mask File...")
        load_mask_btn.setFont(self.default_font)
        load_mask_btn.clicked.connect(self.on_load_mask_clicked)
        main_layout.addWidget(load_mask_btn)

        main_layout.addStretch()

    def on_load_mask_clicked(self):
        """Handle load mask button click"""
        if hasattr(self.parent_widget, "load_mask_file"):
            self.parent_widget.load_mask_file()

    def add_group_to_phasor(self, selected_group = "None"):
        """Adds an entire group to the phasor plot
        
        :param str selected_group: name of group to add to phasor plot
        """
        print(f"group selected to add: {selected_group}")
        for file_name in [file for file, group in self.get_file_group_mapping().items() if group == selected_group]:
            print(f"changing state of {file_name}")
            self.file_rows[file_name]["checkbox"].setCheckState(2)
    
    def eventFilter(self, source, event):
        """Event filter for catching duplicate signals when programatically modifying values
        
        :meta private:
        """
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
    
    def on_add_group(self):
        new_group = self.group_line_edit.text().strip()
        if new_group and new_group not in self.known_groups:
            self.known_groups.append(new_group)
            self.known_groups.sort()
            self.update_all_combos()
            # If analysis_data is available, update it:
            if hasattr(self, "analysis_data"):
                self.analysis_data["group_list"] = self.known_groups
                #print("Updated analysis_data group_list:", self.analysis_data["group_list"])
            # Emit the signal with the updated list.
            self.groups_updated.emit(self.known_groups)
            current_group_mapping = self.get_file_group_mapping()
            group_assignment_dialog = GroupAssignmentWindow(current_group_mapping, new_group)
            if group_assignment_dialog.exec_() == QDialog.Accepted:
                for f in group_assignment_dialog.get_group_assignments():
                    self._set_file_group(f, new_group)
        self.group_line_edit.clear()

        

    def update_all_combos(self):
        """Refreshes the group combo box items in all file rows"""
        for row_info in self.file_rows.values():
            combo = row_info["group_combo"]
            current_text = combo.currentText()
            combo.clear()
            combo.addItems(self.known_groups)
            # Restore the previously selected text if still valid
            if current_text in self.known_groups:
                combo.setCurrentText(current_text)
        group_select_combo = self.group_select.layout().itemAt(0).widget()
        current_text = group_select_combo.currentText()
        group_select_combo.clear()
        group_select_combo.addItems(self.known_groups)
        # Restore the previously selected text if still valid
        if current_text in self.known_groups:
            group_select_combo.setCurrentText(current_text)

    def update_mask_choices(self, mask_layers):
        """Updates the mask combo box items in all file rows
        
        :param list mask_layers: list of available mask layer names
        """
        self.current_mask_layers = ["None"] + mask_layers
        
        for row_info in self.file_rows.values():
            combo = row_info["mask_combo"]
            current_text = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(self.current_mask_layers)
            
            if current_text in self.current_mask_layers:
                combo.setCurrentText(current_text)
            else:
                combo.setCurrentText("None")
            combo.blockSignals(False)
                
    def get_group_list(self):
        """Return the current list of groups"""
        return self.known_groups

    def add_file(self, file_path, layer_data):
        """Adds a row for the given file. Layout: [checkbox | file_name | group_combo | threshold].
        Each has fixed width to align columns.

        :param str file_path: file path of new file
        :param numpy.ndarray layer_data: channel data for the new file
        """

        file_name = os.path.basename(file_path)

        row_layout = QHBoxLayout()
        row_layout.setSpacing(5)
        row_layout.setContentsMargins(0, 0, 0, 0)

        # 1) Checkbox
        checkbox = QCheckBox()
        checkbox.setFixedWidth(20)  # keep it small
        checkbox.setChecked(False)
        checkbox.stateChanged.connect(lambda state, name=file_name: self.on_checkbox_state_changed(state, name))
        row_layout.addWidget(checkbox)

        # 2) File name label
        file_label = QLabel(file_name)
        file_label.setToolTip(file_name)
        file_label.setFont(self.default_font)
        file_label.setStyleSheet("color: #f8f8f2;")
        file_label.setFixedWidth(100)  # fixed for alignment
        row_layout.addWidget(file_label)

        # 3) Group combo
        group_combo = QComboBox()
        group_combo.setFont(self.default_font)
        group_combo.setEditable(False)
        group_combo.addItems(self.known_groups)
        group_combo.setStyleSheet("""
            QComboBox {
                background-color: white;
                color: black;
                border: 1px solid #707070;
                padding: 5px;
            }
            QComboBox QAbstractItemView {
                background-color: white;
                selection-background-color: #707070;
                color: black;
            }
        """)
        row_layout.addWidget(group_combo)

        # 4) Mask Selector
        mask_combo = QComboBox()
        mask_combo.setFont(self.default_font)
        mask_combo.setEditable(False)
        mask_combo.setFixedWidth(100)
        # Populate with current masks if available (tracked in self.current_mask_layers or empty)
        if hasattr(self, "current_mask_layers"):
             mask_combo.addItems(self.current_mask_layers)
        else:
             mask_combo.addItem("None")

        mask_combo.setStyleSheet("""
            QComboBox {
                background-color: white;
                color: black;
                border: 1px solid #707070;
                padding: 5px;
            }
            QComboBox QAbstractItemView {
                background-color: white;
                selection-background-color: #707070;
                color: black;
            }
        """)
        mask_combo.currentTextChanged.connect(lambda text, fn=file_name: self.mask_changed.emit(fn, text))
        row_layout.addWidget(mask_combo)

        # 5) Threshold slider + numeric label
        threshold_layout = QHBoxLayout()
        threshold_layout.setSpacing(2)
        threshold_widget = QWidget()
        threshold_widget.setLayout(threshold_layout)
        threshold_widget.setFixedWidth(200)  # ensure alignment across rows

        QSS = """
            QRangeSlider::handle:horizontal {
                background: #007acc;
                width: 4px;
                height: 24px;
                margin: -12px 0px;
            }
        """

        slider = sqt.QRangeSlider(Qt.Horizontal)
        max_intensity = int(np.max(layer_data))
        slider.setMinimum(0)
        slider.setMaximum(max_intensity)
        slider.setValue((0, max_intensity))
        slider.setStyleSheet(QSS)

        val_low_label = QLineEdit()
        val_low_label.setValidator(QIntValidator())
        val_low_label.setFixedWidth(50)
        val_low_label.setAlignment(Qt.AlignCenter)
        val_low_label.setText("0")

        
        val_high_label = QLineEdit()
        val_high_label.setValidator(QIntValidator())
        val_high_label.setFixedWidth(50)
        val_high_label.setAlignment(Qt.AlignCenter)
        val_high_label.setText(str(max_intensity))

        val_low_label.textEdited.connect(lambda val_low, fn=file_name: self.threshold_changed.emit(fn, (int('0'+val_low), int(val_high_label.text()))))
        val_low_label.textEdited.connect(lambda val_low: slider.setSliderPosition((int('0'+val_low), int(val_high_label.text()))))
        val_low_label.editingFinished.connect(lambda fn=file_name: self.parent_widget.slider_released(fn))

        val_high_label.textEdited.connect(lambda val_high, fn=file_name: self.threshold_changed.emit(fn, (int(val_low_label.text()), int('0'+val_high))))
        val_high_label.textEdited.connect(lambda val_high: slider.setSliderPosition((int(val_low_label.text()), int('0'+val_high))))
        val_high_label.editingFinished.connect(lambda fn=file_name: self.parent_widget.slider_released(fn))

        slider.valueChanged.connect(lambda val, fn=file_name: self.threshold_changed.emit(fn, val))
        slider.valueChanged.connect(lambda val: val_low_label.setText(str(val[0])))
        slider.valueChanged.connect(lambda val: val_high_label.setText(str(val[1])))
        slider.sliderReleased.connect(lambda fn=file_name: self.parent_widget.slider_released(fn))


        threshold_layout.addWidget(slider)
        threshold_layout.addWidget(val_low_label)
        threshold_layout.addWidget(val_high_label)
        row_layout.addWidget(threshold_widget)

        # Add row_layout to the files_layout
        self.files_layout.addLayout(row_layout)

        # Store references
        self.file_rows[file_name] = {
            "checkbox": checkbox,
            "file_label": file_label,
            "group_combo": group_combo,
            "mask_combo": mask_combo,
            "slider": slider,
            "val_low_label": val_low_label,
            "val_high_label": val_high_label,
            "layer_data": layer_data
        }
        # Automatically expand and reduce size of File Selection Box to adapt to number of files
        self.scroll_area.setMinimumHeight(min(len(self.file_rows)*50, 200))

    def remove_file(self, file_path):
        """Removes a row from the file selection table

        :param str file_path: path of the file to remove
        """
        file_name = os.path.basename(file_path)
        if file_name not in self.file_rows:
            return

        row_info = self.file_rows[file_name]
        # We can locate the row_layout by searching for 'file_label'
        label_widget = row_info["file_label"]

        # Step through self.files_layout to find the layout containing this label
        for i in reversed(range(self.files_layout.count())):
            item = self.files_layout.itemAt(i)
            if item is not None and item.layout() is not None:
                row_layout = item.layout()
                # Check if this layout contains label_widget
                for j in range(row_layout.count()):
                    w = row_layout.itemAt(j).widget()
                    if w == label_widget:
                        # This is the correct row layout
                        while row_layout.count():
                            c = row_layout.takeAt(0)
                            if c.widget():
                                c.widget().deleteLater()
                        self.files_layout.removeItem(row_layout)
                        row_layout.deleteLater()
                        break
        del self.file_rows[file_name]

        # Automatically expand and reduce size of File Selection Box to adapt to number of files
        self.scroll_area.setMinimumHeight(min(len(self.file_rows)*50, 200))

    def on_checkbox_state_changed(self, state, file_name):
        """If your main widget has on_checkbox_state_changed, call it.
        
        :meta private:
        """
        if hasattr(self.parent_widget, "on_checkbox_state_changed"):
            self.parent_widget.on_checkbox_state_changed(state, file_name)
            
    
    def get_file_group_mapping(self):
        """Get a dictionary mapping of images to the currently selected group
        Example: { "file1.tif": "Condition 1", "file2.tif": "PLA2", ... }

        :returns: a dictionary that maps file names of images to the name of the group they're assigned to
        :rtype: dict[str, str]
        """
        mapping = {}
        for file_name, row_info in self.file_rows.items():
            # Assume each row_info has a "group_combo" widget.
            mapping[file_name] = row_info["group_combo"].currentText()
        return mapping
    
    def _set_file_group(self, file_name, group):
        """Manually sets the group for a given image
        
        :param str file_name: file name of image
        :param str group: name of group to assign

        :meta public:
        """
        self.file_rows[file_name]["group_combo"].setCurrentIndex(self.known_groups.index(group))
