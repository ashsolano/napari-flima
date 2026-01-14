import os
import shutil
import numpy as np
import pandas as pd
import imageio
import webbrowser

from matplotlib import cm
from scipy.ndimage import gaussian_filter
from scipy.stats import gaussian_kde, ttest_ind, describe

from skimage.measure import label, regionprops
from skimage.color import label2rgb
from skimage.morphology import remove_small_objects, closing, disk

from jinja2 import Template

# PyQt / QtPy imports
from PyQt5.QtGui import QColor  # or: from qtpy.QtGui import QColor, depending on your setup
from qtpy.QtWidgets import (
    QGroupBox, QVBoxLayout, QWidget, QSizePolicy, QLabel,
    QHBoxLayout, QLineEdit, QPushButton, QCheckBox, QComboBox, QFileDialog,
    QSpinBox, QDoubleSpinBox, QMessageBox
)
from qtpy.QtGui import (QFont)

from qtpy.QtCore import Signal

# Bokeh imports
from bokeh.plotting import figure
from bokeh.models import ColumnDataSource, Whisker, HoverTool, Label
from bokeh.embed    import components
from bokeh.resources import CDN

# generalise logo path 
from napari_flima import get_logo_path
from .utils import Worker
from qtpy.QtCore import QThread, Qt
from qtpy.QtWidgets import QApplication
from functools import partial


# ------------------- BACKEND FUNCTIONS -------------------

def compute_iou(boxA, boxB):
    """Compute IoU (Intersection over Union) between two bounding boxes."""
    xA, yA = max(boxA[0], boxB[0]), max(boxA[1], boxB[1])
    xB, yB = min(boxA[2], boxB[2]), min(boxA[3], boxB[3])
    inter_area = max(0, xB - xA) * max(0, yB - yA)
    boxA_area = (boxA[2] - boxA[0]) * (boxA[3] - boxA[1])
    boxB_area = (boxB[2] - boxB[0]) * (boxB[3] - boxB[1])
    union = boxA_area + boxB_area - inter_area
    return inter_area / float(union) if union > 0 else 0

def segment_and_track(intensity_data, min_size=50, threshold=75, iou_threshold=0.3, dist_threshold=10):
    """
    Perform segmentation and tracking across multiple frames.
    Assumes intensity_data is a 3D array (T, H, W).
    Returns a segmented mask (same shape as intensity_data) and a color_map dictionary.
    """
    num_frames = intensity_data.shape[0]
    min_persistence= num_frames
    segmented_masks = np.zeros_like(intensity_data, dtype=int)
    prev_objects, next_label, color_map, object_persistence = {}, 1, {}, {}

    for t_idx in range(num_frames):
        smoothed_frame = gaussian_filter(intensity_data[t_idx], sigma=2)
        bin_thresh = np.percentile(smoothed_frame, threshold)
        binary_mask = smoothed_frame > bin_thresh
        labeled_mask = label(closing(binary_mask, disk(3)))
        labeled_mask = remove_small_objects(labeled_mask, min_size)
        props = regionprops(labeled_mask)
        current_objects = {prop.label: (prop.centroid, prop.bbox) for prop in props}
        matched_labels = {}

        if prev_objects:
            prev_bboxes = {k: prev_objects[k][1] for k in prev_objects}
            curr_bboxes = {k: current_objects[k][1] for k in current_objects}
            for curr_id, curr_bbox in curr_bboxes.items():
                best_match, best_iou, best_dist = None, 0, float('inf')
                for prev_id, prev_bbox in prev_bboxes.items():
                    iou = compute_iou(prev_bbox, curr_bbox)
                    dist = np.linalg.norm(np.array(prev_objects[prev_id][0]) - np.array(current_objects[curr_id][0]))
                    if iou > best_iou and iou > iou_threshold:
                        best_match, best_iou = prev_id, iou
                    elif dist < best_dist and dist < dist_threshold:
                        best_match, best_dist = prev_id, dist
                if best_match:
                    object_persistence[best_match] = object_persistence.get(best_match, 0) + 1
                    matched_labels[curr_id] = best_match
                else:
                    matched_labels[curr_id] = next_label
                    object_persistence[next_label] = 1
                    next_label += 1
        else:
            matched_labels = {obj_id: obj_id for obj_id in current_objects.keys()}
            next_label = max(current_objects.keys()) + 1 if current_objects else 1
            for obj_id in matched_labels.values():
                object_persistence[obj_id] = 1

        new_segmented_mask = np.zeros_like(labeled_mask)
        for obj_label in current_objects.keys():
            final_label = matched_labels.get(obj_label, next_label)
            if final_label not in color_map:
                color_map[final_label] = np.random.rand(3)
            new_segmented_mask[labeled_mask == obj_label] = final_label

        segmented_masks[t_idx] = new_segmented_mask
        prev_objects = {matched_labels[k]: v for k, v in current_objects.items()}

    persistent_objs = {obj_id for obj_id, count in object_persistence.items() if count >= min_persistence}
    segmented_masks = np.where(np.isin(segmented_masks, list(persistent_objs)), segmented_masks, 0)
    return segmented_masks, color_map

# ------------------- SEGMENTATION WIDGETS -------------------

class SegmentationParametersWidget(QWidget):
    """
    A widget for segmentation parameters.
    It uses analysis data (passed from the phasor widget) to obtain intensity data.
    For each file, segmentation is applied and the tracked objects layer
    (named "<base>_objects") is added to the viewer.
    
    It also stores the segmentation label arrays in self.segmentation_results,
    which are later used by the "Apply Cursor Mask" function.
    """
    def __init__(self, viewer, analysis_data=None, phasor_widget=None, parent=None):
        super().__init__(parent)
        self.viewer = viewer
        # analysis_data is a dict (from the phasor widget) with keys like "file_gs_data"
        self.analysis_data = analysis_data if analysis_data is not None else {}
        self.phasor_widget = phasor_widget 
        self.segmentation_results = {}  # Will store the label images (segmentation masks) per file.
        self.setFont(QFont("Arial", 8))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(300)
        self.setStyleSheet("""
            QWidget {
                background-color: #282a36;
                color: #f8f8f2;
            }
            QGroupBox {
                border: 1px solid #707070;
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                                  stop:0 #282a36, stop:1 #33353b);
                border-radius: 5px;
                margin-top: 10px;
                padding: 5px;
            }
            QGroupBox::title {
                color: #f8f8f2;
                left: 10px;
                padding: 0 5px;
            }
            QSpinBox, QDoubleSpinBox {
                background-color: white;
                color: black;
                padding: 2px;
                border: 1px solid #707070;
                max-width: 80px;
            }
            QPushButton {
                background-color: #007acc;
                color: white;
                border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #005f99;
            }
        """)

        layout = QVBoxLayout(self)
        self.groupbox = QGroupBox("Segmentation Parameters")
        group_layout = QVBoxLayout()

        # Row for Min Object Size.
        row_min_size = QHBoxLayout()
        label_min_size = QLabel("Min Object Size:")
        row_min_size.addWidget(label_min_size)
        self.spin_min_size = QSpinBox()
        self.spin_min_size.setRange(0, 1000)
        self.spin_min_size.setValue(50)
        row_min_size.addWidget(self.spin_min_size)
        group_layout.addLayout(row_min_size)

        # Row for Threshold (%)
        row_threshold = QHBoxLayout()
        label_threshold = QLabel("Threshold (%):")
        row_threshold.addWidget(label_threshold)
        self.spin_threshold = QSpinBox()
        self.spin_threshold.setRange(0, 100)
        self.spin_threshold.setValue(75)
        row_threshold.addWidget(self.spin_threshold)
        group_layout.addLayout(row_threshold)

        # Row for IoU Threshold.
        row_iou = QHBoxLayout()
        label_iou = QLabel("IoU Thresh:")
        row_iou.addWidget(label_iou)
        self.spin_iou = QDoubleSpinBox()
        self.spin_iou.setRange(0.0, 1.0)
        self.spin_iou.setSingleStep(0.01)
        self.spin_iou.setValue(0.3)
        row_iou.addWidget(self.spin_iou)
        group_layout.addLayout(row_iou)

        # Row for Max Distance.
        row_dist = QHBoxLayout()
        label_dist = QLabel("Max Dist:")
        row_dist.addWidget(label_dist)
        self.spin_dist = QSpinBox()
        self.spin_dist.setRange(0, 100)
        self.spin_dist.setValue(10)
        row_dist.addWidget(self.spin_dist)
        group_layout.addLayout(row_dist)

        # Row for Min Persistence.
        row_persist = QHBoxLayout()
        label_persist = QLabel("Min Persist:")
        row_persist.addWidget(label_persist)
        self.spin_persist = QSpinBox()
        self.spin_persist.setRange(0, 100)
        self.spin_persist.setValue(30)
        row_persist.addWidget(self.spin_persist)
        group_layout.addLayout(row_persist)

        # Segment & Track Button.
        self.segment_button = QPushButton("Segment & Track")
        self.segment_button.clicked.connect(self.run_segmentation)
        group_layout.addWidget(self.segment_button)
        
        # New: Apply Cursor Mask Button.
        self.apply_mask_button = QPushButton("Compute Cursor Ratios")
        self.apply_mask_button.clicked.connect(self.on_apply_mask_clicked)
        group_layout.addWidget(self.apply_mask_button)

        self.groupbox.setLayout(group_layout)
        layout.addWidget(self.groupbox)
        layout.addStretch()
        self.setLayout(layout)

    def update_num_frames(self):
        print("updating min_persist")
        first_file = next(iter(self.analysis_data["file_gs_data"].values()), None)
        if first_file:
            num_frames = first_file.get("intensity").shape[0]
            print("got updated first file")
        else:
            num_frames = 30
        print(f"new min_persist: {num_frames}")
        self.spin_persist.setValue(num_frames)
        
    def on_apply_mask_clicked(self):
        # Disable the button so they can’t click again in the middle
        self.apply_mask_button.setEnabled(False)
        try:
            df_wide = self.analyze_cursor_mask()
            if df_wide is not None and not df_wide.empty:
                QMessageBox.information(
                    self,
                    "Downstream Analysis",
                    "Cursor mask analysis complete! "
                    f"Generated {len(df_wide)} rows."
                )
            else:
                QMessageBox.warning(
                    self,
                    "Downstream Analysis",
                    "Analysis ran, but no data was generated."
                )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Downstream Analysis Error",
                f"An error occurred:\n{e}"
            )
        finally:
            self.apply_mask_button.setEnabled(True)

    def run_segmentation(self):
        """
        For each file in the analysis data, retrieve the intensity data and apply segmentation.
        The resulting segmentation label arrays and colored masks are added to the viewer.
        The label arrays are stored in self.segmentation_results for later analysis.
        """
        min_size = self.spin_min_size.value()
        threshold = self.spin_threshold.value()
        iou_threshold = self.spin_iou.value()
        dist_threshold = self.spin_dist.value()
        min_persistence = self.spin_persist.value()

        if not self.analysis_data or "file_gs_data" not in self.analysis_data:
            print("No analysis data available from the phasor widget.")
            return

        # Prepare intensity map
        file_intensity_map = {}
        file_keys = list(self.analysis_data["file_gs_data"].keys())
        for file_name in file_keys:
            data = self.analysis_data["file_gs_data"][file_name]
            intensity = data.get("intensity")
            if intensity is None:
                for layer in self.viewer.layers:
                    if hasattr(layer, 'source') and layer.source.path:
                        base = os.path.splitext(os.path.basename(layer.source.path))[0]
                        if base == os.path.splitext(os.path.basename(file_name))[0]:
                            intensity = layer.data[:, 0, :, :]
                            break
                if intensity is None:
                    print(f"No intensity data for {file_name}.")
                    continue
            file_intensity_map[file_name] = intensity

        if not file_intensity_map:
            print("No valid intensity data found for any file.")
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        thread = QThread()
        worker = Worker(
            self.run_segmentation_processing,
            file_intensity_map, min_size, threshold, iou_threshold, dist_threshold, min_persistence
        )
        worker.moveToThread(thread)
        
        # Store ref
        if not hasattr(self, "_threads"):
            self._threads = {}
        self._threads['segmentation'] = (thread, worker)

        thread.started.connect(worker.run)
        worker.result.connect(self.on_segmentation_result)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: self._cleanup_thread('segmentation'))
        thread.finished.connect(lambda: QApplication.restoreOverrideCursor())
        
        thread.start()

    @staticmethod
    def run_segmentation_processing(file_intensity_map, min_size, threshold, iou_threshold, dist_threshold, min_persistence):
        results = {}
        for file_name, intensity in file_intensity_map.items():
            # segment_and_track is imported from global scope
            seg_masks, color_map = segment_and_track(
                intensity, min_size, threshold, iou_threshold, dist_threshold
            )
            
            # Use seg_masks for later use
            # Calculate colored masks
            formatted_colors = {
                i: tuple(color_map[i]) if i in color_map else (1, 0, 0)
                for i in np.unique(seg_masks) if i > 0
            }
           
            colored_masks = np.array([
                label2rgb(frame,
                          colors=[formatted_colors.get(lbl, (1, 0, 0)) for lbl in np.unique(frame)],
                          bg_label=0)
                for frame in seg_masks
            ])
            colored_masks = np.expand_dims(colored_masks, axis=1)
            results[file_name] = (seg_masks, colored_masks)
        return results

    def _cleanup_thread(self, key):
        if hasattr(self, "_threads") and key in self._threads:
            del self._threads[key]

    def on_segmentation_result(self, results):
        for file_name, (seg_masks, colored_masks) in results.items():
            self.segmentation_results[file_name] = seg_masks

            # Use the base layer’s scale and translate.
            if self.viewer.layers:
                base_layer = self.viewer.layers[0]
                dims = colored_masks.ndim - 1
                scale = tuple(np.atleast_1d(base_layer.scale).tolist())
                translate = tuple(np.atleast_1d(base_layer.translate).tolist())
                if len(scale) < dims:
                    scale = scale + (scale[-1],) * (dims - len(scale))
                if len(translate) < dims:
                    translate = translate + (translate[-1],) * (dims - len(translate))
            else:
                dims = colored_masks.ndim - 1
                scale = (1,) * dims
                translate = (0,) * dims

            base_name = os.path.splitext(os.path.basename(file_name))[0]
            objects_layer_name = f"{base_name}_objects"
            if objects_layer_name in self.viewer.layers:
                self.viewer.layers[objects_layer_name].data = colored_masks
            else:
                self.viewer.add_image(
                    colored_masks,
                    name=objects_layer_name,
                    rgb=True,
                    scale=scale,
                    translate=translate,
                    metadata={"source_file": file_name}
                )
        #print("Segmentation finished.")

        
        if self.analysis_data is not None:
            self.analysis_data["segmentation_results"] = self.segmentation_results
            #print("Segmentation results updated in analysis_data:", list(self.analysis_data["segmentation_results"].keys()))

    
    
    def analyze_cursor_mask(self):
        """
        Vectorized analysis of the cursor mask:
          - For each file in self.segmentation_results and for each time frame,
            compute for each active cursor:
              - The masked pixels for that object.
              - The ratio as masked_pixels divided by the total masked pixels for that object,
                where total masked pixels is computed as the sum over the logical OR of 
                all active cursor masks for that object.
          - Build a long-format DataFrame with one row per (File, Time, Object, Cursor)
            with columns: File, Time, Object, Total, Pixels, Ratio.
          - Then pivot the DataFrame.
          - Finally, add a "Group" column based on a file-to-group mapping stored in analysis_data.
        """
        # --- Refresh Analysis Data ---
        if self.phasor_widget is not None:
            self.analysis_data = self.phasor_widget.get_analysis_data()
            #print("Analysis data refreshed:")
            #print("Cursor settings:", self.analysis_data.get("cursor_settings"))
            #print("---- Cursor Mask Layers ----")
            cursor_mask_layers = self.analysis_data.get("cursor_mask_layers")
            if cursor_mask_layers:
                for file_name, layer in cursor_mask_layers.items():
                    try:
                        print(f"{file_name}: Layer name = {layer.name}, data shape = {layer.data.shape}")
                    except Exception as e:
                        print(f"Error accessing layer for {file_name}: {e}")
            else:
                print("No cursor mask layers found in analysis_data.")
        else:
            print("No phasor widget reference provided; cannot refresh analysis data.")
        
        # --- Retrieve active cursor settings ---
        if not self.analysis_data or "cursor_settings" not in self.analysis_data:
            print("No cursor settings available.")
            return None
        cursor_settings = self.analysis_data["cursor_settings"]
        active_cursors = [cs for cs in cursor_settings if cs["active"]]
        if not active_cursors:
            print("No active cursor settings found.")
            return None
        #print("Active cursor settings:", active_cursors)
        
        # --- Retrieve persistent cursor mask layers ---
        if not self.analysis_data or "cursor_mask_layers" not in self.analysis_data:
            print("No cursor mask layers available in analysis data.")
            return None
        
        
        # --- Handle case where segmentation was skipped ---
        if not self.segmentation_results:
            # Create a dummy segmentation: whole image as one object
            dummy = {}
            for fname, layer in cursor_mask_layers.items():
                mask = np.squeeze(layer.data, axis=1)  # shape (T, H, W, 4)
                T, H, W, _ = mask.shape
                dummy[fname] = np.ones((T, H, W), dtype=int)
            self.segmentation_results = dummy

        
        rows = []
        # Loop over each file in segmentation_results.
        for file_name, seg_masks in self.segmentation_results.items():
            #print(f"\nAnalyzing cursor mask for {file_name}:")
            # Retrieve the cursor mask layer for this file.
            cursor_layer = self.analysis_data.get("cursor_mask_layers", {}).get(file_name)
            if cursor_layer is None:
                print(f"No cursor mask layer found for {file_name}.")
                continue
            
            # Expected shape: (T, 1, H, W, 4); squeeze out the singleton axis.
            cursor_mask = np.squeeze(cursor_layer.data, axis=1)  # now shape (T, H, W, 4)
            #print("Cursor mask shape after squeeze:", cursor_mask.shape)
            #print("Segmentation masks shape:", seg_masks.shape)
            
            # Extract binary mask from alpha channel if applicable.
            if cursor_mask.ndim >= 3 and cursor_mask.shape[-1] == 4:
                binary_mask = cursor_mask[..., 3] > 128
            else:
                binary_mask = cursor_mask > 0
            #print("Binary cursor mask shape:", binary_mask.shape)
            
            # Check shape consistency.
            if binary_mask.shape != seg_masks.shape:
                print(f"Shape mismatch for {file_name}: segmentation {seg_masks.shape} vs binary mask {binary_mask.shape}")
                continue
            binary_mask = binary_mask.astype(bool)
            
            T = seg_masks.shape[0]
            # Process each time frame.
            for t in range(T):
                seg_flat = seg_masks[t].flatten()  # shape (H*W,)
                # Compute total counts for each label (includes background at index 0)
                total_counts = np.bincount(seg_flat)
                
                # --- Combine all active cursor masks for this frame ---
                combined_cursor_mask = np.zeros(seg_flat.shape, dtype=bool)
                cursor_mask_dict = {}  # Save each cursor's mask.
                for cs in active_cursors:
                    rgba_val = QColor(cs["color"]).getRgb()  # e.g., (R, G, B, A)
                    rgba_array = np.array(rgba_val)
                    # Build boolean mask for this cursor.
                    cursor_mask_this = np.all(cursor_mask[t] == rgba_array, axis=-1).flatten()
                    cursor_mask_dict[cs["color"]] = cursor_mask_this
                    combined_cursor_mask = combined_cursor_mask | cursor_mask_this
                
                # For each object label (exclude label 0)
                for label_val in range(1, len(total_counts)):
                    if total_counts[label_val] == 0:
                        continue
                    # Mask for the current object in this frame:
                    object_mask = (seg_flat == label_val)
                    # Total masked pixels for this object using the combined cursor mask:
                    overall_object_masked = np.sum(object_mask)
                    # If no masked pixels for this object, skip.
                    if overall_object_masked == 0:
                        continue
                    
                    # For each active cursor, compute its masked count for this object.
                    for cs in active_cursors:
                        cursor_mask_this = cursor_mask_dict[cs["color"]]
                        masked_pixels = np.sum(object_mask & cursor_mask_this)
                        ratio = masked_pixels / overall_object_masked if overall_object_masked > 0 else 0
                        rows.append({
                            "File": file_name,
                            "Time": t,
                            "Object": label_val,
                            "Total": overall_object_masked,
                            "Cursor": cs["color"],
                            "Pixels": masked_pixels,
                            "Ratio": ratio
                        })
        
        # Build long-format DataFrame.
        df_long = pd.DataFrame(rows)
        #print("Long-format Analysis DataFrame head:")
        #print(df_long.head())
        
        # --- Pivot to Wide Format ---
        df_wide = df_long.pivot_table(
            index=["File", "Time", "Object", "Total"],
            columns="Cursor",
            values=["Pixels", "Ratio"]
        )
        # Flatten multi-level columns.
        df_wide.columns = [f"{col[0]}_{col[1]}" for col in df_wide.columns.values]
        df_wide = df_wide.reset_index()
        #print("Pivoted Analysis DataFrame head:")
        #print(df_wide.head())
        
        # --- Add Group Column ---
        # Assume a file-to-group mapping is stored in analysis_data (e.g., from FileSelectionTable).
        if "file_group_mapping" in self.analysis_data:
            mapping = self.analysis_data["file_group_mapping"]
            df_wide["Group"] = df_wide["File"].map(mapping)
        else:
            print("No file_group_mapping found in analysis_data.")
        
        #print("Pivoted Analysis DataFrame with Group column head:")
        #print(df_wide.head())
        
        return df_wide
 

# ------------------- BACKEND FUNCTIONS -------------------
def create_time_series_figures(df_wide, cursors=None):
    """
    Create time-series figures (one per cursor) showing mean ± SEM over time for each group.
    The y-axis is fixed between 0 and 1.
    Returns a list of Bokeh figures.
    """
    df_wide["Time"] = pd.to_numeric(df_wide["Time"], errors="coerce")
    for cursor in cursors:
        df_wide[cursor] = pd.to_numeric(df_wide[cursor], errors="coerce")
    df_wide = df_wide.dropna(subset=["Time"])
    
    # Convert from wide to long
    df_long = df_wide.melt(
        id_vars=["Time", "Group"],
        value_vars=cursors,
        var_name="Cursor",
        value_name="Value"
    )
    
    # Mean, std, count, SEM
    stats_df = (
        df_long
        .groupby(["Time", "Group", "Cursor"], as_index=False)["Value"]
        .agg(mean_val="mean", std="std", count="count")
    )
    stats_df["sem"] = stats_df["std"] / np.sqrt(stats_df["count"])
    
    # Groups and color map
    groups = sorted(stats_df["Group"].dropna().unique())
    palette = ["#1f77b4", "#aec7e8", "#ff7f0e", "#ffbb78",
               "#2ca02c", "#98df8a", "#d62728", "#ff9896", "#9467bd", "#c5b0d5"]
    color_map = {g: palette[i % len(palette)] for i, g in enumerate(groups)}
    
    figures = []
    for cursor in cursors:
        fig = figure(
            width=800, height=600,
            title=f"Time Trend for {cursor}",
            x_axis_label="Time", y_axis_label=cursor,
            y_range=(0, 1),
            tools="pan,wheel_zoom,box_zoom,reset,save"
        )
        # Hover
        hover = HoverTool(tooltips=[
            ("Time", "@Time"),
            ("Mean Value", "@mean_val{0.2f}"),
            ("SEM", "@sem{0.2f}")
        ])
        fig.add_tools(hover)
        
        # Plot lines + whiskers
        for group in groups:
            sub_df = stats_df[(stats_df["Cursor"] == cursor) & (stats_df["Group"] == group)]
            if sub_df.empty:
                continue
            
            source = ColumnDataSource(sub_df)
            fig.line(
                x="Time", y="mean_val",
                source=source,
                color=color_map[group],
                legend_label=str(group),
                line_width=3
            )
            fig.scatter(
                x="Time", y="mean_val",
                source=source,
                color=color_map[group],
                size=8
            )
            source.data["upper"] = source.data["mean_val"] + source.data["sem"]
            source.data["lower"] = source.data["mean_val"] - source.data["sem"]
            whisker = Whisker(
                base="Time",
                upper="upper",
                lower="lower",
                source=source,
                line_color=color_map[group]
            )
            fig.add_layout(whisker)
        
        fig.legend.title = "Group"
        fig.legend.location = "top_left"
        figures.append(fig)
    
    return figures

def create_violin_figures(df_wide, cursors=None):
    """
    Create global violin plots (one per cursor) comparing the distribution of aggregated
    cursor values across groups, with statistical significance brackets showing p-values.
    
    If a group has only one value, a bar is drawn instead of a violin.
    """

    if cursors is None:
        cursors = [col for col in df_wide.columns if col.startswith("Ratio_")]
    
    df_copy = df_wide.copy()
    for cursor in cursors:
        df_copy[cursor] = pd.to_numeric(df_copy[cursor], errors="coerce")
    
    # Dynamically build the aggregation dictionary for the cursor columns.
    agg_dict = {cursor: "mean" for cursor in cursors}
    df_avg = df_copy.groupby(["Group", "Object"], as_index=False).agg(agg_dict)
    
    groups = sorted(df_avg["Group"].dropna().unique())
    palette = ["#1f77b4", "#aec7e8", "#ff7f0e", "#ffbb78",
               "#2ca02c", "#98df8a", "#d62728", "#ff9896", "#9467bd", "#c5b0d5"]
    color_map = {g: palette[i % len(palette)] for i, g in enumerate(groups)}
    
    figures = []
    for cursor in cursors:
        data_min = df_avg[cursor].min()
        data_max = df_avg[cursor].max()
        if data_min == data_max:
            data_min -= 0.05
            data_max += 0.05
        margin = 0.05 * (data_max - data_min)
        y_start = data_min - margin
        y_end   = data_max + margin
        
        x_mapping = {g: i+1 for i, g in enumerate(groups)}
        p = figure(
            width=800, height=600,
            title=f"Global Violin Plot for {cursor} (Aggregated)",
            x_range=(0.5, len(groups)+0.5),
            y_axis_label=cursor,
            tools="pan,wheel_zoom,box_zoom,reset,save"
        )
        p.xaxis.ticker = list(x_mapping.values())
        p.xaxis.major_label_overrides = {v: k for k, v in x_mapping.items()}
        p.y_range.start = y_start
        p.y_range.end = y_end
        
        # Plot each group as a violin + box plot or bar
        for g in groups:
            arr = df_avg.loc[df_avg["Group"] == g, cursor].dropna()
            x_center = x_mapping[g]
            if len(arr) == 1:
                # Draw a bar for the single value group
                y_val = arr.iloc[0]
                bar_width = 0.18
                p.vbar(x=x_center, top=y_val, width=bar_width, fill_color=color_map[g], line_color="black", alpha=0.8, legend_label=g)
                # Optional: also mark with a dot for clarity
                p.scatter(x=[x_center], y=[y_val], color="black", size=10)
                continue
            elif len(arr) < 2:
                continue
            # Violin + box plot
            q1 = np.percentile(arr, 25)
            q2 = np.median(arr)
            q3 = np.percentile(arr, 75)
            iqr = q3 - q1

            lw_box = max(y_start, q1 - 1.5 * iqr)
            uw_box = min(y_end,   q3 + 1.5 * iqr)

            lw_violin = max(y_start, q1 - 3.5 * iqr)
            uw_violin = min(y_end,   q3 + 3.5 * iqr)

            ys = np.linspace(lw_violin, uw_violin, 100)
            kde = gaussian_kde(arr)
            density = kde(ys)
            scale = 0.4 / density.max()
            dens_scaled = density * scale

            x_coords = np.concatenate([x_center - dens_scaled, x_center + dens_scaled[::-1]])
            y_coords = np.concatenate([ys, ys[::-1]])
            p.patch(
                x_coords, y_coords,
                fill_alpha=0.6,
                line_color=color_map[g],
                fill_color=color_map[g],
                legend_label=g
            )
            # Box
            p.rect(
                x=x_center,
                y=(q1 + q3) / 2,
                width=0.1,
                height=(q3 - q1),
                fill_color="white",
                line_color="black",
                fill_alpha=0.8
            )
            # Median line
            p.segment(
                x_center - 0.05, q2,
                x_center + 0.05, q2,
                line_color="black",
                line_width=2
            )
            # Whiskers
            p.segment(x_center, lw_box, x_center, q1, line_color="black")
            p.segment(x_center, q3, x_center, uw_box, line_color="black")
            p.segment(x_center - 0.01, lw_box, x_center + 0.01, lw_box, line_color="black")
            p.segment(x_center - 0.01, uw_box, x_center + 0.01, uw_box, line_color="black")
        
        # Statistical testing:
        if groups and all(g == "None" for g in groups):
            brackets = []
        else:
            # Only test when there are at least two groups with at least 2 values each
            eligible = [g for g in groups if len(df_avg.loc[df_avg["Group"] == g, cursor].dropna()) >= 2]
            if len(eligible) >= 3:
                from scipy.stats import f_oneway
                try:
                    group_data = [df_avg.loc[df_avg["Group"] == g, cursor].dropna() for g in eligible]
                    if len(group_data) >= 3:
                        F_stat, p_val = f_oneway(*group_data)
                        if p_val < 0.05:
                            x_left = min([x_mapping[g] for g in eligible])
                            x_right = max([x_mapping[g] for g in eligible])
                            brackets = [{
                                "x_left": x_left,
                                "x_right": x_right,
                                "level": 1,
                                "p_val": p_val
                            }]
                        else:
                            brackets = []
                    else:
                        brackets = []
                except Exception as e:
                    print(f"ANOVA test error for {cursor}: {e}")
                    brackets = []
            elif len(eligible) == 2:
                # Exactly two groups: use pairwise t-test.
                g1, g2 = eligible
                arr1 = df_avg.loc[df_avg["Group"] == g1, cursor].dropna()
                arr2 = df_avg.loc[df_avg["Group"] == g2, cursor].dropna()
                if len(arr1) >= 2 and len(arr2) >= 2:
                    try:
                        stat, p_val = ttest_ind(arr1, arr2)
                    except Exception as e:
                        print(f"Pairwise test error for {g1} vs {g2}: {e}")
                        p_val = None
                    if p_val is not None and p_val < 0.05:
                        x_left = x_mapping[g1]
                        x_right = x_mapping[g2]
                        brackets = [{
                            "x_left": x_left,
                            "x_right": x_right,
                            "level": 1,
                            "p_val": p_val
                        }]
                    else:
                        brackets = []
                else:
                    brackets = []
            else:
                brackets = []

        # Draw brackets if any.
        if brackets:
            max_level = max(b["level"] for b in brackets)
            p.y_range.end += (max_level + 1) * 0.05
            for b in brackets:
                y_bracket = p.y_range.start + (p.y_range.end - p.y_range.start) - b["level"] * 0.05
                p.line([b["x_left"], b["x_right"]], [y_bracket, y_bracket],
                       line_width=1, line_color="black")
                p.line([b["x_left"], b["x_left"]],
                       [y_bracket, y_bracket - 0.05/2],
                       line_width=1, line_color="black")
                p.line([b["x_right"], b["x_right"]],
                       [y_bracket, y_bracket - 0.05/2],
                       line_width=1, line_color="black")
                bracket_label = Label(
                    x=(b["x_left"] + b["x_right"]) / 2,
                    y=y_bracket + 0.05 * 0.15,
                    text=f"p={b['p_val']:.3g}",
                    text_font_size="10pt",
                    text_color="black",
                    text_align="center",
                    text_baseline="bottom"
                )
                p.add_layout(bracket_label)
        else:
            print(f"No significant differences (p < 0.05) for {cursor}.")
        
        p.legend.title = "Group"
        p.legend.location = "top_left"
        num_groups_with_multiple = sum(len(df_avg.loc[df_avg["Group"] == g, cursor].dropna()) > 1 for g in groups)
        num_groups_with_single = sum(len(df_avg.loc[df_avg["Group"] == g, cursor].dropna()) == 1 for g in groups)
        if num_groups_with_multiple == 0 and num_groups_with_single > 0:
            p.y_range.start = 0
            p.y_range.end = 1

        figures.append(p)
    
    return figures



def convert_fig_to_interactive(fig):
    #from bokeh.embed import components
    script, div = components(fig)
    return script + div

# ------------------- export utility functions ---------

def is_valid_segmentation(arr):
    """Return True if the mask has at least two unique values (so, not all 0), and contains at least one nonzero pixel."""
    if not isinstance(arr, np.ndarray) or arr.size == 0:
        return False
    labels = np.unique(arr)
    return (len(labels) > 1) and np.any(arr != 0)


# ------------------- EXPORT WIDGET -------------------
class ExportResultsWidget(QWidget):
    """Widget for selecting export options and generating an HTML report with interactive sliders."""
    def __init__(self, analysis_data=None, phasor_widget=None, segmentation_widget=None, parent=None):
        super().__init__(parent)
        self.setFont(QFont("Arial", 8))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(300)
        self.setStyleSheet("""
            QWidget {
                background-color: #282a36;
                color: #f8f8f2;
            }
            QGroupBox {
                border: 1px solid #707070;
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                                                  stop:0 #282a36, stop:1 #33353b);
                border-radius: 5px;
                margin-top: 10px;
                padding: 5px;
            }
            QGroupBox::title {
                color: #f8f8f2;
                left: 10px;
                padding: 0 5px;
            }
            QLineEdit {
                background-color: white;
                color: black;
                padding: 2px;
                border: 1px solid #707070;
            }
            QPushButton {
                background-color: #007acc;
                color: white;
                border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton:hover {
                background-color: #005f99;
            }
        """)
        layout = QVBoxLayout(self)
        
        # Store analysis data and phasor widget reference.
        self.analysis_data = analysis_data if analysis_data is not None else {}
        self.phasor_widget = phasor_widget
        self.segmentation_widget = segmentation_widget 
        
       
        # Set the path to your logo.
        segmentation_results = self.analysis_data.get("segmentation_results", {})
        #print("Segmentation results keys:", list(segmentation_results.keys()))
        
        # Group box for export options.
        self.groupbox = QGroupBox("Export Results")
        box_layout = QVBoxLayout()

        # Folder selection row.
        folder_layout = QHBoxLayout()
        folder_label = QLabel("Export Directory:")
        folder_layout.addWidget(folder_label)
        self.folder_line_edit = QLineEdit()
        self.folder_line_edit.setPlaceholderText("Select directory...")
        folder_layout.addWidget(self.folder_line_edit)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.select_export_folder)
        folder_layout.addWidget(browse_btn)
        box_layout.addLayout(folder_layout)

        # Export checkboxes.
        cb_layout = QHBoxLayout()
        self.export_intensity_cb = QCheckBox("Intensity")
        self.export_intensity_cb.setChecked(True)
        cb_layout.addWidget(self.export_intensity_cb)
        self.export_flim_cb = QCheckBox("FLIM")
        self.export_flim_cb.setChecked(True)
        cb_layout.addWidget(self.export_flim_cb)
        self.export_gs_cb = QCheckBox("G & S Masks")
        self.export_gs_cb.setChecked(True)
        cb_layout.addWidget(self.export_gs_cb)
        box_layout.addLayout(cb_layout)
        
        
        # Add a new checkbox for "Downstream Analysis"
        self.export_downstream_cb = QCheckBox("Downstream Analysis")
        self.export_downstream_cb.setChecked(False)
        box_layout.addWidget(self.export_downstream_cb)
        

        # Comparison group row.
        comp_layout = QHBoxLayout()
        comp_label = QLabel("Comparison Group:")
        comp_layout.addWidget(comp_label)
        self.comparison_combo = QComboBox()
        # Populate using the group_list from analysis_data.
        groups = self.analysis_data.get("group_list", ["Condition 1", "Condition 2", "Condition 3"])
        self.comparison_combo.addItems(groups)
        comp_layout.addWidget(self.comparison_combo)
        box_layout.addLayout(comp_layout)
        
    

        # Export button.
        export_btn = QPushButton("Export Results")
        export_btn.setFont(QFont("Arial", 12))
        export_btn.clicked.connect(self.export_results)
        box_layout.addWidget(export_btn)

        self.groupbox.setLayout(box_layout)
        layout.addWidget(self.groupbox)
        layout.addStretch()
        self.setLayout(layout)

        
        self.logo_path = get_logo_path()

    def select_export_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Export Folder")
        if folder:
            self.folder_line_edit.setText(folder)
  
    def update_comparison_combo(self, group_list):
        self.comparison_combo.clear()
        self.comparison_combo.addItems(group_list)
        #print("Comparison combo updated with:", group_list)

    
    @staticmethod
    def apply_turbo_colormap(img_float, pmin=10, pmax=90):
        """
        Apply the 'turbo' colormap to a 2D float image.
        Normalize using the pmin and pmax percentiles. If the range is too narrow,
        fall back to full range normalization.
        
        Parameters:
          img_float : 2D numpy array (float) – e.g. a lifetime image.
          pmin : lower percentile (default 10)
          pmax : upper percentile (default 90)
          
        Returns:
          An (H, W, 3) uint8 RGB image.
        """
        
        lower = np.nanpercentile(img_float, pmin)
        upper = np.nanpercentile(img_float, pmax)
        #print(f"apply_turbo_colormap: p{pmin} = {lower}, p{pmax} = {upper}")
        
        # If the range is nearly zero, fall back to full range.
        if np.isclose(upper, lower, atol=1e-3):
            lower = np.nanmin(img_float)
            upper = np.nanmax(img_float)
            #print(f"Falling back: min = {lower}, max = {upper}")
        
        # Normalize image to [0, 1]
        norm_img = (img_float - lower) / (upper - lower + 1e-8)
        norm_img = np.clip(norm_img, 0, 1)
        
        # Apply the turbo colormap
        turbo_cmap = cm.get_cmap("turbo")
        rgba = turbo_cmap(norm_img)  # Returns an array in [0,1] with shape (H, W, 4)
        rgb = (rgba[..., :3] * 255).astype(np.uint8)
        return rgb


    
    @staticmethod
    def composite_on_black(rgba):
        """
        Composite an RGBA image onto a black background, returning an RGB image.
        """
        r = rgba[..., 0].astype(np.float32)
        g = rgba[..., 1].astype(np.float32)
        b = rgba[..., 2].astype(np.float32)
        a = rgba[..., 3].astype(np.float32) / 255.0
        out_r = r * a
        out_g = g * a
        out_b = b * a
        out_rgb = np.dstack((out_r, out_g, out_b)).astype(np.uint8)
        return out_rgb
    
    def generate_interactive_plot_summaries(self, df_downstream):
        """
        Generate interactive plot summaries from the downstream analysis DataFrame.
        This method calls the interactive plotting functions to build Bokeh figures
        and then converts the first time-series and violin figures into HTML snippets.
        The violin plots include pairwise significance brackets with both * grading and the p-value.
        Returns a dictionary with keys:
           - "time_trend": HTML snippet for the time-resolved plot,
           - "global_violin": HTML snippet for the global violin plot.
        """
        # Dynamically determine the cursor columns.
        ratio_cols = [col for col in df_downstream.columns if col.startswith("Ratio_")]
        if not ratio_cols:
            print("No ratio columns found in the downstream DataFrame.")
            return {}
        
        # Generate Bokeh figures for time trend and violin plots.
        time_figs = create_time_series_figures(df_downstream, cursors=ratio_cols)
        violin_figs = create_violin_figures(df_downstream, 
                                            cursors=ratio_cols)
        
        # Build a summary dictionary mapping each cursor column to its interactive HTML snippets.
        interactive_summary = {}
        for idx, cursor in enumerate(ratio_cols):
            # Make sure that the figure index exists.
            if idx < len(time_figs) and idx < len(violin_figs):
                interactive_summary[cursor] = {
                    "time_trend": convert_fig_to_interactive(time_figs[idx]),
                    "global_violin": convert_fig_to_interactive(violin_figs[idx])
                }
            else:
                print(f"Warning: Missing figure for {cursor}.")
        return interactive_summary
    
    # WIP
    def _generate_new_plots(self):
        import seaborn as sns
        from statsmodels.formula.api import ols
        import matplotlib.pyplot as plt
        import statsmodels.api as sm
        import itertools as it
        import starbars
        df_wide = self.segmentation_widget.analyze_cursor_mask()
        cursor_settings = self.analysis_data.get("cursor_settings", [])
        active_cursors = [cs["color"] for cs in cursor_settings if cs.get("active")]
        fig_dir = os.path.join(self.folder_line_edit.text(), "figures")
        lms = {}
        anova_res = {}
        for c in active_cursors:
            lms[c] = ols("Ratio_"+c+" ~ Group", data = df_wide).fit()
            anova_res[c] = sm.stats.anova_lm(lms[c], typ=2)

        n_cursor = len(active_cursors)
        f, axs = plt.subplots(1, n_cursor, figsize=(8*n_cursor,8))
        order = self.phasor_widget.file_selection_widget.get_file_group_mapping().values()
        order = [*{*order}]
        flima_palette = ["#1f77b4", "#aec7e8", "#ff7f0e", "#ffbb78", "#2ca02c", "#98df8a", "#d62728", "#ff9896", "#9467bd", "#c5b0d5"]
        sig = [list(lm.t_test_pairwise("Group").result_frame["P>|t|"]) for lm in lms.values()]
        print(sig)
        annotations = [[(o[0], o[1], float(s[i])) for i,o in enumerate(it.combinations(order, 2))] for s in sig]
        print(annotations)
        for i,c in enumerate(active_cursors):
            sns.violinplot(data = df_wide, x = "Group", y = "Ratio_"+c, bw_adjust=.5, cut=1, linewidth=1, palette=flima_palette, ax=axs[i])
            starbars.draw_annotation(annotations[0], ax=axs[i])
        f.set_dpi(400)
        plt.savefig(os.path.join(fig_dir, "violin.png"))

        file_groups = self.analysis_data['file_group_mapping']
        group_summary = {}
        for file,group in file_groups.items():
            f2, ax2 = plt.subplots(figsize=(8,8))
            f2.set_dpi(400)
            intensity = self.analysis_data['file_gs_data'][file]['intensity']
            shape = intensity.shape
            intensity = intensity.reshape(shape[0], shape[1]*shape[2])
            sns.histplot(data = intensity.T, palette=flima_palette, log_scale=True, ax = ax2)
            plt.savefig(os.path.join(fig_dir, file+"intensity_kde.png"))
            if group_summary.get(group) is not None:
                group_summary[group] = group_summary[group].append(list(describe(intensity)))
            else:
                group_summary[group] = [describe(intensity)]
        with open(os.path.join(fig_dir, 'descriptive_statistics.txt'), 'w') as f:
            print(group_summary, file=f)

        summary_intensity = np.array([np.clip(self.analysis_data['file_gs_data'][f]['intensity'].flatten(), a_min=0.001, a_max = None) for f in file_groups.keys()])
        f4, ax4 = plt.subplots(figsize=(8,8))
        f4.set_dpi(400)
        sns.kdeplot(summary_intensity.T, log_scale=True, palette=flima_palette, ax=ax4)
        plt.savefig(os.path.join(fig_dir, "intensity_summary_kde.png"))

        for g in order:
            grouped_intensity = np.array([np.clip(self.analysis_data['file_gs_data'][f]['intensity'].flatten(), a_min=0.001, a_max = None) for f in file_groups.keys() if file_groups[f] == g])
            f3, ax3 = plt.subplots(figsize=(8,8))
            f3.set_dpi(400)
            sns.kdeplot(grouped_intensity.T, log_scale=True, palette=flima_palette, ax=ax3)
            plt.savefig(os.path.join(fig_dir, g+"_intensity_summary_kde.png"))
        


    def export_results(self):
        """
        Exports results to a subfolder named "FLIMa" within the selected directory:
          - Exports intensity, FLIM, and cursor mask images for each file.
          - If "Downstream Analysis" is checked, also exports:
              - Segmentation images (from segmentation_results stored in analysis_data).
              - The wide-format analysis DataFrame (obtained via analyze_cursor_mask() from the segmentation widget) as CSV,
                and includes a scrollable HTML table of the DataFrame in the report.
          - Also includes the cursor information table in the phasor distribution section.
        """
      
        if self.phasor_widget is not None:
            new_data = self.phasor_widget.get_analysis_data()
            if self.segmentation_widget is not None:
                seg_data = self.segmentation_widget.segmentation_results
                if seg_data:
                    new_data["segmentation_results"] = seg_data
                    #print("Merged segmentation_results from segmentation widget:", list(seg_data.keys()))
            self.analysis_data = new_data
            #print("Export: Analysis data refreshed:")
            #print("Cursor settings:", self.analysis_data.get("cursor_settings"))

        
        # Get active cursor settings.
        cursor_settings = self.analysis_data.get("cursor_settings", [])
        active_cursors = [cs for cs in cursor_settings if cs.get("active")]
        if not active_cursors:
            print("No active cursor settings found.")
            return
        #print("Active cursor settings:", active_cursors)
        
        
        
        # Check export folder.
        export_dir = self.folder_line_edit.text()
        if not export_dir:
            print("No export folder selected.")
            return
        
        # Create output directory.
        output_dir = os.path.join(export_dir, "FLIMa")
        os.makedirs(output_dir, exist_ok=True)
        #print(f"Export folder created: {output_dir}")
        
        # Copy the logo file.
        logo_filename = 'logo.png'
        logo_src = self.logo_path
        logo_dst  = os.path.join(output_dir, logo_filename)
        try:
            shutil.copyfile(logo_src, logo_dst)
        except FileNotFoundError:
            # resource wasn’t found in the package—skip or log a warning
            print(f"Logo not found at {logo_src}, skipping copy.")
        except Exception as e:
            print(f"Error copying logo from {logo_src}: {e}")
            
        
        # Retrieve analysis data parts.
        file_gs_data = self.analysis_data.get("file_gs_data", {})
        lifetime_layers = self.analysis_data.get("lifetime_layers", {})
        cursor_mask_layers = self.analysis_data.get("cursor_mask_layers", {})
        
        # Determine if downstream analysis is to be exported.
        do_downstream = self.export_downstream_cb.isChecked() if hasattr(self, "export_downstream_cb") else False
        
        # Retrieve segmentation results from analysis_data.
        # --- Filter segmentation_results ONCE ---
        raw_segmentation_results = self.analysis_data.get("segmentation_results", {})
        
        def to_base_name(k):
            return os.path.splitext(os.path.basename(k))[0]
        
        segmentation_results = {}
        if do_downstream and raw_segmentation_results:
            for k, v in raw_segmentation_results.items():
                bname = to_base_name(k)
                if is_valid_segmentation(v):
                    segmentation_results[bname] = v
        print("segmentation_results after filtering:", list(segmentation_results.keys()))
        
        # --- Export Images for Each File ---
        report_files = []
        for file_name, data in file_gs_data.items():
            base_name = os.path.splitext(os.path.basename(file_name))[0]
            file_output_dir = os.path.join(output_dir, base_name)
            os.makedirs(file_output_dir, exist_ok=True)
            #print(f"Created folder for {base_name}: {file_output_dir}")
        
            # Export intensity images.
            if self.export_intensity_cb.isChecked():
                intensity = data.get("intensity")
                if intensity is not None:
                    # Handle both 2D and 3D intensity arrays robustly
                    if intensity.ndim == 2:
                        # Only one frame; save as t=0
                        out_path = os.path.join(file_output_dir, "intensity_0.png")
                        img = intensity
                        if type(img) != np.uint8:
                            img = img.astype(np.uint8)
                        imageio.imwrite(out_path, img)
                    elif intensity.ndim == 3:
                        T = intensity.shape[0]
                        for t in range(T):
                            img = np.squeeze(intensity[t])
                            if img.ndim != 2:
                                raise ValueError(f"Cannot save intensity image with shape {img.shape}; must be 2D.")
                            out_path = os.path.join(file_output_dir, f"intensity_{t}.png")
                            imageio.imwrite(out_path, img)
                    else:
                        print(f"Warning: Unexpected intensity shape {intensity.shape} for {file_name}. Skipping export.")
                else:
                    print(f"No intensity data for {file_name}.")


            
            if self.export_flim_cb.isChecked():
                lifetime_layer = lifetime_layers.get(file_name)
                if lifetime_layer is not None:
                    lifetime_data = lifetime_layer.data  # Expected shape: (T, 1, H, W) or (H, W)
                    # Squeeze singleton axes but keep at least 3D for multi-frame
                    if lifetime_data.ndim == 2:
                        # Only one frame, (H, W)
                        imgs_to_save = [lifetime_data]
                    elif lifetime_data.ndim == 3:
                        # Already (T, H, W)
                        imgs_to_save = [lifetime_data[t] for t in range(lifetime_data.shape[0])]
                    elif lifetime_data.ndim == 4:
                        # Squeeze the channel axis if present (T, 1, H, W)
                        if lifetime_data.shape[1] == 1:
                            lifetime_data = np.squeeze(lifetime_data, axis=1)  # Now (T, H, W)
                            imgs_to_save = [lifetime_data[t] for t in range(lifetime_data.shape[0])]
                        else:
                            raise ValueError(f"Cannot handle FLIM lifetime array shape {lifetime_data.shape}")
                    else:
                        raise ValueError(f"Unexpected FLIM lifetime data shape {lifetime_data.shape}")
            
                    for t, img in enumerate(imgs_to_save):
                        valid = ~np.isnan(img)
                        if np.any(valid):
                            lower = np.nanpercentile(img[valid], 10)
                            upper = np.nanpercentile(img[valid], 90)
                        else:
                            lower, upper = np.nanmin(img), np.nanmax(img)
                        norm_img = (img - lower) / (upper - lower + 1e-8)
                        norm_img = np.clip(norm_img, 0, 1)
                        rgb_turbo = self.apply_turbo_colormap(norm_img, pmin=0, pmax=100)
                        img_to_save = np.squeeze(rgb_turbo)
                        if img_to_save.ndim not in (2, 3):
                            raise ValueError(f"Cannot save FLIM image with shape {img_to_save.shape}; must be 2D or 3D (RGB).")
                        out_path = os.path.join(file_output_dir, f"lifetime_{t}.png")
                        imageio.imwrite(out_path, img_to_save)
                else:
                    print(f"No lifetime layer for {file_name}.")

        
            # Export cursor mask images.
            if self.export_gs_cb.isChecked():
                cursor_layer = cursor_mask_layers.get(file_name)
                if cursor_layer is not None:
                    cursor_data = cursor_layer.data  # Expected shape: (T, 1, H, W, 4), (T, H, W, 4), (H, W, 4), etc.
            
                    # Handle all possible shapes robustly
                    if cursor_data.ndim == 5 and cursor_data.shape[1] == 1:
                        # Squeeze singleton channel: (T, 1, H, W, 4) -> (T, H, W, 4)
                        cursor_data = np.squeeze(cursor_data, axis=1)
            
                    # Single-frame: (H, W, 4)
                    if cursor_data.ndim == 3 and cursor_data.shape[-1] in (3, 4):
                        masks_to_save = [cursor_data]
                    # Multi-frame: (T, H, W, 4)
                    elif cursor_data.ndim == 4 and cursor_data.shape[-1] in (3, 4):
                        masks_to_save = [cursor_data[t] for t in range(cursor_data.shape[0])]
                    else:
                        raise ValueError(f"Unexpected cursor mask shape {cursor_data.shape}")
            
                    for t, rgba in enumerate(masks_to_save):
                        composited = self.composite_on_black(rgba)
                        img = np.squeeze(composited)
                        if img.ndim not in (2, 3):
                            raise ValueError(f"Cannot save mask image with shape {img.shape}; must be 2D or 3D (RGB/RGBA).")
                        out_path = os.path.join(file_output_dir, f"mask_{t}.png")
                        imageio.imwrite(out_path, img)
                else:
                    print(f"No cursor mask layer for {file_name}.")

          
        
            # --- Export Segmentation Images if Downstream is Enabled ---

            seg_masks = segmentation_results.get(base_name, None)
            has_valid_segmentation = do_downstream and is_valid_segmentation(seg_masks)
            
            if has_valid_segmentation:
                if seg_masks.ndim == 2:
                    masks_to_save = [seg_masks]
                elif seg_masks.ndim == 3:
                    masks_to_save = [seg_masks[t] for t in range(seg_masks.shape[0])]
                else:
                    raise ValueError(f"Unexpected segmentation mask shape {seg_masks.shape}")
                for t, mask in enumerate(masks_to_save):
                    seg_image = label2rgb(mask, bg_label=0)
                    img = np.squeeze((seg_image * 255).astype(np.uint8))
                    if img.ndim not in (2, 3):
                        raise ValueError(f"Cannot save segmentation image with shape {img.shape}; must be 2D or 3D (RGB).")
                    out_path = os.path.join(file_output_dir, f"segmentation_{t}.png")
                    imageio.imwrite(out_path, img)
            else:
                print(f"No valid segmentation for {base_name} -- skipping segmentation export.")

    
            intensity_data = data.get("intensity")
            num_frames = intensity_data.shape[0] if intensity_data is not None else 0
            report_files.append({
                "name": base_name,
                "num_frames": num_frames,
                "has_segmentation": has_valid_segmentation,
            })
        
        # --- Save Phasor Plot Frames ---
        phasor_output_dir = os.path.join(output_dir, "phasor")
        os.makedirs(phasor_output_dir, exist_ok=True)
        if self.phasor_widget is not None and self.phasor_widget.dialog is not None:
            self.phasor_widget.dialog.save_all_phasor_frames(phasor_output_dir)
            num_phasor_frames = len(self.phasor_widget.dialog.frames)
        else:
            num_phasor_frames = 0
        
        # --- Downstream Analysis DataFrame ---
        # Use the segmentation widget's analyze_cursor_mask() if available.
        if do_downstream and self.segmentation_widget is not None and hasattr(self.segmentation_widget, "analyze_cursor_mask"):
            df_wide = self.segmentation_widget.analyze_cursor_mask()
        else:
            df_wide = None
        if do_downstream and df_wide is not None:
            csv_path = os.path.join(output_dir, "downstream_analysis.csv")
            try:
                df_wide.to_csv(csv_path, index=False)
                webbrowser.open(csv_path) # untested on Linux or OSX, relies on unsupported funtinality
                #print(f"Downstream analysis CSV saved: {csv_path}")
            except Exception as e:
                print(f"Error saving downstream analysis CSV: {e}")
            downstream_table = df_wide.to_html(index=False, classes="analysis-table")
        else:
            downstream_table = ""
        
        # --- Generate Interactive Plot Summaries if downstream_table was generated ---
        if downstream_table != "":
            # Here we assume the downstream DataFrame is available as df_wide
            interactive_plots = self.generate_interactive_plot_summaries(df_wide)
        else:
            interactive_plots = {}
        self.analysis_data["plot_summary"] = interactive_plots      
    
        
        # --- Build Report Data ---
        report_data = {
            "title": "FLIMa Summary Report",
            "logo_filename": logo_filename,
            "files": report_files,
            "num_phasor_frames": num_phasor_frames,
            "cursors": active_cursors,
            "do_downstream": do_downstream,
            "downstream_table": downstream_table,
            "plot_summary": self.analysis_data.get("plot_summary", {})
        }
        
        
        # --- Build HTML Report ---
        # NOTE: The cursor information table has been restored below in the phasor distribution section.
        
        template_str = r"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
          <meta charset="utf-8">
          <title>{{ title }}</title>
        
          <!-- MathJax for LaTeX equations -->
          <script src="https://polyfill.io/v3/polyfill.min.js?features=es6"></script>
          <script id="MathJax-script" async
            src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js">
          </script>
          
          <!-- BokehJS Resources -->
          <link href="https://cdn.bokeh.org/bokeh/release/bokeh-3.7.0.min.css" rel="stylesheet" type="text/css">
          <script src="https://cdn.bokeh.org/bokeh/release/bokeh-3.7.0.min.js"></script>
  
        
          <style>
            body {
              margin: 0; padding: 0; display: flex; background-color: #f5f5f5; font-family: Arial, sans-serif;
            }
            /* Sticky Sidebar */
            .sidebar {
              position: sticky; top: 0; width: 240px; background-color: #282a36; color: #f8f8f2;
              height: 100vh; overflow-y: auto; padding: 20px; box-sizing: border-box;
            }
            .sidebar img {
              display: block; margin: 0 auto 15px auto; height: 50px;
            }
            .sidebar h2 {
              font-size: 1.6em; margin: 0 0 10px 0; text-align: center;
            }
            .sidebar ul { list-style: none; padding-left: 0; margin-left: 0; }
            .sidebar li { margin: 6px 0; cursor: pointer; color: #61dafb; }
            .sidebar li:hover { text-decoration: underline; }
            /* Indent sub-items */
            .sidebar ul ul {
              margin-left: 15px;
              margin-top: 4px;
              margin-bottom: 4px;
            }
        
            /* Main Content */
            .content { flex: 1; padding: 20px; overflow-y: auto; }
            header {
              display: flex; align-items: center; border-bottom: 3px solid #007acc; padding-bottom: 20px; margin-bottom: 30px;
            }
            header img { height: 140px; margin-right: 30px; }
            header h1 { color: #007acc; margin: 0; font-size: 4.5em; line-height: 1.2; }
        
            .section {
              margin-bottom: 40px; background-color: white; padding: 20px; border-radius: 8px;
              box-shadow: 0 2px 5px rgba(0,0,0,0.1);
            }
            .section h2 { font-size: 2em; color: #007acc; border-bottom: 2px solid #007acc; padding-bottom: 10px; margin-bottom: 20px; }
            .subsection h3 { font-size: 1.6em; color: #333; margin-bottom: 10px; }
        
            .img-table { width: 100%; border-collapse: collapse; text-align: center; margin-bottom: 15px; }
            .img-table th, .img-table td { padding: 5px; border: 1px solid #ddd; }
            .img-table th {
              background-color: #007acc; 
              color: white; 
              font-size: 1.1em; 
              white-space: nowrap;
            }
            .img-table img {
              max-width: 360px; 
              height: auto; 
              margin: 2px; 
              border: 1px solid #ccc; 
              border-radius: 4px;
            }
        
            /* Example: multiple images side by side */
            .segmentation-row {
              display: flex;
              flex-wrap: wrap;
              gap: 20px; /* space between images */
              justify-content: center;
              align-items: center;
              margin-bottom: 15px;
            }
            .segmentation-row img {
              max-width: 400px; /* adjust as needed */
              border: 1px solid #ccc;
              border-radius: 4px;
            }
        
            .frame-controls { text-align: center; margin-top: 10px; }
            .frame-controls input[type=range] { width: 60%; }
            .frame-controls input[type=number] { width: 60px; font-size: 1em; text-align: center; }
        
            .cursor-table { width: 100%; border-collapse: collapse; text-align: center; margin-top: 20px; }
            .cursor-table th, .cursor-table td { padding: 5px; border: 1px solid #ddd; }
            .cursor-table th {
              background-color: #007acc; 
              color: white; 
              font-size: 1em;
              white-space: nowrap;
            }
            /* For a color swatch in the table */
            .color-swatch {
              display: inline-block;
              width: 20px;
              height: 20px;
              margin-right: 6px;
              border-radius: 4px;
              vertical-align: middle;
              border: 1px solid #ccc;
            }
        
            .analysis-table { margin-top: 20px; border-collapse: collapse; width: 100%; }
            .analysis-table th, .analysis-table td { border: 1px solid #ddd; padding: 8px; text-align: center; }
            .analysis-table th { background-color: #007acc; color: white; }
          </style>
        
          <script>
            function updateFrame(base, maxFrames, sliderId, numberId) {
              var slider = document.getElementById(sliderId);
              var numberInput = document.getElementById(numberId);
              var t = slider.value;
              numberInput.value = t;
              document.getElementById("intensity_" + base).src = base + "/intensity_" + t + ".png";
              document.getElementById("lifetime_" + base).src = base + "/lifetime_" + t + ".png";
              document.getElementById("mask_" + base).src = base + "/mask_" + t + ".png";
            }
            function setFrameFromNumber(base, maxFrames, sliderId, numberId) {
              var slider = document.getElementById(sliderId);
              var numberInput = document.getElementById(numberId);
              slider.value = numberInput.value;
              updateFrame(base, maxFrames, sliderId, numberId);
            }
            function updateDownstreamFrame(base, maxFrames, sliderId, numberId) {
              var slider = document.getElementById(sliderId);
              var numberInput = document.getElementById(numberId);
              var t = slider.value;
              numberInput.value = t;
              document.getElementById("segmentation_" + base).src = base + "/segmentation_" + t + ".png";
            }
            function setDownstreamFrameFromNumber(base, maxFrames, sliderId, numberId) {
              var slider = document.getElementById(sliderId);
              var numberInput = document.getElementById(numberId);
              slider.value = numberInput.value;
              updateDownstreamFrame(base, maxFrames, sliderId, numberId);
            }
          </script>
        </head>
        <body>
          <!-- Sticky Sidebar -->
          <div class="sidebar">
            <img src="{{ logo_filename }}" alt="Sidebar Logo">
            <h2>Contents</h2>
            <ul>
              <li onclick="document.getElementById('data_overview').scrollIntoView();">Data Overview</li>
              <ul>
                {% for file in files %}
                <li onclick="document.getElementById('{{ file.name }}').scrollIntoView();">{{ file.name }}</li>
                {% endfor %}
              </ul>
              <li onclick="document.getElementById('phasor_distribution').scrollIntoView();">Phasor Distribution</li>
              <ul>
                <li onclick="document.getElementById('cursor_info').scrollIntoView();">Cursor Information</li>
              </ul>
              {% if do_downstream %}
              <li onclick="document.getElementById('downstream_analysis').scrollIntoView();">Downstream Analysis</li>
              <ul>
                {% for file in files %}
                <li onclick="document.getElementById('downstream_{{ file.name }}').scrollIntoView();">{{ file.name }}</li>
                {% endfor %}
                <li onclick="document.getElementById('downstream_table').scrollIntoView();">Analysis Results</li>
              </ul>
              {% endif %}
              <!-- New: Interactive Plots link -->
              <li onclick="document.getElementById('interactive_plots').scrollIntoView();">Interactive Plots</li>
            </ul>
          </div>
        
          <!-- Main Content -->
          <div class="content">
            <header>
              <img src="{{ logo_filename }}" alt="Main Logo">
              <h1>{{ title }}</h1>
            </header>
        
            <!-- Data Overview Section -->
            <div class="section" id="data_overview">
              <h2>Data Overview</h2>
              <p>Below are the exported images for each file. Use the sliders to navigate through the time frames.</p>
              {% for file in files %}
              <div class="subsection" id="{{ file.name }}">
                <h3>{{ file.name }}</h3>
                <table class="img-table">
                  <tr>
                    <th>Intensity</th>
                    <th>Lifetime</th>
                    <th>Cursor Mask</th>
                  </tr>
                  <tr>
                    <td><img id="intensity_{{ file.name }}" src="{{ file.name }}/intensity_0.png" alt="Intensity"></td>
                    <td><img id="lifetime_{{ file.name }}" src="{{ file.name }}/lifetime_0.png" alt="Lifetime"></td>
                    <td><img id="mask_{{ file.name }}" src="{{ file.name }}/mask_0.png" alt="Cursor Mask"></td>
                  </tr>
                </table>
                <div class="frame-controls">
                  Frame:
                  <input id="slider_{{ file.name }}" type="range" min="0" max="{{ file.num_frames - 1 }}" value="0"
                         onchange="updateFrame('{{ file.name }}', {{ file.num_frames }}, 'slider_{{ file.name }}', 'number_{{ file.name }}')">
                  <input id="number_{{ file.name }}" type="number" min="0" max="{{ file.num_frames - 1 }}" value="0"
                         onchange="setFrameFromNumber('{{ file.name }}', {{ file.num_frames }}, 'slider_{{ file.name }}', 'number_{{ file.name }}')">
                </div>
              </div>
              {% endfor %}
            </div>
        
            <!-- Phasor Distribution Section -->
            <div class="section" id="phasor_distribution">
              <h2>Phasor Distribution</h2>
              <p>
                The <strong>phasor plot</strong> is a powerful representation of fluorescence decays.
                Below are the definitions:
              </p>
              <p>
                <strong>Time-Domain Definition</strong> (Fourier transform of the decay):<br>
                \[
                  g = \frac{\int_{0}^{\infty} I(t) \cos(\omega t) \, dt}{\int_{0}^{\infty} I(t) \, dt},\quad
                  s = \frac{\int_{0}^{\infty} I(t) \sin(\omega t) \, dt}{\int_{0}^{\infty} I(t) \, dt}.
                \]
              </p>
              <p>
                <strong>Frequency-Domain Definition</strong>: In frequency-domain FLIM, one measures a 
                <em>modulation ratio</em> \(M\) and a <em>phase delay</em> \(\phi\). Then the phasor coordinates are given by:<br>
                \[
                  g = M \cos(\phi),\quad s = M \sin(\phi).
                \]
              </p>
              <p>
                On the <em>universal circle</em>, shorter lifetimes appear toward the right (higher \(g\) values) while longer lifetimes shift left.
              </p>
              <p>
                From \(g\) and \(s\), the <em>modulation lifetime</em> \(\tau_m\) and <em>phase lifetime</em> \(\tau_p\)
                can be computed as:
              </p>
              <p style="text-align:center;">
                \[
                  \tau_m = \frac{1}{\omega}\sqrt{\frac{1}{m^2} - 1},\quad
                  \tau_p = \frac{1}{\omega}\tan(\phi),
                \]
                where \(m = \sqrt{g^2+s^2}\) and \(\omega=2\pi f\).
              </p>
              <div style="text-align:center;">
                <img id="phasor_img" src="phasor/phasor_0.png" alt="Phasor Plot"
                     style="max-width:600px; border:1px solid #ccc; border-radius:4px;">
              </div>
              <div class="frame-controls" style="text-align:center; margin-top:10px;">
                Frame:
                <input id="phasor_slider" type="range" min="0" max="{{ num_phasor_frames - 1 }}" value="0"
                       onchange="document.getElementById('phasor_img').src='phasor/phasor_'+this.value+'.png'">
                <input id="phasor_number" type="number" min="0" max="{{ num_phasor_frames - 1 }}" value="0"
                       onchange="document.getElementById('phasor_slider').value=this.value; document.getElementById('phasor_img').src='phasor/phasor_'+this.value+'.png'">
              </div>
            </div>
        
            <!-- Cursor Information Section -->
            <div class="section" id="cursor_info">
              <h2>Cursor Information</h2>
              <table class="cursor-table">
                <tr>
                  <th>Cursor #</th>
                  <th>Color</th>
                  <th>Radius</th>
                  <th>G</th>
                  <th>S</th>
                  <th>τ<sub>m</sub></th>
                  <th>τ<sub>p</sub></th>
                </tr>
                {% for c in cursors %}
                <tr>
                  <td>{{ loop.index }}</td>
                  <td>
                    <span class="color-swatch" style="background-color: {{ c.color }};"></span>
                    {{ c.color }}
                  </td>
                  <td>{{ "%.2f"|format(c.radius) }}</td>
                  <td>{{ "%.2f"|format(c.g_value) }}</td>
                  <td>{{ "%.2f"|format(c.s_value) }}</td>
                  <td>{{ "%.2f"|format(c.tau_m) }}</td>
                  <td>{{ "%.2f"|format(c.tau_p) }}</td>
                </tr>
                {% endfor %}
              </table>
            </div>
        
            <!-- Downstream Analysis Section (if enabled) -->
            {% if do_downstream %}
            <div class="section" id="downstream_analysis">
              <h2>Downstream Analysis</h2>
              <p>This section displays the segmentation images and the pivoted analysis DataFrame below.</p>
              {% for file in files %}
                {% if file.has_segmentation %}
                <div class="subsection" id="downstream_{{ file.name }}">
                  <h3>{{ file.name }}</h3>
                  <div class="segmentation-row">
                    <img id="segmentation_{{ file.name }}" src="{{ file.name }}/segmentation_0.png" alt="Segmentation">
                  </div>
                  <div class="frame-controls">
                    Frame:
                    <input id="downstream_slider_{{ file.name }}" type="range" min="0" max="{{ file.num_frames - 1 }}" value="0"
                           onchange="updateDownstreamFrame('{{ file.name }}', {{ file.num_frames }}, 'downstream_slider_{{ file.name }}', 'downstream_number_{{ file.name }}')">
                    <input id="downstream_number_{{ file.name }}" type="number" min="0" max="{{ file.num_frames - 1 }}" value="0"
                           onchange="setDownstreamFrameFromNumber('{{ file.name }}', {{ file.num_frames }}, 'downstream_slider_{{ file.name }}', 'downstream_number_{{ file.name }}')">
                  </div>
                </div>
                {% endif %}
              {% endfor %}
              {% if downstream_table %}
              <h3>Analysis Results</h3>
              <div class="analysis-table-container" style="overflow-x:auto; max-height:400px; overflow-y:auto;">
                {{ downstream_table|safe }}
              </div>
              {% endif %}
            </div>
            {% endif %}

        
            <!-- New: Interactive Plot Summaries Section -->
            <div class="section" id="interactive_plots">
              <h2>Interactive Plot Summaries</h2>
              {% if plot_summary %}
                {% for cursor, plots in plot_summary.items() %}
                  <h3>Time Trend for {{ cursor }}</h3>
                  {{ plots.time_trend|safe }}
                  <h3>Global Violin for {{ cursor }}</h3>
                  {{ plots.global_violin|safe }}
                {% endfor %}
              {% else %}
                <p>No interactive plots available.</p>
              {% endif %}
            </div>
        
            <div class="footer">
              <p>Generated by FLIMa.</p>
            </div>
          </div>
        </body>
        </html>
        """
        
        # Create a Jinja2 Template instance.
        template = Template(template_str)
        
        # Render the template using unpacked report_data.
        try:
            html_output = template.render(**report_data)
            report_path = os.path.join(output_dir, "FLIMa_report.html")
            with open(report_path, "w", encoding="utf-8") as f:
                f.write(html_output)
            #print(f"HTML report generated: {report_path}")
        except Exception as e:
            print(f"Error writing HTML report: {e}")
        
        # print("Exporting results to:", output_dir)
        # print("Export intensity images:", self.export_intensity_cb.isChecked())
        # print("Export FLIM images:", self.export_flim_cb.isChecked())
        # print("Export G & S masks:", self.export_gs_cb.isChecked())
        # print("Comparison group selected:", self.comparison_combo.currentText())
        print("Export complete.")



# ------------------- MAIN PARENT SEGMENTATION WIDGET -------------------  
 
class MainSegmentationWidget(QWidget):
    """
    Main widget that integrates the segmentation parameters and export results widgets.
    It accepts analysis data (passed from the phasor widget) so that segmentation can be applied
    on the intensity data from active files. The resulting tracked objects layer is named "<base>_objects".
    Additionally, it provides a refresh button to update the analysis data (including cursor settings)
    from the phasor widget.
    """
    def __init__(self, viewer, analysis_data=None, phasor_widget=None, parent=None):
        super().__init__(parent)
        self.viewer = viewer
        self.phasor_widget = phasor_widget  # reference to the phasor widget for refreshing analysis data
        
        # Access the file selection widget from the phasor widget
        file_selection = self.phasor_widget.file_selection_widget
       
    
        self.analysis_data = analysis_data if analysis_data is not None else {}
        self.setFont(QFont("Arial", 8))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMinimumWidth(300)
        self.setStyleSheet("background-color: #282a36; color: #f8f8f2;")
        
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Create a shared group list.
        #self.shared_groups = ["None", "Condition 1", "Condition 2"]    
        
        # Create the sub-widgets.
        self.seg_params_widget = SegmentationParametersWidget(viewer, analysis_data=self.analysis_data, phasor_widget=self.phasor_widget)
        self.export_widget = ExportResultsWidget(analysis_data=self.analysis_data, phasor_widget=self.phasor_widget, segmentation_widget=self.seg_params_widget)
        #self.export_widget = ExportResultsWidget(analysis_data=self.analysis_data, phasor_widget=self.phasor_widget)
        
        file_selection.groups_updated.connect(self.export_widget.update_comparison_combo)
        
        # Add a refresh button to update the analysis data.
        self.refresh_button = QPushButton("Refresh Analysis Data")
        self.refresh_button.setFont(QFont("Arial", 10))
        self.refresh_button.setStyleSheet("""
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
        self.refresh_button.clicked.connect(self.refresh_analysis_data)
        
        # Add the sub-widgets and refresh button to the layout.
        layout.addWidget(self.seg_params_widget)
        layout.addWidget(self.export_widget)
        layout.addWidget(self.refresh_button)
        layout.addStretch()
        self.setLayout(layout)
        
    
    
    def refresh_analysis_data(self):
        """
        Re-retrieve the analysis data from the phasor widget.
        This includes cursor settings and cursor mask layers.
        Also merges in segmentation results from the segmentation widget.
        """
        if self.phasor_widget is not None:
            new_data = self.phasor_widget.get_analysis_data()
            # Merge segmentation results if available from segmentation widget.
            if hasattr(self, "seg_params_widget") and self.seg_params_widget is not None:
                seg_data = self.seg_params_widget.segmentation_results
                if seg_data:
                    new_data["segmentation_results"] = seg_data
                    #print("Merged segmentation_results from segmentation widget:", list(seg_data.keys()))
            self.analysis_data = new_data
            self.seg_params_widget.update_num_frames()
            #print("Analysis data refreshed:")
            #print("Cursor settings:", self.analysis_data.get("cursor_settings"))
            #print("Group list:", self.analysis_data.get("group_list"))
            
            # Print cursor mask layers information.
            #print("---- Cursor Mask Layers ----")
            cursor_mask_layers = self.analysis_data.get("cursor_mask_layers")
            if cursor_mask_layers:
                for file_name, layer in cursor_mask_layers.items():
                    try:
                        print(f"{file_name}: Layer name = {layer.name}, data shape = {layer.data.shape}")
                    except Exception as e:
                        print(f"Error accessing layer for {file_name}: {e}")
            else:
                print("No cursor mask layers found in analysis_data.")
        else:
            print("No phasor widget reference provided; cannot refresh analysis data.")
    
    
        
    def print_cursor_info(self):
        # Print cursor settings
        #print("---- Cursor Settings ----")
        cursor_settings = self.analysis_data.get("cursor_settings")
        if cursor_settings:
            for idx, cs in enumerate(cursor_settings):
                print(f"Cursor {idx}: {cs}")
        else:
            print("No cursor settings found in analysis_data.")
        
        # Print cursor mask layers information
        #print("---- Cursor Mask Layers ----")
        cursor_mask_layers = self.analysis_data.get("cursor_mask_layers")
        # if cursor_mask_layers:
        #     for file_name, layer in cursor_mask_layers.items():
        #         try:
        #             print(f"{file_name}: Layer name = {layer.name}, data shape = {layer.data.shape}")
        #         except Exception as e:
        #             print(f"Error accessing layer for {file_name}: {e}")
        # else:
        #     print("No cursor mask layers found in analysis_data.")
    
    
