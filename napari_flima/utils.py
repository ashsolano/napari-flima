"""
Utility classes and functions for FLIMa
"""

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
from functools import partial


import imageio

# ---------------------------------------------------------------------------
# Supporting utils file selection table 

def clear_layout(layout):
    """Recursively clear all items from a layout.
    
    :param layout: layout to clear"""
    if layout is not None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
            else:
                clear_layout(item.layout())

# ---------------------------------------------------------------------------
# Supporting utils for  phasor plot dialog 


class PlotCanvas(FigureCanvas):
    """Canvas class supporting draggable cursors on a Matplotlib axis, with blitting for speed.
    
    :signal cursorReleased: emits when a draggable cursor is released
        (cursor_index -> int, x -> float, y -> float)
        
    """
    cursorReleased = Signal(int, float, float)

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
        """
        Adds a draggable cursor to the canvas
        
        :param int x: x coordinate of the cursor
        :param int y: y coordinate of the cursor
        :param float radius: radius coordinate of the cursor
        :param str color: colour of the cursor
        """
        circle = plt.Circle((x, y), radius,
                            edgecolor=color, facecolor='none',
                            lw=2, zorder=10)
        self.ax.add_patch(circle)
        self.draggable_cursors.append(circle)
        # after adding, do a full redraw & recache background:
        self.draw()
        self.background = self.copy_from_bbox(self.ax.bbox)
    
    def update_draggable_cursor_pos(self, idx, x, y):
        """
        Updates the position of a draggable cursor
        
        :param int idx: Cursor index in list of draggable cursors
        :param int x: new x coordinate
        :param int y: new y coordinate
        """
        self.draggable_cursors[idx].center = x, y
        self.draw()
        self.background = self.copy_from_bbox(self.ax.bbox)

    def remove_draggable_cursor(self, idx):
        """
        Removes a draggable cursor from the canvas
        
        :param int idx: Cursor index in list of draggable cursors
        """
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
        """
        Plots the universal circle on the canvas
        """
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
# Supporting utils for generalisable file import

def extract_channel(data, channel_idx=0):
    """
    Returns the channel image for thresholding, robust to 2D, 3D, or 4D input.

    :returns: (t, y, x) if 4D input
    :returns: (y, x) if 3D or 2D input
    :rtype: tuple (int,int,int) | tuple (int,int)
    """
    if data.ndim == 4:
        return data[:, channel_idx, :, :].copy()
    elif data.ndim == 3:
        # Guess channel vs time-first by shape
        if data.shape[0] < 10:
            return data[channel_idx, :, :].copy()
        else:
            return data[:, :, :].copy()
    elif data.ndim == 2:
        return data.copy()
    else:
        raise ValueError(f"Unsupported array shape: {data.shape}")

# ---------------------------------------------------------------------------
# Supporting utils for cursor selection widget 

class ColorDelegate(QStyledItemDelegate):
    """Colour selection drop-down menu with a thumbnail filled with colour options and names
    
    :meta private:
    """
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
    """This will allow for selection of the created colour drop down options based on the colour model generated
    
    :meta private:
    """
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
        """This will create a colour model so that CSS4 colours are ordered by colour gradient
        
        :meta private:
        """
        
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
    """A delegate that provides a narrow QLineEdit with a double validator for numeric columns.
    
    :meta private:
    """
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
