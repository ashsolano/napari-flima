import os
import napari
from qtpy.QtWidgets import QApplication, QDialog, QTabWidget, QWidget, QVBoxLayout, QLabel
from qtpy.QtGui import QPixmap
from qtpy.QtCore import Qt

# Import your FLIM data parameters dialog and plugin widgets from your package.
from napari_flima.intro_dialog_widget import FLIMDialog
from napari_flima.phasor_widget import PhasorWidget, PhasorPlotDialog
from napari_flima.segmentation_widget import MainSegmentationWidget

# Import the helper function to get the logo path.
from napari_flima import get_logo_path

def main():
    app = QApplication([])

    # 1. Launch the FLIM Data Parameters dialog first.
    flim_dialog = FLIMDialog()
    if flim_dialog.exec_() != QDialog.Accepted:
        return  # Exit if dialog is canceled

    intro_params = flim_dialog.get_parameters()

    # 2. Get or create a Napari viewer.
    viewer = napari.current_viewer() or napari.Viewer()

    # 3. Build your main plugin widget.
    main_widget = QWidget()
    main_layout = QVBoxLayout(main_widget)

    # (Optional) Add a logo using the get_logo_path() helper.
    logo_path = get_logo_path()
    if os.path.exists(logo_path):
        logo_label = QLabel()
        logo_label.setAlignment(Qt.AlignCenter)
        pixmap = QPixmap(logo_path)
        logo_label.setPixmap(pixmap)
        main_layout.addWidget(logo_label)

    # 4. Create a QTabWidget for your plugin’s sub-widgets.
    tab_widget = QTabWidget()
    phasor_dialog = PhasorPlotDialog(parent=None)
    phasor_widget = PhasorWidget(viewer, phasor_dialog, intro_params)
    analysis_data = phasor_widget.get_analysis_data()
    seg_widget = MainSegmentationWidget(viewer, analysis_data=analysis_data, phasor_widget=phasor_widget)
    tab_widget.addTab(phasor_widget, "Phasor FLIM")
    tab_widget.addTab(seg_widget, "Downstream Analysis")
    main_layout.addWidget(tab_widget)

    # 5. Dock the main widget in the Napari viewer.
    dock_widget = viewer.window.add_dock_widget(main_widget, area='right')
    dock_widget.setTitleBarWidget(QWidget())
    dock_widget.setWindowTitle("FLIMa")

    viewer.show()
    viewer.window._qt_window.showNormal()
    viewer.window._qt_window.resize(1200, 800)

    app.exec_()

if __name__ == "__main__":
    main()
