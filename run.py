import os
import napari
from qtpy.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTabWidget, QWidget
)
from qtpy.QtGui  import QPixmap
from qtpy.QtCore import Qt

from napari_flima.intro_dialog_widget import FLIMDialog
from napari_flima.phasor_widget       import PhasorWidget
from napari_flima.phasor_plot import PhasorPlotDialog
from napari_flima.segmentation_widget import MainSegmentationWidget
from napari_flima import get_logo_path

def main():
    # 1) Create (or get) the Napari Viewer and hide it immediately
    viewer = napari.current_viewer() or napari.Viewer()
    viewer.window._qt_window.hide()

    # 2) Show the FLIM intro dialog as a standalone window
    flim_dialog = FLIMDialog()  # top‑level by default
    if flim_dialog.exec_() != QDialog.Accepted:
        # User cancelled → exit without ever showing Napari
        return

    full_config = flim_dialog.get_full_config()

    # 3) Build Phasor + Segmentation widgets
    phasor_plot_dialog = PhasorPlotDialog(parent=viewer.window._qt_window)
    phasor_widget      = PhasorWidget(viewer, phasor_plot_dialog, full_config)
    analysis_data      = phasor_widget.get_analysis_data()
    seg_widget         = MainSegmentationWidget(
        viewer,
        analysis_data=analysis_data,
        phasor_widget=phasor_widget
    )
    phasor_widget.seg_widget = seg_widget
    if full_config and full_config.downstream:
        seg_widget.apply_downstream_config(full_config.downstream)

    # 4) Create a docking panel with tabs
    main_widget = QWidget()
    layout      = QVBoxLayout(main_widget)

    # Optional: show the logo at the top of the dock
    logo_path = get_logo_path()
    if os.path.exists(logo_path):
        logo_lbl = QLabel(alignment=Qt.AlignCenter)
        pix      = QPixmap(logo_path).scaledToWidth(200, Qt.SmoothTransformation)
        logo_lbl.setPixmap(pix)
        layout.addWidget(logo_lbl)

    tabs = QTabWidget()
    tabs.addTab(phasor_widget, "Phasor FLIM")
    tabs.addTab(seg_widget,    "Downstream Analysis")
    layout.addWidget(tabs)

    dock = viewer.window.add_dock_widget(main_widget, name="FLIMa", area="right")
    dock.setTitleBarWidget(QWidget())  # remove extra title bar

    # 5) Show Napari (with your plugin already docked)
    viewer.window._qt_window.show()

    # 6) Enter Napari’s event loop
    napari.run()


if __name__ == "__main__":
    main()
