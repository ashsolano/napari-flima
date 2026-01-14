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

import imageio

from .file_selection_table import FileSelectionTable

from .cursor_analysis import CursorAnalysisWidget

from .utils import (
    extract_channel, ColorSelectorApp, PlotCanvas, Worker
)

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
        self.file_selection_widget = FileSelectionTable(self, title="🛈 &File Selection")
        self.file_selection_widget.threshold_changed.connect(self.update_threshold)
        self.file_selection_widget.mask_changed.connect(self.on_mask_changed)
        layout.addWidget(self.file_selection_widget)
        
    
        
        # --- Cursor Analysis Section ---
        self.cursor_analysis_widget = CursorAnalysisWidget(self, title="🛈 &Cursor Analysis", font=self.font())
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
        
        # Debouncing timer for phasor replotting
        self.replot_timer = QTimer()
        self.replot_timer.setSingleShot(True)
        self.replot_timer.setInterval(200)  # 200ms delay
        self.replot_timer.timeout.connect(self.replot_phasor)
        
 
    
    def update_threshold(self, file_name, threshold_value):
        self.update_image_layer(file_name, threshold_value[0], threshold_value[1])
        
    def on_mask_changed(self, file_name, mask_name):
        # Trigger update of the image layer to re-apply mask + threshold
        if file_name in self.file_selection_widget.file_rows:
             # Retrieve current threshold values to pass
             slider = self.file_selection_widget.file_rows[file_name]["slider"]
             val = slider.value()
             self.update_image_layer(file_name, val[0], val[1])

    def load_mask_file(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Mask File", "", "Images (*.tif *.tiff *.png *.jpg)")
        if file_path:
            # Load as a labels layer or image layer? 
            # Usually mask is binary, but user said "treat non zero values as 1s", implies it might be intensity image.
            # Loading as Image layer is safer.
            try:
                self.viewer.open(file_path, name=os.path.basename(file_path), plugin='napari')
            except Exception as e:
                print(f"Error loading mask file: {e}")
            
    def update_mask_choices(self):
        # list all image/label layers that are NOT the current analysis files? 
        # Or just list all layers. The user can distinguish.
        # But we need to avoid self-selection loops if possible? (Simplicity: just list all).
        layers = [layer.name for layer in self.viewer.layers if hasattr(layer, 'data')]
        self.file_selection_widget.update_mask_choices(layers)

    def on_layer_added(self, event):
        layer = event.value
        self.update_mask_choices() # Update mask choices whenever a layer is added
        
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
        self.update_mask_choices() # Update mask choices whenever a layer is removed


    def update_threshold(self, file_name, threshold_value):
        self.update_image_layer(file_name, threshold_value[0], threshold_value[1])
    

    def update_image_layer(self, file_name, threshold_lower, threshold_upper):
        channel_map = self.intro_params.get("channel_assignments", [])
        intensity_idx = channel_map.index("Intensity") if "Intensity" in channel_map else 0
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
        original_data = self.file_selection_widget.file_rows[file_name]["layer_data"]
        checkbox_checked = self.file_selection_widget.file_rows[file_name]["checkbox"].isChecked()
        mask_layer_name = file_name + "_mask"
    
        # --- Universal thresholding logic ---
        intensity_image = extract_channel(original_data, intensity_idx)
        if intensity_image.ndim == 3:
            mask_lower = intensity_image < threshold_lower
            mask_upper = intensity_image > threshold_upper
            mask = np.logical_or(mask_lower, mask_upper)
            mask0 = mask[0]
        else:
            mask_lower = intensity_image < threshold_lower
            mask_upper = intensity_image > threshold_upper
            mask = np.logical_or(mask_lower, mask_upper)
            mask0 = mask
        if not checkbox_checked:
            rgba_mask = np.zeros(mask0.shape + (4,), dtype=np.uint8)
            rgba_mask[mask0, 0] = 255
            rgba_mask[mask0, 3] = 128
            if mask0.sum() > 0:
                overlay = self._create_or_update_overlay(mask_layer_name, rgba_mask)
            else:
                self.remove_overlay(mask_layer_name)
        else:
            self.remove_overlay(mask_layer_name)
            
        # --- Apply External Mask Layer if selected ---
        mask_selection_combo = self.file_selection_widget.file_rows[file_name].get("mask_combo")
        if mask_selection_combo:
            selected_mask_name = mask_selection_combo.currentText()
            if selected_mask_name != "None" and selected_mask_name in self.viewer.layers:
                mask_layer_obj = self.viewer.layers[selected_mask_name]
                mask_data = mask_layer_obj.data
                
                # Treat non-zero values as 1 (inclusion mask)
                # Actually, usually mask means "1 is ROI". 
                # If we want to EXCLUDE pixels that are 0 in the mask:
                # We add to the 'mask' (which is the exclusion mask for setting to 0).
                # So if mask_data == 0, we want to exclude.
                
                # Broadcasting logic
                # Target shape: intensity_image.shape
                # mask_data shape: ?
                
                # 1. Binarize
                binary_ext_mask = (mask_data != 0)
                
                # 2. Invert for exclusion (True where we want to set to 0)
                exclusion_ext_mask = ~binary_ext_mask
                
                # 3. Broadcast
                final_ext_mask = None
                
                if exclusion_ext_mask.shape == intensity_image.shape:
                    final_ext_mask = exclusion_ext_mask
                elif exclusion_ext_mask.ndim == 2 and intensity_image.ndim == 3:
                     # Broadcast 2D mask to 3D image
                     # (H, W) -> (T, H, W)
                     if exclusion_ext_mask.shape == intensity_image.shape[1:]:
                         final_ext_mask = np.broadcast_to(exclusion_ext_mask, intensity_image.shape)
                     else:
                         print(f"Shape mismatch: Mask {exclusion_ext_mask.shape} vs Image {intensity_image.shape}")
                elif exclusion_ext_mask.ndim == 3 and intensity_image.ndim == 3:
                     # Frame mismatch?
                     if exclusion_ext_mask.shape != intensity_image.shape:
                         print(f"Frame/Shape mismatch between mask {selected_mask_name} and image {file_name}. Applying anyway as per request.")
                         # Strategy: If T dim differs, broadcast or loop?
                         # Safe fallback: apply frame by frame with modulo? 
                         # Or simpler: if 2D shapes match, use simple broadcasting if T=1
                         
                         if exclusion_ext_mask.shape[1:] == intensity_image.shape[1:]:
                             # Spatial dims match.
                             if exclusion_ext_mask.shape[0] == 1:
                                  # Broadcast single frame
                                  final_ext_mask = np.broadcast_to(exclusion_ext_mask[0], intensity_image.shape)
                             else:
                                  # Iterate and assign?
                                  # Let's create a full size mask
                                  final_ext_mask = np.zeros(intensity_image.shape, dtype=bool)
                                  T_img = intensity_image.shape[0]
                                  T_mask = exclusion_ext_mask.shape[0]
                                  for t in range(T_img):
                                      # Use modulo for looping if mask is shorter, or just clamp?
                                      # "Apply mask to each frame anyway" -> maybe loop if short.
                                      t_m = t % T_mask
                                      final_ext_mask[t] = exclusion_ext_mask[t_m]
                         else:
                             print("Spatial dimensions mismatch. Cannot apply mask efficiently.")
                
                if final_ext_mask is None and exclusion_ext_mask.ndim == intensity_image.ndim:
                     # Check if shapes match exactly again?
                     if exclusion_ext_mask.shape == intensity_image.shape:
                         final_ext_mask = exclusion_ext_mask

                # Combine with threshold mask
                if final_ext_mask is not None:
                    mask = np.logical_or(mask, final_ext_mask)

        # Apply threshold (and external mask)
        intensity_image[mask] = 0
        # Copy back into right place in data
        updated_data = original_data.copy()
        if original_data.ndim == 4:
            updated_data[:, intensity_idx, :, :] = intensity_image
        elif original_data.ndim == 3 and original_data.shape[0] < 10:
            updated_data[intensity_idx, :, :] = intensity_image
        elif original_data.ndim == 3:
            updated_data[:, :, :] = intensity_image
        elif original_data.ndim == 2:
            updated_data[:, :] = intensity_image
        else:
            raise ValueError(f"Unexpected shape for update: {original_data.shape}")
        self.intensity = intensity_image.copy()
        image_layer.data = updated_data
        image_layer.refresh()
        self.current_mask = mask
        # Overlay positioning logic as before...
        if mask_layer_name in self.viewer.layers:
            overlay_layer = self.viewer.layers[mask_layer_name]
            if self.viewer.grid.enabled:
                if hasattr(image_layer, "metadata") and "grid" in image_layer.metadata:
                    overlay_layer.metadata = overlay_layer.metadata or {}
                    overlay_layer.metadata["grid"] = image_layer.metadata["grid"]
                else:
                    try:
                        idx = self.file_order.index(file_name)
                    except ValueError:
                        idx = 0
                    overlay_layer.metadata = overlay_layer.metadata or {}
                    overlay_layer.metadata["grid"] = (0, idx)
            else:
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
            QApplication.setOverrideCursor(Qt.WaitCursor)
            threshold_value = self.file_selection_widget.file_rows[file_name]["slider"].value()
            self.update_threshold(file_name, threshold_value)
            
            # Prepare data for worker
            layer_data = self.file_selection_widget.file_rows[file_name]["layer_data"]
            current_mask = self.current_mask.copy() if self.current_mask is not None else None
            # Copy intro_params to ensure thread safety (shallow copy is usually enough for dict of primitives)
            intro_params = self.intro_params.copy()

            # Create worker and thread
            thread = QThread()
            worker = Worker(self.run_phasor_calculation, layer_data, intro_params, current_mask)
            worker.moveToThread(thread)
            
            # Store references to prevent garbage collection
            if not hasattr(self, "_threads"):
                self._threads = {}
            self._threads[file_name] = (thread, worker)

            # Connect signals
            thread.started.connect(worker.run)
            worker.result.connect(partial(self.on_phasor_result, file_name=file_name, current_mask=current_mask))
            worker.finished.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            # Cleanup storage when thread finishes
            thread.finished.connect(thread.deleteLater)
            thread.finished.connect(lambda: self._cleanup_thread(file_name))
            thread.finished.connect(lambda: QApplication.restoreOverrideCursor())
            
            thread.start()

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
            
            self.replot_timer.start()

    @staticmethod
    def run_phasor_calculation(layer_data, intro_params, current_mask):
        intensity, g_image, s_image, orig_g, orig_s = PhasorWidget.calculate_g_s_coordinates(
            layer_data, intro_params, zero_indices=current_mask
        )
        tau_m, tau_p, tau_av = PhasorWidget.compute_lifetimes_from_gs(g_image, s_image, intro_params)
        return intensity, g_image, s_image, orig_g, orig_s, tau_m, tau_p, tau_av

    def on_phasor_result(self, result, file_name, current_mask):
        intensity, g_image, s_image, orig_g, orig_s, tau_m, tau_p, tau_av = result
        
        # Apply threshold mask to the lifetime arrays
        if current_mask is not None:
            try:
                if tau_m.ndim == current_mask.ndim:
                    tau_m[current_mask] = np.nan
                    tau_p[current_mask] = np.nan
                    tau_av[current_mask] = np.nan
                elif tau_m.ndim == 2 and current_mask.ndim == 3:
                    tau_m[0][current_mask[0]] = np.nan
                    tau_p[0][current_mask[0]] = np.nan
                    tau_av[0][current_mask[0]] = np.nan
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
        self.original_g = orig_g
        self.original_s = orig_s

        # Update or add the lifetime layer.
        base_name = os.path.splitext(os.path.basename(file_name))[0]
        tau_av_layer_name = f"{base_name}_lifetime"
        try:
            min_tau_av = np.nanpercentile(tau_av, 1)
            max_tau_av = np.nanpercentile(tau_av, 99)
        except Exception as e:
            # print("Error computing percentiles for tau_av:", e)
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
        
        # Finally, replot the phasor using only the g/s data from checked files.
        self.replot_timer.start()


     
    def _cleanup_thread(self, key):
        if hasattr(self, "_threads") and key in self._threads:
            del self._threads[key]

    # def replot_phasor(self):
    #     """
    #     Replot the phasor dialog by timepoint, overlaying every checked file.
    #     - If g_array is 3D (T×H×W): we get T pages.
    #     - If g_array is 2D: T = 1, so you get one page with all files.
    #     """
    #     # 1) clear old frames
    #     self.dialog.frames = []
    
        
    #     if not self.file_gs_data:
    #         print("No files selected for phasor plotting.")
    #         self.dialog.plot_universal_circle()
    #         return
    
        
    #     files = list(self.file_gs_data.keys())
    #     # pick the first file to infer T
    #     sample = self.file_gs_data[files[0]]
    #     data0 = (self.smoothed_gs_data[files[0]]
    #              if self.median_filter_applied and files[0] in self.smoothed_gs_data
    #              else sample)
    #     g0 = data0["g_image"]
    #     T = g0.shape[0] if g0.ndim == 3 else 1
    
        
    #     for t in range(T):
    #         for fname in files:
    #             raw = self.smoothed_gs_data[fname] if (self.median_filter_applied and fname in self.smoothed_gs_data) else self.file_gs_data[fname]
    #             g_arr = raw["g_image"]
    #             s_arr = raw["s_image"]
    #             if g_arr.ndim == 3:
    #                 self.dialog.add_frame(g_arr[t], s_arr[t])
    #             else:
    #                 # 2D data → only one frame, so add on t==0
    #                 if t == 0:
    #                     self.dialog.add_frame(g_arr, s_arr)
    
    #     # 5) force pages = T, with each page = len(files)
    #     self.dialog.group_size = 1
    #     # sync spinner to this
    #     self.dialog.group_spin.blockSignals(True)
    #     self.dialog.group_spin.setValue(1)
    #     self.dialog.group_spin.setEnabled(len(self.dialog.frames) > 1)
    #     self.dialog.group_spin.blockSignals(False)
    
    #     # 6) redraw
    #     self.dialog.update_frame_navigation()
    #     self.dialog.plot_current_group()
 
    def replot_phasor(self):
        """
        Replot the phasor dialog by timepoint, aggregating all checked files.
        Each frame shows ALL selected files' g/s data at that timepoint.
        """
        # 1) Clear old frames
        self.dialog.frames = []
    
        if not self.file_gs_data:
            print("No files selected for phasor plotting.")
            self.dialog.plot_universal_circle()
            return
    
        files = list(self.file_gs_data.keys())
        # Pick the first file to infer T
        sample = self.file_gs_data[files[0]]
        data0 = (self.smoothed_gs_data[files[0]]
                 if self.median_filter_applied and files[0] in self.smoothed_gs_data
                 else sample)
        g0 = data0["g_image"]
        T = g0.shape[0] if g0.ndim == 3 else 1
    
        for t in range(T):
            g_list = []
            s_list = []
            for fname in files:
                raw = self.smoothed_gs_data[fname] if (self.median_filter_applied and fname in self.smoothed_gs_data) else self.file_gs_data[fname]
                g_arr = raw["g_image"]
                s_arr = raw["s_image"]
                if g_arr.ndim == 3:
                    g_list.append(g_arr[t].flatten())
                    s_list.append(s_arr[t].flatten())
                else:
                    g_list.append(g_arr.flatten())
                    s_list.append(s_arr.flatten())
            # Concatenate ALL files' points at this timepoint
            g_concat = np.concatenate(g_list)
            s_concat = np.concatenate(s_list)
            self.dialog.add_frame(g_concat, s_concat)
    
        # Only one group per timepoint
        self.dialog.group_size = 1
        self.dialog.group_spin.blockSignals(True)
        self.dialog.group_spin.setValue(1)
        self.dialog.group_spin.setEnabled(len(self.dialog.frames) > 1)
        self.dialog.group_spin.blockSignals(False)
    
        # Redraw
        self.dialog.update_frame_navigation()
        self.dialog.plot_current_group()
              


   
    @staticmethod
    def calculate_g_s_coordinates(image_data, intro_params, zero_indices=None):
        """
        Calculate the G and S coordinates for phasor analysis using the channel assignments
        provided in the intro parameters.
    
        Supports 2D, 3D, or 4D arrays for both FD FLIM and TCSPC FLIM types.
        """
        channel_map = intro_params.get("channel_assignments", [])
        flim_type = intro_params.get("flim_type", "FD FLIM")
        harmonic = intro_params.get("harmonic", 1)
        # laser_frequency unused here but extracted in original
        intensity_idx = channel_map.index("Intensity") if "Intensity" in channel_map else 0
        
        original_g = None
        original_s = None
    
        if flim_type == "FD FLIM":
            # Always works for 2D/3D/4D:
            intensity = extract_channel(image_data, intensity_idx)
    
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
                    pass  # already set
                try:
                    mod_idx = channel_map.index("Modulation-values")
                except ValueError:
                    pass  # already set
    
            phase_array = extract_channel(image_data, phase_idx)
            mod_array = extract_channel(image_data, mod_idx)
    
            g_image = mod_array * np.cos(np.pi / 180 * phase_array)
            s_image = mod_array * np.sin(np.pi / 180 * phase_array)
    
            original_g = g_image.copy()
            original_s = s_image.copy()
    
            if zero_indices is not None:
                g_image[zero_indices] = 0
                s_image[zero_indices] = 0
    
        elif flim_type == "TCSPC FLIM":
            # Robust extraction for all dimensions:
            intensity = extract_channel(image_data, intensity_idx)
            try:
                g_idx = channel_map.index("G-values")
            except ValueError:
                g_idx = 4  # default fallback
            try:
                s_idx = channel_map.index("S-values")
            except ValueError:
                s_idx = 5  # default fallback
    
            g_values = extract_channel(image_data, g_idx)
            s_values = extract_channel(image_data, s_idx)
    
            g_values_m = (g_values - 32767.5) / 32767.5
            s_values_m = (s_values - 32767.5) / 32767.5
    
            original_g = g_values_m.copy()
            original_s = s_values_m.copy()
    
            if zero_indices is not None:
                g_values_m[zero_indices] = 0
                s_values_m[zero_indices] = 0
    
            g_image = g_values_m.copy()
            s_image = s_values_m.copy()
    
        return intensity, g_image, s_image, original_g, original_s
    
    
    @staticmethod
    def compute_lifetimes_from_gs(g_array, s_array, intro_params):
        """
        Compute modulation (tau_m) and phase (tau_p) lifetimes from G and S arrays.
        Laser frequency (in MHz) is taken from the intro parameters.
        If the computed magnitude m is zero, tau_m is set to 0.
        """
        # Retrieve the laser frequency from the intro parameters (in MHz)
        laser_freq_mhz = intro_params.get("laser_frequency", 80.0)
        # print(laser_freq_mhz)
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

        QApplication.setOverrideCursor(Qt.WaitCursor)
        # We pass a copy/extraction of relevant data to minimize side effects, 
        # though passing file_gs_data dict (keys + pointers to arrays) is generally okay for read-access
        # but let's be explicit if possible. here we just pass the dict.
        thread = QThread()
        worker = Worker(self.run_median_filter_processing, self.file_gs_data, nsmoothing)
        worker.moveToThread(thread)
        
        # Store ref
        if not hasattr(self, "_threads"):
            self._threads = {}
        self._threads['median_filter'] = (thread, worker)

        thread.started.connect(worker.run)
        worker.result.connect(self.on_median_filter_result)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._cleanup_thread('median_filter'))
        thread.finished.connect(lambda: QApplication.restoreOverrideCursor())
        
        thread.start()

    @staticmethod
    def run_median_filter_processing(file_gs_data, nsmoothing):
        results = {}
        for file_name, data in file_gs_data.items():
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
                filtered_g = filtered_g
                filtered_s = filtered_s
            else:
                # print(f"Unsupported data shape for file: {file_name}")
                continue

            results[file_name] = {
                "g_image": filtered_g.copy(),
                "s_image": filtered_s.copy()
            }
        return results

    def on_median_filter_result(self, results):
        if not hasattr(self, "smoothed_gs_data"):
            self.smoothed_gs_data = {}
        
        self.smoothed_gs_data.update(results)
        self.median_filter_applied = True
        self.replot_timer.start()


    

    
    def reset_filter(self):
        self.dialog.kernel_spin.setValue(3)
        self.dialog.iter_spin.setValue(1)
        self.median_filter_applied = False
        # Optionally, reset the smoothed data to match the original.
        if self.file_gs_data:
            self.smoothed_gs_data = {file_name: data.copy() for file_name, data in self.file_gs_data.items()}
        self.replot_timer.start()

    
   
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
        print("Updating G and S values...")
        """Upon releasing the draggable cursor, update the corresponding G and S input values."""
        QApplication.setOverrideCursor(Qt.WaitCursor)
        # Check if the cursor index is valid within our stored cursor rows.
        if cursor_index < len(self.cursor_analysis_widget.cursor_rows_data):
            row_data = self.cursor_analysis_widget.cursor_rows_data[cursor_index]
            self.cursor_analysis_widget.table.blockSignals(True)
            # Assuming column 3 holds the G value and column 4 holds the S value:
            row_data["col_3"].setText(f"{x:.2f}")
            row_data["col_4"].setText(f"{y:.2f}")
           
            tau_mod, tau_phase = self.compute_lifetimes_from_point(x, y)
            #print("printing tau_mod and tau_phase values")
            #print(tau_mod)
            #print(tau_phase)
            
            row_data["col_5"].setText(f"{tau_mod:.2f}")
            row_data["col_6"].setText(f"{tau_phase:.2f}")

            self.dialog.plot_canvas.update_draggable_cursor_pos(cursor_index, x, y)
            self.update_pixels_within_cursor()
            self.cursor_analysis_widget.table.blockSignals(False)
            print("Done!")
        else:
            print(f"Cursor index {cursor_index} is out of range.")

        QApplication.restoreOverrideCursor()

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
        #print("Selecting pixels (threaded)")
        
        if not hasattr(self, 'intensity') or self.intensity is None:
            # print("Error: intensity data is not initialized.")
            return

        # 1) Gather data from UI (must happen on main thread)
        #    We need:
        #      - file_gs_data / smoothed_gs_data (the G/S arrays)
        #      - active cursor parameters (radius, G, S, color)
        #      - median_filter_applied flag

        cursor_params = []
        for row_data in self.cursor_analysis_widget.cursor_rows_data:
            if row_data["checkbox"].isChecked():
                try:
                    r = float(row_data["col_2"].text())
                    g_c = float(row_data["col_3"].text())
                    s_c = float(row_data["col_4"].text())
                    c_txt = row_data["color_selector"].currentText()
                    params = {
                        "radius": r,
                        "g_center": g_c,
                        "s_center": s_c,
                        "color_text": c_txt
                    }
                    cursor_params.append(params)
                except Exception as e:
                    print(f"Error parsing cursor row: {e}")
                    continue
        
        if not cursor_params:
            # If no cursors active, we might want to clear existing masks?
            # For now, just return or handle as empty.
            pass

        # Prepare a lightweight dict of file -> (g_array, s_array)
        # to avoid passing 'self' to worker.
        files_to_process = {}
        for file_name, file_data in self.file_gs_data.items():
            if self.median_filter_applied and file_name in self.smoothed_gs_data:
                g = self.smoothed_gs_data[file_name]["g_image"]
                s = self.smoothed_gs_data[file_name]["s_image"]
            else:
                g = file_data["g_image"]
                s = file_data["s_image"]
            
            if g is not None and s is not None:
                files_to_process[file_name] = (g, s)

        if not files_to_process:
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        
        # 2) Create Thread & Worker
        thread = QThread()
        worker = Worker(self.calculate_cursor_masks, files_to_process, cursor_params)
        worker.moveToThread(thread)
        
        # Store ref
        if not hasattr(self, "_threads"):
            self._threads = {}
        self._threads['cursor_update'] = (thread, worker)

        thread.started.connect(worker.run)
        worker.result.connect(self.on_cursor_mask_result)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._cleanup_thread('cursor_update'))
        thread.finished.connect(lambda: QApplication.restoreOverrideCursor())
        
        thread.start()

    @staticmethod
    def calculate_cursor_masks(files_map, cursor_params):
        """
        Static method running in worker thread.
        files_map: { filename: (g_arr, s_arr) }
        cursor_params: list of dicts {radius, g_center, s_center, color_text}
        Returns: dict { filename: (highlighted_pixels_rgba, layer_shape_hint) }
        """
        results = {}
        
        for file_name, (g_data, s_data) in files_map.items():
            # Create blank RGBA
            if g_data.ndim == 3:
                # (T, H, W, 4)
                highlighted_pixels = np.zeros(g_data.shape + (4,), dtype=np.uint8)
            else:
                # (H, W, 4)
                highlighted_pixels = np.zeros(g_data.shape + (4,), dtype=np.uint8)

            for p in cursor_params:
                radius = p["radius"]
                g_c = p["g_center"]
                s_c = p["s_center"]
                color_name = p["color_text"]
                
                # QColor is not thread-safe safe or not available without GUI? 
                # Actually QColor is QtGui, often okay, but safer to parse or pass RGB.
                # simpler: we can use QColor here if QtGui is imported.
                # If crash, we move rgb parsing to main thread.
                try:
                    rgb = QColor(color_name).getRgb()[:3]
                except:
                    rgb = (255, 0, 0)

                if g_data.ndim == 3:
                     # Vectorized over T is tricky if memory large, but let's try loop or broadcast
                     # g_data: (T, Y, X)
                    dist = np.hypot(g_data - g_c, s_data - s_c)
                    mask = dist <= radius
                    # mask is (T, Y, X)
                    # highlight is (T, Y, X, 4)
                    # We want to assign color where mask is True
                    highlighted_pixels[mask] = rgb + (255,)
                else:
                    dist = np.hypot(g_data - g_c, s_data - s_c)
                    mask = dist <= radius
                    highlighted_pixels[mask] = rgb + (255,)
            
            # Prepare layer data shape
            # If 2D (H, W, 4) -> (1, 1, H, W, 4)
            # If 3D (T, H, W, 4) -> (T, 1, H, W, 4)
            if g_data.ndim == 2:
                layer_data = np.expand_dims(np.expand_dims(highlighted_pixels, axis=0), axis=0)
            elif g_data.ndim == 3:
                layer_data = np.expand_dims(highlighted_pixels, axis=1)
            else:
                layer_data = highlighted_pixels
            
            results[file_name] = layer_data

        return results

    def on_cursor_mask_result(self, results):
        """
        Update Napari layers with calculated masks.
        results: { filename: layer_data_array }
        """
        if not hasattr(self, 'cursor_mask_layers'):
            self.cursor_mask_layers = {}

        for file_name, layer_data in results.items():
            base_name = os.path.splitext(os.path.basename(file_name))[0]
            cursor_layer_name = f"{base_name}_cursor_mask"
            
            if cursor_layer_name in self.viewer.layers:
                self.viewer.layers[cursor_layer_name].data = layer_data
            else:
                new_layer = self.viewer.add_image(
                    layer_data,
                    name=cursor_layer_name,
                    colormap=None
                )
                self.cursor_mask_layers[file_name] = new_layer

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