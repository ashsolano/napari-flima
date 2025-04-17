import os
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from math import ceil
from scipy import signal
from matplotlib.colors import CSS4_COLORS
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from napari.utils.colormaps import Colormap
from qtpy.QtCore import Qt, Signal, QRect
from qtpy.QtGui import (
    QClipboard, QPixmap, QColor, QStandardItem, QStandardItemModel,
    QPainter, QFont, QBrush, QIcon, QDoubleValidator
)
from qtpy.QtWidgets import (
    QApplication, QWidget, QDialog, QVBoxLayout, QHBoxLayout, QPushButton,
    QLineEdit, QCheckBox, QComboBox, QSpinBox, QDoubleSpinBox, QStyledItemDelegate,
    QStyle, QStyleOptionComboBox, QScrollArea, QSizePolicy, QGroupBox, QLabel,
    QTableWidget, QTableWidgetItem, QAbstractItemView, QHeaderView, QFormLayout,
    QGridLayout, QFileDialog, QSlider
)
from qtpy.QtCore import QTimer
from functools import partial


import imageio


# ---------------------------------------------------------------------------
# Supporting utils for cursor selection widget 

class ColorDelegate(QStyledItemDelegate):
    """This will create a colour selection drop-down menu with a thumbnail filled with the colour option and the colour name"""
    
    def __init__(self, parent=None):
        super(ColorDelegate, self).__init__(parent)

    def paint(self, painter, option, index):
        color = QColor(index.data(Qt.UserRole))  # Get the color data

        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())

        # Draw color thumbnail
        thumbnail_size = min(option.rect.height() - 4, 16)  # Limit thumbnail size to 16x16
        thumbnail_rect = QRect(option.rect.left() + 2, option.rect.top() + (option.rect.height() - thumbnail_size) // 2,
                               thumbnail_size, thumbnail_size)
        painter.fillRect(thumbnail_rect, color)

        # Draw color name
        name = index.data(Qt.DisplayRole)  # Get the color name
        painter.drawText(option.rect.adjusted(thumbnail_size + 4, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, name)

    def sizeHint(self, option, index):
        size = super(ColorDelegate, self).sizeHint(option, index)
        size.setHeight(max(size.height(), 20))  # Ensure the height is sufficient for the color thumbnail
        return size

class ColorSelectorApp(QComboBox):
    """This will allow for selection of the created colour drop down options based on the colour model generated"""
    def __init__(self, parent=None):
        super(ColorSelectorApp, self).__init__(parent)

        self.setModel(self.create_color_model())
        self.setItemDelegate(ColorDelegate(self))

        self.currentIndexChanged.connect(self.handle_selection)

    # Override paintEvent to show only color thumbnail for selected item
    def paintEvent(self, event):
        painter = QPainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        
        # Get color of the selected item
        color = QColor(self.currentData(Qt.UserRole))

        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, option.palette.highlight())

        # Draw only color thumbnail for selected item
        thumbnail_size = min(option.rect.height() - 4, 16)
        thumbnail_rect = QRect(option.rect.left() + (option.rect.width() - thumbnail_size) // 2,
                               option.rect.top() + (option.rect.height() - thumbnail_size) // 2,
                               thumbnail_size, thumbnail_size)
        painter.fillRect(thumbnail_rect, color)
        painter.drawRect(thumbnail_rect)

    # Override sizeHint to reduce the width of the combobox
    def sizeHint(self):
        size = super(ColorSelectorApp, self).sizeHint()
        size.setWidth(24)  # Set a small width for the combobox
        return size

    # Create color model with all CSS4 colors, ordered by a color 
    def create_color_model(self):
        """This will create a colour model so that CSS4 colours are ordered by colour gradient"""
        
        model = QStandardItemModel(self)
        sorted_colors = sorted(CSS4_COLORS.items(), key=lambda item: QColor(item[1]).hue())  # Sort by hue for a gradient effect
        for color_name, color_value in sorted_colors:
            item = QStandardItem(color_name)
            item.setData(QColor(color_value), Qt.UserRole)  # Set color data
            model.appendRow(item)
        return model

    # Handle selection change event
    def handle_selection(self, index):
        color = QColor(self.itemData(index, Qt.UserRole))
        # print("Selected color:", color.name())
        # You can use the selected color here as needed

    def selectedColor(self):
        return QColor(self.currentData(Qt.UserRole))

    def selectedColorName(self):
        return self.currentText()



class NumericDelegate(QStyledItemDelegate):
    """A delegate that provides a narrow QLineEdit with a double validator for numeric columns."""
    def createEditor(self, parent, option, index):
        line_edit = QLineEdit(parent)
        # Accept up to 3 decimals, range [0.0 .. 999.999] (adjust as needed)
        validator = QDoubleValidator(0.0, 999.999, 3, parent)
        validator.setNotation(QDoubleValidator.StandardNotation)
        line_edit.setValidator(validator)
        line_edit.setAlignment(Qt.AlignCenter)
        # You can set a small fixed width if you like, or let the table column handle it
        return line_edit

    def setEditorData(self, editor, index):
        # The cell's data is a string or numeric
        text_value = index.model().data(index, Qt.EditRole)
        if text_value is None:
            text_value = "0.0"
        editor.setText(str(text_value))

    def setModelData(self, editor, model, index):
        # Commit the edited text back to the model
        text_value = editor.text()
        model.setData(index, text_value, Qt.EditRole)



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
    def __init__(self, parent=None, title="Cursor Analysis", font=None):
        super().__init__(title, parent)
        self.default_font = font or QFont("Arial", 12)
        self.setFont(self.default_font)
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

    def add_cursor_row(self):
        """Insert a new row with Active, Color, R, G, S, τₘ, τₚ, and Remove."""
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

# ---------------------------------------------------------------------------
# Supporting utils file selection table 

def clear_layout(layout):
    """Recursively clear all items from a layout."""
    if layout is not None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
            else:
                clear_layout(item.layout())
                
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
    """

    threshold_changed = Signal(str, int)  # (file_name, threshold_value)
    groups_updated = Signal(list)  # Signal to emit updated group list

    def __init__(self, parent=None, title="File Selection", font=None):
        super().__init__(title, parent)
        self.parent_widget = parent
        self.default_font = font if font else QFont("Arial", 12)
        self.setFont(self.default_font)

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

        main_layout.addStretch()

   
   
    
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
        self.group_line_edit.clear()

        

    def update_all_combos(self):
        """Refreshes the group combo box items in all file rows."""
        for row_info in self.file_rows.values():
            combo = row_info["group_combo"]
            current_text = combo.currentText()
            combo.clear()
            combo.addItems(self.known_groups)
            # Restore the previously selected text if still valid
            if current_text in self.known_groups:
                combo.setCurrentText(current_text)
                
    def get_group_list(self):
        """Return the current group list."""
        return self.known_groups

    def add_file(self, file_path, layer_data):
        """
        Adds a row for the given file. Layout: [checkbox | file_name | group_combo | threshold].
        Each has fixed width to align columns.
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
        file_label.setFont(self.default_font)
        file_label.setStyleSheet("color: #f8f8f2;")
        file_label.setFixedWidth(100)  # fixed for alignment
        row_layout.addWidget(file_label)

        # 3) Group combo
        group_combo = QComboBox()
        group_combo.setFont(self.default_font)
        group_combo.setEditable(False)
        group_combo.addItems(self.known_groups)
        group_combo.setFixedWidth(100)  # align combos
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

        # 4) Threshold slider + numeric label
        threshold_layout = QHBoxLayout()
        threshold_layout.setSpacing(2)
        threshold_widget = QWidget()
        threshold_widget.setLayout(threshold_layout)
        threshold_widget.setFixedWidth(200)  # ensure alignment across rows

        slider = QSlider(Qt.Horizontal)
        max_intensity = int(np.max(layer_data))
        slider.setMinimum(0)
        slider.setMaximum(max_intensity)
        slider.setValue(0)

        val_label = QLabel("0")
        val_label.setFixedWidth(30)
        val_label.setAlignment(Qt.AlignCenter)

        slider.valueChanged.connect(lambda val, fn=file_name: self.threshold_changed.emit(fn, val))
        slider.valueChanged.connect(lambda val: val_label.setText(str(val)))
        slider.sliderReleased.connect(lambda fn=file_name: self.parent_widget.slider_released(fn))


        threshold_layout.addWidget(slider)
        threshold_layout.addWidget(val_label)
        row_layout.addWidget(threshold_widget)

        # Add row_layout to the files_layout
        self.files_layout.addLayout(row_layout)

        # Store references
        self.file_rows[file_name] = {
            "checkbox": checkbox,
            "file_label": file_label,
            "group_combo": group_combo,
            "slider": slider,
            "val_label": val_label,
            "layer_data": layer_data
        }

    def remove_file(self, file_path):
        """
        Removes the row for the given file_path from the layout.
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

    def on_checkbox_state_changed(self, state, file_name):
        """If your main widget has on_checkbox_state_changed, call it."""
        if hasattr(self.parent_widget, "on_checkbox_state_changed"):
            self.parent_widget.on_checkbox_state_changed(state, file_name)
            
    
    def get_file_group_mapping(self):
        """
        Returns a dictionary mapping file names to the currently selected group.
        Example:
            { "file1.tif": "Condition 1", "file2.tif": "PLA2", ... }
        """
        mapping = {}
        for file_name, row_info in self.file_rows.items():
            # Assume each row_info has a "group_combo" widget.
            mapping[file_name] = row_info["group_combo"].currentText()
        return mapping


# ---------------------------------------------------------------------------
# Supporting utils for  phasor plot dialog 

class PlotCanvas(FigureCanvas):
    """Canvas supporting draggable cursors on a Matplotlib axis, with blitting for speed."""
    cursorReleased = Signal(int, float, float)  # (cursor_index, x, y)

    def __init__(self, fig, ax, parent=None):
        super().__init__(fig)
        self.setParent(parent)
        self.ax = ax

        # enforce white figure/axes background
        matplotlib.rcParams.update({
            'figure.facecolor': "white",
            'axes.facecolor':   "white",
            'axes.edgecolor':   '#000000',
            'xtick.color':      '#000000',
            'ytick.color':      '#000000',
            'text.color':       '#000000',
            'axes.labelcolor':  '#000000',
        })

        self.draggable_cursors = []
        self.selected_cursor = None
        self.offset = (0,0)
        self.background = None

        # Connect mouse events
        self.mpl_connect('button_press_event',   self.on_press)
        self.mpl_connect('motion_notify_event',  self.on_motion)
        self.mpl_connect('button_release_event', self.on_release)

        # Initial draw of the universal circle (no scatter yet)
        self.plot_universal_circle()
        self.background = self.copy_from_bbox(self.ax.bbox)

    def add_draggable_cursor(self, x, y, radius, color='blue'):
        circle = plt.Circle((x, y), radius,
                            edgecolor=color, facecolor='none',
                            lw=2, zorder=10)
        self.ax.add_patch(circle)
        self.draggable_cursors.append(circle)
        # after adding, do a full redraw & recache background:
        self.draw()
        self.background = self.copy_from_bbox(self.ax.bbox)

    def remove_draggable_cursor(self, idx):
        if 0 <= idx < len(self.draggable_cursors):
            circle = self.draggable_cursors.pop(idx)
            circle.remove()
            # full redraw & recache background:
            self.draw()
            self.background = self.copy_from_bbox(self.ax.bbox)

    def on_press(self, event):
        if event.inaxes:
            for cursor in self.draggable_cursors:
                contains, _ = cursor.contains(event)
                if contains:
                    self.selected_cursor = cursor
                    # cache fresh background (without the cursor drawn)
                    self.background = self.copy_from_bbox(self.ax.bbox)
                    x0, y0 = cursor.center
                    self.offset = (x0 - event.xdata, y0 - event.ydata)
                    break

    def on_motion(self, event):
        if self.selected_cursor is None or event.inaxes is None:
            return

        # compute new center
        x, y = event.xdata + self.offset[0], event.ydata + self.offset[1]
        self.selected_cursor.center = (x, y)

        # blit workflow
        self.restore_region(self.background)           # restore background
        self.ax.draw_artist(self.selected_cursor)      # draw only the moving cursor
        self.blit(self.ax.bbox)                        # blit only the axes area

    def on_release(self, event):
        if self.selected_cursor is not None:
            x, y = self.selected_cursor.center
            idx = self.draggable_cursors.index(self.selected_cursor)
            self.cursorReleased.emit(idx, x, y)
            self.selected_cursor = None

            # final full draw to re‑render everything cleanly
            self.draw()
            self.background = self.copy_from_bbox(self.ax.bbox)

    def plot_universal_circle(self):
        self.ax.clear()
        self.ax.set_aspect('equal', adjustable='box')
        theta = np.linspace(0, 2*np.pi, 200)
        xunit = 0.5 + 0.5 * np.cos(theta)
        yunit = 0.5 * np.sin(theta)
        self.ax.plot(xunit, yunit, color="#888888", linewidth=1.2)
        self.ax.set_xlim(0, 1); self.ax.set_ylim(0, 1)
        self.ax.set_xticks([0, 0.5, 1]); self.ax.set_yticks([0, 0.5, 1])
        self.ax.set_xlabel("S", fontsize=9, color="black")
        self.ax.set_ylabel("G", fontsize=9, color="black")
        self.ax.tick_params(axis='both', labelsize=8, direction='in', colors="black")
        for spine in self.ax.spines.values():
            spine.set_color("black"); spine.set_linewidth(1.5)
        self.draw()
        self.background = self.copy_from_bbox(self.ax.bbox)
        

# ---------------------------------------------------------------------------
# main phasor plot dialog 

class PhasorPlotDialog(QDialog):
    """
    A pop-up dialog for phasor analysis:
      - Dark dialog background, white plot background with black border.
      - Slider & spin boxes for frame navigation + group size.
      - Save, Copy, Clear buttons in a blue style.
      - Draggable cursors preserved when switching frames.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Phasor Distribution")

      
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

        self.setFont(QFont("Arial", 10))

        # List of frames (g_array, s_array)
        self.frames = []
        self.current_group = 0
        self.group_size = 1

        # Create figure and axis with white background
        self.fig, self.ax = plt.subplots(figsize=(4, 4), dpi=100)
        self.fig.patch.set_facecolor("white")
        self.ax.set_facecolor("white")
        self.plot_canvas = PlotCanvas(self.fig, self.ax, self)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(8)
        main_layout.setContentsMargins(5, 5, 5, 5)

        # (A) Navigation banner
        nav_layout = QHBoxLayout()
        nav_layout.setSpacing(10)

        frame_label = QLabel("Frame Group:")
        frame_label.setFont(QFont("Arial", 12))
        nav_layout.addWidget(frame_label)

        self.frame_slider = QSlider(Qt.Horizontal)
        self.frame_slider.setMinimum(1)
        self.frame_slider.setMaximum(1)
        self.frame_slider.setValue(1)
        self.frame_slider.valueChanged.connect(self.on_slider_changed)
        nav_layout.addWidget(self.frame_slider)

        # Style the slider handle to be bigger/brighter
        self.frame_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                background: #444444;
                height: 6px;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                background: #f8f8f2;  /* Light handle to contrast the dark groove */
                border: 1px solid #007acc;
                width: 16px;  /* Increase handle width for visibility */
                margin: -5px 0;
                border-radius: 8px;
            }
            QSlider::sub-page:horizontal {
                background: #007acc; /* the filled portion to the left of handle */
            }
            QSlider::add-page:horizontal {
                background: #333333; /* the portion to the right of handle */
            }
        """)

        self.frame_spin = QSpinBox()
        self.frame_spin.setMinimum(1)
        self.frame_spin.setMaximum(50)
        self.frame_spin.setValue(1)
        self.frame_spin.valueChanged.connect(self.on_spin_changed)
        nav_layout.addWidget(self.frame_spin)

        group_label = QLabel("Group Size:")
        group_label.setFont(QFont("Arial", 12))
        nav_layout.addWidget(group_label)

        self.group_spin = QSpinBox()
        self.group_spin.setMinimum(1)
        self.group_spin.setMaximum(50)
        self.group_spin.setValue(1)
        self.group_spin.setFixedWidth(60)
        self.group_spin.valueChanged.connect(self.on_group_size_changed)
        nav_layout.addWidget(self.group_spin)

        main_layout.addLayout(nav_layout)
        
        # (A2) Median Filter controls: kernel size, iterations, Apply and Reset buttons.
        median_layout = QHBoxLayout()
        median_layout.setSpacing(10)

        kernel_label = QLabel("Kernel Size:")
        kernel_label.setFont(QFont("Arial", 12))
        median_layout.addWidget(kernel_label)

        self.kernel_spin = QSpinBox()
        self.kernel_spin.setMinimum(1)
        self.kernel_spin.setMaximum(15)
        self.kernel_spin.setValue(3)  # default kernel size (odd numbers work best)
        median_layout.addWidget(self.kernel_spin)

        iter_label = QLabel("Iterations:")
        iter_label.setFont(QFont("Arial", 12))
        median_layout.addWidget(iter_label)

        self.iter_spin = QSpinBox()
        self.iter_spin.setMinimum(1)
        self.iter_spin.setMaximum(10)
        self.iter_spin.setValue(1)  # default: no repeated filtering
        median_layout.addWidget(self.iter_spin)

        self.apply_filter_button = QPushButton("Apply Filter")
        self.apply_filter_button.setFont(QFont("Arial", 12))
        self.apply_filter_button.setStyleSheet("""
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
        #self.apply_filter_button.clicked.connect(self.apply_median_filter)
        median_layout.addWidget(self.apply_filter_button)

        self.reset_filter_button = QPushButton("Reset Filter")
        self.reset_filter_button.setFont(QFont("Arial", 12))
        self.reset_filter_button.setStyleSheet("""
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
        #self.reset_filter_button.clicked.connect(self.reset_filter)
        median_layout.addWidget(self.reset_filter_button)

        main_layout.addLayout(median_layout)

        # (B) Plot canvas
        main_layout.addWidget(self.plot_canvas)

        # (C) Button row: Save, Copy, Clear.
        btn_layout = QHBoxLayout()
        self.save_button = QPushButton(" Save")
        self.save_button.setIcon(QIcon("save_icon.png"))
        self.save_button.setStyleSheet("""
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
        self.save_button.clicked.connect(self.save_plot)
        btn_layout.addWidget(self.save_button)

        self.copy_button = QPushButton(" Copy")
        self.copy_button.setStyleSheet("""
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
        self.copy_button.clicked.connect(self.copy_plot)
        btn_layout.addWidget(self.copy_button)

        self.clear_button = QPushButton(" Clear")
        self.clear_button.setStyleSheet("""
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
        self.clear_button.clicked.connect(self.clear_g_s_coordinates)
        btn_layout.addWidget(self.clear_button)

        main_layout.addLayout(btn_layout)
        self.setLayout(main_layout)

        self.setFixedSize(500, 600)
        self.plot_universal_circle()

        
    def update_frame_navigation(self):
        total_frames = len(self.frames)
        total_groups = ceil(total_frames / self.group_size) if total_frames > 0 else 1
        if self.current_group >= total_groups:
            self.current_group = total_groups - 1
        self.frame_slider.blockSignals(True)
        self.frame_spin.blockSignals(True)
        self.frame_slider.setMaximum(total_groups)
        self.frame_spin.setMaximum(total_groups)
        self.frame_slider.setValue(self.current_group + 1)
        self.frame_spin.setValue(self.current_group + 1)
        self.frame_slider.blockSignals(False)
        self.frame_spin.blockSignals(False)

    def on_slider_changed(self, value):
        
        self.current_group = value - 1
        self.frame_spin.blockSignals(True)
        self.frame_spin.setValue(value)
        self.frame_spin.blockSignals(False)
        self.plot_current_group()

    def on_spin_changed(self, value):
        self.current_group = value - 1
        self.frame_slider.blockSignals(True)
        self.frame_slider.setValue(value)
        self.frame_slider.blockSignals(False)
        self.plot_current_group()

    def on_group_size_changed(self, value):
        self.group_size = value
        self.update_frame_navigation()
        self.plot_current_group()

    def add_frame(self, g_array, s_array):
        self.frames.append((g_array, s_array))
        self.update_frame_navigation()

    def plot_current_group(self):
        total_frames = len(self.frames)
        if total_frames == 0:
            self.plot_universal_circle()
            return
        start = self.current_group * self.group_size
        end = min(start + self.group_size, total_frames)
        g_list = [frame[0].flatten() for frame in self.frames[start:end]]
        s_list = [frame[1].flatten() for frame in self.frames[start:end]]
        if not g_list or not s_list:
            self.plot_universal_circle()
            return
        g_concat = np.concatenate(g_list)
        s_concat = np.concatenate(s_list)
        self.plot_g_s_coordinates(g_concat, s_concat)

    def plot_universal_circle(self):
        saved_cursors = self.plot_canvas.draggable_cursors.copy()
        self.ax.clear()
        self.ax.set_aspect('equal', adjustable='box')
        theta = np.linspace(0, 2*np.pi, 200)
        xunit = 0.5 + 0.5 * np.cos(theta)
        yunit = 0.5 * np.sin(theta)
        self.ax.plot(xunit, yunit, color="#888888", linewidth=1.2)
        self.ax.set_xlim(0, 1)
        self.ax.set_ylim(0, 1)
        self.ax.set_xticks([0, 0.5, 1])
        self.ax.set_yticks([0, 0.5, 1])
        self.ax.set_xlabel("G", fontsize=9, color="black")
        self.ax.set_ylabel("S", fontsize=9, color="black")
        self.ax.tick_params(axis='both', labelsize=8, direction='in', colors="black")
        # Black border
        for spine in self.ax.spines.values():
            spine.set_color("black")
            spine.set_linewidth(1.5)
        # Re-add cursors
        for c in saved_cursors:
            self.ax.add_patch(c)
        self.plot_canvas.draggable_cursors = saved_cursors
        self.plot_canvas.draw()

    def plot_g_s_coordinates(self, g, s):
        try:
            saved_cursors = self.plot_canvas.draggable_cursors.copy()
            g = g[g != 0]
            s = s[s != 0]
            bins = 300
            heatmap, xedges, yedges = np.histogram2d(g, s, bins=bins)
            xidx = np.clip(np.digitize(g, xedges), 0, bins-1)
            yidx = np.clip(np.digitize(s, yedges), 0, bins-1)
            c = heatmap[xidx, yidx]
            sorted_idx = np.argsort(c)
            g_sorted = g[sorted_idx]
            s_sorted = s[sorted_idx]
            c_sorted = c[sorted_idx]
            self.ax.clear()
            self.plot_universal_circle()  # re-add cursors
            self.ax.scatter(g_sorted, s_sorted, c=c_sorted, cmap='jet', s=0.3, alpha=1.0)
            for cpatch in saved_cursors:
                self.ax.add_patch(cpatch)
            self.plot_canvas.draggable_cursors = saved_cursors
            self.plot_canvas.draw()
        except Exception as e:
            print(f"Error plotting G/S coords: {e}")

    def clear_g_s_coordinates(self):
        """Clears data points from the phasor distribution plot."""
        self.ax.clear()
        self.plot_universal_circle()
        self.plot_canvas.draw()
     #  self.plot_universal_circle()
     #  self.plot_canvas.draw()

    def add_cursor(self, x, y, radius=0.03, color='blue'):
        self.plot_canvas.add_draggable_cursor(x, y, radius, color=color)
        self.plot_canvas.cursorReleased.connect(self.on_cursor_released)

    def on_cursor_released(self, idx, x, y):
        print(f"Cursor {idx} released at (S={x:.3f}, G={y:.3f})")

    def remove_cursor(self, idx):
        self.plot_canvas.remove_draggable_cursor(idx)

    def save_plot(self):
        file_path, _ = QFileDialog.getSaveFileName(self, "Save Plot", "", "PNG (*.png);;JPEG (*.jpg *.jpeg)")
        if file_path:
            orig_fc = self.fig.get_facecolor()
            self.fig.patch.set_facecolor('white')
            self.fig.savefig(file_path, facecolor='white', edgecolor='white')
            self.fig.patch.set_facecolor(orig_fc)

    def copy_plot(self):
        clipboard = QApplication.clipboard()
        pixmap = self.plot_canvas.grab()
        clipboard.setPixmap(pixmap)
    
    
    # def save_all_phasor_frames(self, output_dir):
    #     """
    #     Save all phasor frames to the specified output directory using imageio.
    #     This method iterates over each frame, updates the plot,
    #     converts the canvas to a NumPy array, and writes it as a PNG.
    #     """
        
    #     os.makedirs(output_dir, exist_ok=True)
        
    #     # Save the original facecolor so we can restore it later.
    #     orig_fc = self.fig.get_facecolor()
    #     self.fig.patch.set_facecolor('white')
        
    #     total_frames = len(self.frames)  # Adjust if your frame storage is different.
        
    #     for idx in range(total_frames):
    #         # Set the current frame.
    #         self.current_group = idx
    #         self.plot_current_group()  # Update the plot to show frame idx.
    #         self.fig.canvas.draw()     # Force a redraw of the canvas.
            
    #         # Get the current canvas size (display size).
    #         width, height = self.fig.canvas.get_width_height()
    #         # Get the raw RGB string from the canvas.
    #         raw = self.fig.canvas.tostring_rgb()
    #         img_array = np.frombuffer(raw, dtype=np.uint8)
            
    #         # Determine the scale factor by comparing the expected size (width*height*3)
    #         # with the buffer length.
    #         expected_size = width * height * 3
    #         scale = int(np.sqrt(len(img_array) / expected_size))
    #         if scale < 1:
    #             scale = 1
    #         new_height = height * scale
    #         new_width = width * scale
            
    #         try:
    #             img_array = img_array.reshape((new_height, new_width, 3))
    #         except Exception as e:
    #             print(f"Error reshaping image array at frame {idx}: {e}")
    #             continue
            
    #         # Construct the file path and save the image.
    #         file_path = os.path.join(output_dir, f"phasor_{idx}.png")
    #         imageio.imwrite(file_path, img_array)
    #         #print(f"Saved phasor frame {idx} to {file_path}")
        
    #     # Restore the original facecolor.
    #     self.fig.patch.set_facecolor(orig_fc)
    
    def save_all_phasor_frames(self, output_dir):
        """
        Save all phasor frames to the specified output directory using imageio.
        This method iterates over each frame, updates the plot,
        converts the canvas to a NumPy array, and writes it as a PNG.
        """

        os.makedirs(output_dir, exist_ok=True)

        # Save the original facecolor so we can restore it later.
        orig_fc = self.fig.get_facecolor()
        self.fig.patch.set_facecolor('white')

        total_frames = len(self.frames)

        for idx in range(total_frames):
            # 1) Set the current frame and redraw
            self.current_group = idx
            self.plot_current_group()
            self.fig.canvas.draw()

            # 2) Grab the RGBA buffer directly from the Agg renderer
            #    This returns an (H, W, 4) uint8 array.
            rgba = self.fig.canvas.renderer.buffer_rgba()
            img_array = np.asarray(rgba)

            # 3) Write out the frame
            file_path = os.path.join(output_dir, f"phasor_{idx}.png")
            imageio.imwrite(file_path, img_array)

        # Restore the original facecolor.
        self.fig.patch.set_facecolor(orig_fc)




#------------------------------------------------------------------------------
# Main PhasorWidget that integrates these components.

class PhasorWidget(QWidget):
    """This widget will prompt user input related to FLIM acquisition parameters, then generate phasor distribution for each pixel
    in an image, thresholding and median filter smoothing, and the cursor analysis to generate pseudocolored maps"""
    
    def __init__(self, viewer, dialog, intro_params, parent=None):
        super().__init__()

        
        
        self.viewer = viewer
        self.dialog = dialog
        self.intro_params = intro_params
        self.file_gs_data = {}
        self.smoothed_gs_data = {}
        self.median_filter_applied = False
        self.current_file = None
        self.file_order = []
        self.highlighted_pixels = None  # Initialize here
        
        # NEW: dictionaries to store persistent layers
        self.lifetime_layers = {}          # key: file_name, value: lifetime layer (tau_av)
        self.cursor_mask_layers = {}       # key: file_name, value: cursor mask layer
        
        
        
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        
        # --- File Selection Section ---
        self.file_selection_widget = FileSelectionTable(self, title="File Selection")
        self.file_selection_widget.threshold_changed.connect(self.update_threshold)
        layout.addWidget(self.file_selection_widget)
        
    
        
        # --- Cursor Analysis Section ---
        self.cursor_analysis_widget = CursorAnalysisWidget(self, title="Cursor Analysis", font=self.font())
        layout.addWidget(self.cursor_analysis_widget)
        

        
        # --- Button to Open Phasor Plot Dialog ---
        open_dialog_btn = QPushButton("Open Phasor Plot")
        open_dialog_btn.setFont(QFont("Arial", 12))
        open_dialog_btn.setStyleSheet("background-color: #007acc; color: white; padding: 8px; border-radius: 4px;")
        open_dialog_btn.clicked.connect(self.open_phasor_plot_dialog)
        layout.addWidget(open_dialog_btn)
        
        
        layout.addStretch()
        self.setLayout(layout)

        # Connect to Napari viewer events
        self.viewer.layers.events.inserted.connect(self.on_layer_added)
        self.viewer.layers.events.removed.connect(self.on_layer_removed)
        
        self.g_s_inputs = []
        # Connect the cursorReleased signal to the update_g_s_values method
        self.dialog.plot_canvas.cursorReleased.connect(self.update_g_s_values)
        
        
        # Connect the median filter buttons in the dialog to the main widget's filtering functions.
        self.dialog.apply_filter_button.clicked.connect(self.apply_median_filter)
        self.dialog.reset_filter_button.clicked.connect(self.reset_filter)
        
 
    
    def on_layer_added(self, event):
        layer = event.value
        if hasattr(layer, 'source') and layer.source.path:
            file_path = layer.source.path
            
            # Let the FileSelection widget track the file
            self.file_selection_widget.add_file(file_path, layer.data)
            
            # Keep a consistent file_order
            if file_path not in self.file_order:
                self.file_order.append(file_path)
            
            # If grid view is enabled, assign a grid cell to the new image layer.
            if self.viewer.grid.enabled:
                try:
                    idx = self.file_order.index(file_path)
                except ValueError:
                    idx = 0
                layer.metadata = layer.metadata or {}
                layer.metadata['grid'] = (0, idx)  # e.g., row 0, column = index


    def on_layer_removed(self, event):
        layer = event.value
        if hasattr(layer, 'source') and layer.source.path:
            file_path = layer.source.path
            self.file_selection_widget.remove_file(file_path)

    def update_threshold(self, file_name, threshold_value):
        self.update_image_layer(file_name, threshold_value)
    
    
            
   
    
    def update_image_layer(self, file_name, threshold):
        """
        Applies threshold to the intensity channel of file_name's image,
        and creates/updates a red overlay named <file_name>_mask.
        If grid is enabled, the overlay is placed in the same cell as the image.
        If grid is disabled, the image and overlay are moved to the top of the layer list.
        """
        channel_map = self.intro_params.get("channel_assignments", [])
        flim_type = self.intro_params.get("flim_type", "FD FLIM")
        intensity_idx = channel_map.index("Intensity") if "Intensity" in channel_map else 0
        #print("Channel assignments:", channel_map)
        #print("FLIM type:", flim_type)
        #print("Intensity channel index:", intensity_idx)
    
        # 1) Find the matching image layer
        image_layer = None
        for layer in self.viewer.layers:
            if (
                hasattr(layer, "source")
                and layer.source.path is not None
                and os.path.basename(layer.source.path) == file_name
            ):
                image_layer = layer
                break
    
        if image_layer is None:
            print(f"No matching image layer found for {file_name}.")
            return
    
        # 2) Retrieve data & checkbox state
        original_data = self.file_selection_widget.file_rows[file_name]["layer_data"]
        checkbox_checked = self.file_selection_widget.file_rows[file_name]["checkbox"].isChecked()
        mask_layer_name = file_name + "_mask"
    
        # 3) FD FLIM vs TCSPC FLIM thresholding
        if flim_type == "FD FLIM":
            # shape: [channels, height, width]
            intensity_image = original_data[intensity_idx, :, :].copy()
            mask = intensity_image < threshold
            #print("Mask shape (FD FLIM):", mask.shape)
    
            if not checkbox_checked:
                rgba_mask = np.zeros((mask.shape[0], mask.shape[1], 4), dtype=np.uint8)
                rgba_mask[mask, 0] = 255  # Red
                rgba_mask[mask, 3] = 128  # Semi-transparent
                if mask.sum() > 0:
                    overlay = self._create_or_update_overlay(mask_layer_name, rgba_mask)
                else:
                    self.remove_overlay(mask_layer_name)
            else:
                self.remove_overlay(mask_layer_name)
    
            # Apply threshold
            intensity_image[mask] = 0
            updated_data = original_data.copy()
            updated_data[intensity_idx, :, :] = intensity_image
            self.intensity = intensity_image.copy()
    
        else:
            # TCSPC FLIM: [time, channels, height, width]
            intensity_image = original_data[:, intensity_idx, :, :].copy()
            mask = intensity_image < threshold  # shape: (num_frames, height, width)
            #print("Mask shape (TCSPC FLIM):", mask.shape)
    
            if not checkbox_checked:
                # Only show red overlay for the first frame
                rgba_mask = np.zeros((mask.shape[1], mask.shape[2], 4), dtype=np.uint8)
                rgba_mask[mask[0], 0] = 255
                rgba_mask[mask[0], 3] = 128
                if mask[0].sum() > 0:
                    overlay = self._create_or_update_overlay(mask_layer_name, rgba_mask)
                else:
                    self.remove_overlay(mask_layer_name)
            else:
                self.remove_overlay(mask_layer_name)
    
            # Apply threshold
            intensity_image[mask] = 0
            updated_data = original_data.copy()
            updated_data[:, intensity_idx, :, :] = intensity_image
            self.intensity = intensity_image.copy()
    
        # 4) Update the image layer
        image_layer.data = updated_data
        image_layer.refresh()
        self.current_mask = mask
    
        # 5) If the overlay exists, position it either in the same grid cell or stacked on top
        if mask_layer_name in self.viewer.layers:
            overlay_layer = self.viewer.layers[mask_layer_name]
            if self.viewer.grid.enabled:
                # Copy the image's grid metadata if it exists
                if hasattr(image_layer, "metadata") and "grid" in image_layer.metadata:
                    overlay_layer.metadata = overlay_layer.metadata or {}
                    overlay_layer.metadata["grid"] = image_layer.metadata["grid"]
                else:
                    # fallback: use file_order
                    try:
                        idx = self.file_order.index(file_name)
                    except ValueError:
                        idx = 0
                    overlay_layer.metadata = overlay_layer.metadata or {}
                    overlay_layer.metadata["grid"] = (0, idx)
            else:
                # Grid disabled: Move both the image layer & overlay to the top
                self._bring_to_top(image_layer, overlay_layer)
    
    def _create_or_update_overlay(self, layer_name, rgba_mask):
        """Helper to create or update an overlay layer with the given name."""
        if layer_name in self.viewer.layers:
            overlay = self.viewer.layers[layer_name]
            overlay.data = rgba_mask
        else:
            overlay = self.viewer.add_image(rgba_mask, name=layer_name, blending="additive")
        return overlay
    
    def _bring_to_top(self, image_layer, overlay_layer):
        """Helper to move the image & overlay so they're at the top of the layer list."""
        # Move image layer to the top
        img_idx = self.viewer.layers.index(image_layer)
        top_idx = len(self.viewer.layers) - 1
        if img_idx < top_idx:
            self.viewer.layers.move(img_idx, top_idx)
        # Move overlay layer to be above the image
        ov_idx = self.viewer.layers.index(overlay_layer)
        self.viewer.layers.move(ov_idx, len(self.viewer.layers) - 1)
    
    
    def remove_overlay(self, mask_layer_name):
        """Remove the red overlay layer if it exists."""
        if mask_layer_name in self.viewer.layers:
            self.viewer.layers.remove(self.viewer.layers[mask_layer_name])
    
   
    
    def slider_released(self, file_name):
        """Called when the slider is released; remove the red overlay for that file."""
        mask_layer_name = file_name + "_mask"
        QTimer.singleShot(0, lambda: self.remove_overlay(mask_layer_name))

    
   
    
    def on_checkbox_state_changed(self, state, file_name):
        """
        When a file's checkbox is toggled:
         - If checked: compute g/s coordinates, lifetimes, etc., and add this file's data 
           to self.file_gs_data so that replot_phasor() uses it; also update lifetime layer.
         - If unchecked: remove the file's entry from self.file_gs_data so that its g/s data
           no longer appear in the phasor plot. The lifetime layer and cursor mask layer remain 
           for later reference.
        """
        if state == Qt.Checked:
            threshold_value = self.file_selection_widget.file_rows[file_name]["slider"].value()
            self.update_threshold(file_name, threshold_value)
            layer_data = self.file_selection_widget.file_rows[file_name]["layer_data"]
    
            # Compute intensity, g, and s arrays.
            intensity, g_image, s_image = self.calculate_g_s_coordinates(
                layer_data,
                self.intro_params.get("laser_frequency", 0),
                self.intro_params.get("harmonic", 1),
                zero_indices=self.current_mask  # assuming update_threshold stored the mask here
            )
    
            # Compute lifetimes.
            #print("Begin computing lifetime values")
            tau_m, tau_p, tau_av = self.compute_lifetimes_from_gs(g_image, s_image)
            #print("Complete lifetime value calculations")
    
            # Apply threshold mask to the lifetime arrays as before...
            if self.current_mask is not None:
                try:
                    if tau_m.ndim == self.current_mask.ndim:
                        tau_m[self.current_mask] = np.nan
                        tau_p[self.current_mask] = np.nan
                        tau_av[self.current_mask] = np.nan
                    elif tau_m.ndim == 2 and self.current_mask.ndim == 3:
                        tau_m[0][self.current_mask[0]] = np.nan
                        tau_p[0][self.current_mask[0]] = np.nan
                        tau_av[0][self.current_mask[0]] = np.nan
                except Exception as e:
                    print("Error applying threshold mask to lifetime images:", e)
    
            # Store computed g/s (and lifetime) data for phasor plotting.
            self.file_gs_data[file_name] = {
                "intensity": intensity,
                "g_image": g_image,
                "s_image": s_image,
                "tau_av": tau_av  # for display if needed
            }
            self.intensity = intensity
            self.g = g_image
            self.s = s_image
    
            # Update or add the lifetime layer.
            base_name = os.path.splitext(os.path.basename(file_name))[0]
            tau_av_layer_name = f"{base_name}_lifetime"
            try:
                min_tau_av = np.nanpercentile(tau_av, 1)
                max_tau_av = np.nanpercentile(tau_av, 99)
            except Exception as e:
                print("Error computing percentiles for tau_av:", e)
                min_tau_av, max_tau_av = np.nanmin(tau_av), np.nanmax(tau_av)
    
            # Prepare the data for display.
            if tau_av.ndim == 2:
                tau_av_disp = np.expand_dims(np.expand_dims(tau_av, axis=0), axis=0)
            elif tau_av.ndim == 3:
                tau_av_disp = np.expand_dims(tau_av, axis=1)
            else:
                tau_av_disp = tau_av
    
            if tau_av_layer_name in self.viewer.layers:
                layer = self.viewer.layers[tau_av_layer_name]
                layer.data = tau_av_disp
            else:
                layer = self.viewer.add_image(
                    tau_av_disp,
                    name=tau_av_layer_name,
                    colormap="turbo",
                    contrast_limits=(min_tau_av, max_tau_av)
                )
    
            # 1) Hide the lifetime layer by default
            layer.visible = False
    
            # 2) Move the lifetime layer so it sits just above the base image
            base_idx = None
            for i, lay in enumerate(self.viewer.layers):
                if (hasattr(lay, "source") and lay.source.path is not None
                    and os.path.basename(lay.source.path) == os.path.basename(file_name)):
                    base_idx = i
                    break
    
            if base_idx is not None:
                lifetime_idx = self.viewer.layers.index(layer)
                # If the lifetime layer is below the base image, move it above
                if lifetime_idx < base_idx:
                    self.viewer.layers.move(lifetime_idx, base_idx + 1)
    
            # Keep the lifetime layer permanently (store it if needed).
            self.lifetime_layers[file_name] = layer
    
            # Set the current file to this file.
            self.current_file = file_name
    
        else:
            # If unchecked, remove this file's g/s data from phasor plotting.
            if file_name in self.file_gs_data:
                del self.file_gs_data[file_name]
            # Also, if the current file is being unchecked, choose another file (if available)
            if self.current_file == file_name:
                if self.file_gs_data:
                    self.current_file = list(self.file_gs_data.keys())[0]
                else:
                    self.current_file = None
            # (Lifetime layer and cursor mask layer remain, so that analysis persists.)
            #print(f"File {file_name} unticked; lifetime layer and cursor mask are kept.")
    
        # Finally, replot the phasor using only the g/s data from checked files.
        self.replot_phasor()

    
    
    def replot_phasor(self):
        """
        Replot the phasor dialog by timepoint, overlaying every checked file.
        - If g_array is 3D (T×H×W): we get T pages.
        - If g_array is 2D: T = 1, so you get one page with all files.
        """
        # 1) clear old frames
        self.dialog.frames = []
    
        
        if not self.file_gs_data:
            print("No files selected for phasor plotting.")
            self.dialog.plot_universal_circle()
            return
    
        
        files = list(self.file_gs_data.keys())
        # pick the first file to infer T
        sample = self.file_gs_data[files[0]]
        data0 = (self.smoothed_gs_data[files[0]]
                 if self.median_filter_applied and files[0] in self.smoothed_gs_data
                 else sample)
        g0 = data0["g_image"]
        T = g0.shape[0] if g0.ndim == 3 else 1
    
        
        for t in range(T):
            for fname in files:
                raw = self.smoothed_gs_data[fname] if (self.median_filter_applied and fname in self.smoothed_gs_data) else self.file_gs_data[fname]
                g_arr = raw["g_image"]
                s_arr = raw["s_image"]
                if g_arr.ndim == 3:
                    self.dialog.add_frame(g_arr[t], s_arr[t])
                else:
                    # 2D data → only one frame, so add on t==0
                    if t == 0:
                        self.dialog.add_frame(g_arr, s_arr)
    
        # 5) force pages = T, with each page = len(files)
        self.dialog.group_size = len(files)
        # sync spinner to this
        self.dialog.group_spin.blockSignals(True)
        self.dialog.group_spin.setValue(len(files))
        self.dialog.group_spin.blockSignals(False)
    
        # 6) redraw
        self.dialog.update_frame_navigation()
        self.dialog.plot_current_group()
          


    def calculate_g_s_coordinates(self, image_data, laser_frequency, harmonic, zero_indices=None):
        """
        Calculate the G and S coordinates for phasor analysis using the channel assignments
        provided in the intro parameters.
        
        Expected intro parameters:
          - "flim_type": "FD FLIM" or "TCSPC FLIM"
          - "channel_assignments": a list of strings (e.g., 
              ['Intensity', 'None', 'None', 'None', 'G-values', 'S-values'])
        
        For FD FLIM, we assume the data shape is [channels, height, width].
        For TCSPC FLIM, we assume the data shape is [time, channels, height, width] and we take the first time point.
        """
        # Retrieve channel mapping and FLIM type from intro parameters.
        channel_map = self.intro_params.get("channel_assignments", [])
        flim_type = self.intro_params.get("flim_type", "FD FLIM")
        #print(flim_type)
        harmonic = self.intro_params.get("harmonic", 1)
        #print(harmonic)
        laser_frequency = self.intro_params.get("laser_frequency", 0)
        #print(laser_frequency)
        
        # Determine the index for the intensity channel.
        intensity_idx = channel_map.index("Intensity") if "Intensity" in channel_map else 0
        
        if flim_type == "FD FLIM":
            # FD FLIM: assume data shape is [channels, height, width]
            intensity = image_data[intensity_idx, :, :]
            
            # Determine phase and modulation indices.
            try:
                phase_idx = channel_map.index("Phase-values")
            except ValueError:
                phase_idx = 1  # fallback
            try:
                mod_idx = channel_map.index("Modulation-values")
            except ValueError:
                mod_idx = 2  # fallback
            
            # Optionally, if harmonic==2, you might have alternate channels.
            if harmonic == 2:
                try:
                    phase_idx = channel_map.index("Phase-values")
                except ValueError:
                    phase_idx = phase_idx  # leave as is
                try:
                    mod_idx = channel_map.index("Modulation-values")
                except ValueError:
                    mod_idx = mod_idx  # leave as is
            
            phase_array = image_data[phase_idx, :, :].copy()
            mod_array = image_data[mod_idx, :, :].copy()
            
            # Calculate G and S coordinates.
            g_image = mod_array * np.cos(np.pi / 180 * phase_array)
            s_image = mod_array * np.sin(np.pi / 180 * phase_array)
            
            self.original_g = g_image
            self.original_s = s_image
            
            if zero_indices is not None:
                g_image[zero_indices] = 0
                s_image[zero_indices] = 0
                
                
        elif flim_type == "TCSPC FLIM":
            # TCSPC FLIM: assume data shape is [time, channels, height, width]
            intensity = image_data[:, intensity_idx, :, :]
            
            # For TCSPC, get the G and S channels based on mapping.
            try:
                g_idx = channel_map.index("G-values")
            except ValueError:
                g_idx = 4  # default fallback
            try:
                s_idx = channel_map.index("S-values")
            except ValueError:
                s_idx = 5  # default fallback
            
            # Extract G and S channels from all time points.
            g_values = image_data[:, g_idx, :, :]
            s_values = image_data[:, s_idx, :, :]
            
            # Scale the values.
            g_values_m = (g_values - 32767.5) / 32767.5
            s_values_m = (s_values - 32767.5) / 32767.5
            
            self.original_g = g_values_m
            self.original_s = s_values_m
            
            if zero_indices is not None:
                g_values_m[zero_indices] = 0
                s_values_m[zero_indices] = 0
                
            # For visualization, take the first time point.
            g_image = g_values_m.copy()
            s_image = s_values_m.copy()
            
            #print("G image shape:", g_image.shape)
            #print("S image shape:", s_image.shape)
        
        return intensity, g_image, s_image
    
    
    
    def compute_lifetimes_from_gs(self, g_array, s_array):
        """
        Compute modulation (tau_m) and phase (tau_p) lifetimes from G and S arrays.
        Laser frequency (in MHz) is taken from the intro parameters.
        If the computed magnitude m is zero, tau_m is set to 0.
        """
        # Retrieve the laser frequency from the intro parameters (in MHz)
        laser_freq_mhz = self.intro_params.get("laser_frequency", 80.0)
        # Convert to Hz and compute angular frequency.
        w = 2.0 * np.pi * (laser_freq_mhz * 1e6)
    
        # Compute the magnitude m = sqrt(g^2 + s^2)
        m = np.sqrt(g_array**2 + s_array**2)
    
        # Compute tau_m using the new formula.
        # For elements where m > 0, compute sqrt(1/(m^2) - 1); otherwise use 0.
        
        # Suppress divide-by-zero and invalid value warnings.
        with np.errstate(divide='ignore', invalid='ignore'):
            tau_m = (1.0 / w) * np.sqrt(np.where(m > 0, (1.0 / (m ** 2)) - 1.0, 0.0))
        # Ensure tau_m is 0 where m == 0.
        tau_m = np.where(m > 0, tau_m, 0.0)
       
        #tau_m = (1.0 / w) * np.sqrt(np.where(m > 0, (1.0 / (m ** 2)) - 1.0, 0.0))
        # Ensure tau_m is 0 where m == 0.
        #tau_m = np.where(m > 0, tau_m, 0.0)
    
        # Compute phase (phi) and then tau_p.
        phi = np.arctan2(s_array, g_array)
        tau_p = (1.0 / w) * np.tan(phi)
        
        # Convert to nanoseconds
        tau_m = tau_m * 1e9
        tau_p = tau_p * 1e9
        
        # Get average lifetime
        tau_av = (tau_m + tau_p) / 2.0
    
        return tau_m, tau_p, tau_av

    def compute_lifetimes_from_point(self, g, s):
        """
        Compute tau_modulation (tau_m) and tau_phase (tau_p) from a single (g, s) coordinate.
        The modulation lifetime is computed as:
            tau_m = (1/w) * sqrt((1/m^2) - 1)
        where m = sqrt(g^2 + s^2) and w = 2*pi*(laser_frequency in Hz).
    
        The phase lifetime is computed as:
            tau_p = (1/w) * tan(phi)
        where phi = arctan2(s, g).
    
        Returns the lifetimes in seconds. Multiply by 1e9 to display in nanoseconds.
        """
        # Retrieve laser frequency from intro parameters (assumed to be in MHz)
        laser_frequency = self.intro_params.get("laser_frequency", 1)
        # Convert to Hz and compute angular frequency
        w = 2 * np.pi * (laser_frequency * 1e6)
    
        # Compute the modulation (m) from g and s.
        m = np.sqrt(g**2 + s**2)
    
        # Compute tau_m using the new formula. Avoid division by zero.
        if m > 0:
            tau_m = (1.0 / w) * np.sqrt((1.0 / (m ** 2)) - 1.0)
        else:
            tau_m = 0.0
    
        # Compute phase (phi) and then tau_p.
        phi = np.arctan2(s, g)
        tau_p = (1.0 / w) * np.tan(phi)
        
        # Convert to nanoseconds
        tau_m = tau_m * 1e9
        tau_p = tau_p * 1e9
    
        return tau_m, tau_p

    
    def apply_median_filter(self):
        #print("Applying median filter")
        nsmoothing = self.dialog.iter_spin.value()  # number of iterations

        if not self.file_gs_data:
            print("No file data available for filtering.")
            return

        # Ensure the smoothed data dictionary exists.
        if not hasattr(self, "smoothed_gs_data"):
            self.smoothed_gs_data = {}

        # Process each file's data.
        for file_name, data in self.file_gs_data.items():
            original_g = data["g_image"]
            original_s = data["s_image"]

            # Apply median filtering to each file.
            if original_g.ndim == 3:
                filtered_g = np.zeros_like(original_g)
                filtered_s = np.zeros_like(original_s)
                for i in range(original_g.shape[0]):
                    frame_g = original_g[i, :, :].copy()
                    frame_s = original_s[i, :, :].copy()
                    for _ in range(nsmoothing):
                        frame_g = signal.medfilt2d(frame_g, kernel_size=3)
                        frame_s = signal.medfilt2d(frame_s, kernel_size=3)
                    filtered_g[i] = frame_g
                    filtered_s[i] = frame_s
            elif original_g.ndim == 2:
                filtered_g = original_g.copy()
                filtered_s = original_s.copy()
                for _ in range(nsmoothing):
                    filtered_g = signal.medfilt2d(filtered_g, kernel_size=3)
                    filtered_s = signal.medfilt2d(filtered_s, kernel_size=3)
            else:
                print(f"Unsupported data shape for file: {file_name}")
                continue

            # Save the filtered results in the smoothed dictionary.
            self.smoothed_gs_data[file_name] = {
                "g_image": filtered_g.copy(),
                "s_image": filtered_s.copy()
                # Optionally, if you want to filter lifetime (tau_av), process here.
            }
    
        # Set a flag indicating that median filtering is active.
        self.median_filter_applied = True

        # Replot the phasor dialog using filtered data.
        self.replot_phasor()
        #print("Finished median filtering")

    

    
    def reset_filter(self):
        self.dialog.kernel_spin.setValue(3)
        self.dialog.iter_spin.setValue(1)
        self.median_filter_applied = False
        # Optionally, reset the smoothed data to match the original.
        if self.file_gs_data:
            self.smoothed_gs_data = {file_name: data.copy() for file_name, data in self.file_gs_data.items()}
        self.replot_phasor()

    
   
    def cursor_checkbox_state_changed(self, state, idx):
        """When a cursor row's checkbox is toggled, add or remove its draggable cursor."""
        # Retrieve the stored row data for this index.
        row_data = self.cursor_analysis_widget.cursor_rows_data[idx]
    
        if state == Qt.Checked:
            # Extract current values from the row's widgets.
            try:
                radius = float(row_data["col_2"].text())
                color = row_data["color_selector"].currentText()
                g = float(row_data["col_3"].text())
                s = float(row_data["col_4"].text())
            except Exception as e:
                print(f"Error retrieving cursor settings for row {idx}: {e}")
                return

            #print(f"Adding cursor: radius={radius}, color={color}, G={g}, S={s}")
            # Add the draggable cursor to the phasor dialog.
            self.dialog.add_cursor(g, s, radius, color)
        else:
            # Remove the cursor corresponding to this row.
            print(f"Removing cursor at index {idx}")
            self.dialog.remove_cursor(idx)
            
    
    def update_g_s_values(self, cursor_index, x, y):
        """Upon releasing the draggable cursor, update the corresponding G and S input values."""
        # Check if the cursor index is valid within our stored cursor rows.
        if cursor_index < len(self.cursor_analysis_widget.cursor_rows_data):
            row_data = self.cursor_analysis_widget.cursor_rows_data[cursor_index]
            # Assuming column 3 holds the G value and column 4 holds the S value:
            row_data["col_3"].setText(f"{x:.2f}")
            row_data["col_4"].setText(f"{y:.2f}")
           
            tau_mod, tau_phase = self.compute_lifetimes_from_point(x, y)
            #print("printing tau_mod and tau_phase values")
            #print(tau_mod)
            #print(tau_phase)
            
            row_data["col_5"].setText(f"{tau_mod:.2f}")
            row_data["col_6"].setText(f"{tau_phase:.2f}")
        
            self.update_pixels_within_cursor()
        else:
            print(f"Cursor index {cursor_index} is out of range.")

   
    #Add here to execute the phasor dialog
    def open_phasor_plot_dialog(self):
        """
        Open the PhasorPlotDialog pop-up.
        Optionally, before showing, you could pass frames or update settings.
        """
        # Make the phasor dialog modeless
        self.dialog.setWindowModality(Qt.NonModal)
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
        
    
    def update_pixels_within_cursor(self):
        """
        Computes and updates independent cursor mask layers for each active file.
        A single cursor selection event updates the cursor masks for all active files.
        Each file's cursor mask is then reordered to appear immediately above its base image.
        
        The final layer data is shaped similarly to your tau_av expansions:
          - If g_data is 2D (H, W), the layer becomes (1, 1, H, W, 4).
          - If g_data is 3D (T, H, W), the layer becomes (T, 1, H, W, 4).
        This aligns the time axis with the viewer, letting Napari handle multi-frame displays.
        """
        #print("Selecting pixels")
        
        # Ensure intensity data is available.
        if not hasattr(self, 'intensity') or self.intensity is None:
            print("Error: intensity data is not initialized.")
            return
    
        # Loop over each active file (checked) in self.file_gs_data.
        for file_name, file_data in self.file_gs_data.items():
            # Decide whether to use smoothed data or original data.
            if self.median_filter_applied and file_name in self.smoothed_gs_data:
                g_data = self.smoothed_gs_data[file_name]["g_image"]
                s_data = self.smoothed_gs_data[file_name]["s_image"]
            else:
                g_data = file_data["g_image"]
                s_data = file_data["s_image"]
    
            if g_data is None:
                print(f"No g data available for {file_name}.")
                continue
    
            # Create an RGBA array for highlighted pixels for this file.
            # If g_data is (T, H, W), we initially build (T, H, W, 4).
            # If g_data is (H, W), we build (H, W, 4).
            if g_data.ndim == 3:
                highlighted_pixels = np.zeros(g_data.shape + (4,), dtype=np.uint8)
            else:
                highlighted_pixels = np.zeros(g_data.shape + (4,), dtype=np.uint8)
            #print(f"For file {file_name}, highlighted_pixels shape: {highlighted_pixels.shape}")
    
            # Loop through each cursor row in the CursorAnalysisWidget.
            for row_data in self.cursor_analysis_widget.cursor_rows_data:
                if row_data["checkbox"].isChecked():
                    try:
                        radius = float(row_data["col_2"].text())
                        g_center = float(row_data["col_3"].text())
                        s_center = float(row_data["col_4"].text())
                        cursor_color = row_data["color_selector"].currentText()
                    except Exception as e:
                        print(f"Error retrieving cursor settings for {file_name}: {e}")
                        continue
    
                    #print(f"Cursor settings for {file_name} - "
                          #f"Radius: {radius}, G: {g_center}, S: {s_center}, Color: {cursor_color}")
                    rgb = QColor(cursor_color).getRgb()[:3]
                    #print(f"RGB: {rgb}")
    
                    # Compute mask for each time frame if multi-frame, else for 2D.
                    if g_data.ndim == 3:
                        for t in range(g_data.shape[0]):
                            distance = np.hypot(g_data[t] - g_center, s_data[t] - s_center)
                            mask = distance <= radius
                            highlighted_pixels[t][mask] = rgb + (255,)
                    else:
                        distance = np.hypot(g_data - g_center, s_data - s_center)
                        mask = distance <= radius
                        highlighted_pixels[mask] = rgb + (255,)
                    #print(f"Finished updating highlighted pixels for {file_name} for this cursor.")
    
            # Save computed highlighted pixels in a dictionary for potential reuse.
            if not hasattr(self, 'highlighted_pixels_dict'):
                self.highlighted_pixels_dict = {}
            self.highlighted_pixels_dict[file_name] = highlighted_pixels
    
            # --- Prepare data for display so that the time axis aligns properly ---
            # If highlighted_pixels is 2D (H, W, 4), we expand to (1, 1, H, W, 4).
            # If it's 3D (T, H, W, 4), we expand to (T, 1, H, W, 4).
            # This mirrors your tau_av expansions.
            if g_data.ndim == 2:
                # Means highlighted_pixels is (H, W, 4).
                layer_data = np.expand_dims(np.expand_dims(highlighted_pixels, axis=0), axis=0)
            elif g_data.ndim == 3:
                # Means highlighted_pixels is (T, H, W, 4).
                layer_data = np.expand_dims(highlighted_pixels, axis=1)
            else:
                layer_data = highlighted_pixels
    
            # Determine the cursor mask layer name (using base file name).
            base_name = os.path.splitext(os.path.basename(file_name))[0]
            cursor_layer_name = f"{base_name}_cursor_mask"
    
            # Update or add the cursor mask layer for this file.
            if cursor_layer_name in self.viewer.layers:
                #print(f"Updating existing '{cursor_layer_name}' layer for {file_name}.")
                self.viewer.layers[cursor_layer_name].data = layer_data
            else:
                #print(f"Adding new '{cursor_layer_name}' layer for {file_name}.")
                new_layer = self.viewer.add_image(
                    layer_data,
                    name=cursor_layer_name,
                    colormap=None
                )
                self.cursor_mask_layers[file_name] = new_layer
    
            # Reorder the cursor mask layer so it is immediately above its corresponding image.
            self._order_cursor_mask_above_image(file_name)
    
    
    
    def _order_cursor_mask_above_image(self, file_name):
        """
        Moves the cursor mask layer for file_name so that it appears immediately above
        its corresponding image layer.
        """
        import os
        base_name = os.path.splitext(os.path.basename(file_name))[0]
        cursor_layer_name = f"{base_name}_cursor_mask"
        
        image_layer = None
        for layer in self.viewer.layers:
            if (hasattr(layer, "source") and layer.source.path is not None and 
                os.path.splitext(os.path.basename(layer.source.path))[0] == base_name):
                image_layer = layer
                break
        if image_layer is None:
            print(f"No base image found for ordering for {file_name}.")
            return
        if cursor_layer_name not in self.viewer.layers:
            print(f"No cursor mask layer found for ordering for {file_name}.")
            return
    
        image_index = self.viewer.layers.index(image_layer)
        cursor_layer = self.viewer.layers[cursor_layer_name]
        cursor_index = self.viewer.layers.index(cursor_layer)
        # If the cursor mask is not immediately above the image, move it to image_index + 1.
        if cursor_index != image_index + 1:
            self.viewer.layers.move(cursor_index, image_index + 1)
    
    # def get_analysis_data(self):
    #     """Return a dictionary with all the analysis data needed by segmentation."""
    #     return {
    #         "file_gs_data": self.file_gs_data,
    #         "smoothed_gs_data": self.smoothed_gs_data,
    #         "median_filter_applied": self.median_filter_applied,
    #         "current_file": self.current_file,
    #         "file_order": self.file_order,
    #         "highlighted_pixels": self.highlighted_pixels,
    #         "lifetime_layers": self.lifetime_layers,
    #         "cursor_mask_layers": self.cursor_mask_layers,
    #         "cursor_settings": self.cursor_analysis_widget.get_cursor_settings()
    #     }
    
    def get_analysis_data(self):
        """Return a dictionary with all the analysis data needed by segmentation."""
        data = {
            "file_gs_data": self.file_gs_data,
            "smoothed_gs_data": self.smoothed_gs_data,
            "median_filter_applied": self.median_filter_applied,
            "current_file": self.current_file,
            "file_order": self.file_order,
            "highlighted_pixels": self.highlighted_pixels,
            "lifetime_layers": self.lifetime_layers,
            "cursor_mask_layers": self.cursor_mask_layers,
            "cursor_settings": self.cursor_analysis_widget.get_cursor_settings()
        }
        # Add the group list from the file selection widget (assuming it's stored there)
        if hasattr(self, "file_selection_widget"):
            data["group_list"] = self.file_selection_widget.get_group_list()
            # Also add the file mapping, which is a dict of file_name -> group name.
            data["file_group_mapping"] = self.file_selection_widget.get_file_group_mapping()
        return data

    
                    
            
            
                    
                
                    
                
            
                
                        