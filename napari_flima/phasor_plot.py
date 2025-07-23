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

from .utils import PlotCanvas

import imageio

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

        
    # def update_frame_navigation(self):
    #     total_frames = len(self.frames)
    #     total_groups = ceil(total_frames / self.group_size) if total_frames > 0 else 1
    #     if self.current_group >= total_groups:
    #         self.current_group = total_groups - 1
    #     self.frame_slider.blockSignals(True)
    #     self.frame_spin.blockSignals(True)
    #     self.frame_slider.setMaximum(total_groups)
    #     self.frame_spin.setMaximum(total_groups)
    #     self.frame_slider.setValue(self.current_group + 1)
    #     self.frame_spin.setValue(self.current_group + 1)
    #     self.frame_slider.blockSignals(False)
    #     self.frame_spin.blockSignals(False)
        
    def update_frame_navigation(self):
        total_frames = len(self.frames)
        # Restrict group size to available frames
        self.group_spin.blockSignals(True)
        self.group_spin.setMaximum(total_frames if total_frames > 0 else 1)
        if self.group_size > total_frames:
            self.group_size = total_frames if total_frames > 0 else 1
            self.group_spin.setValue(self.group_size)
        # Optionally disable group size if only 1 frame
        self.group_spin.setEnabled(total_frames > 1)
        self.group_spin.blockSignals(False)
    
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
        print("Num frames in PhasorPlotDialog:", len(self.frames))
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