
from qtpy.QtGui import QPixmap, QPalette, QColor, QFont
from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QSpinBox, QCheckBox,
    QPushButton, QFormLayout, QGroupBox, QApplication, QMessageBox,
    QSizePolicy, QScrollArea, QWidget
)
import os

def set_napari_palette(app):
    """Apply a Napari-inspired dark palette with background #282a36 and text #f8f8f2."""
    darkPalette = QPalette()
    darkPalette.setColor(QPalette.Window, QColor("#282a36"))
    darkPalette.setColor(QPalette.WindowText, QColor("#f8f8f2"))
    darkPalette.setColor(QPalette.Base, QColor("#282a36"))
    darkPalette.setColor(QPalette.AlternateBase, QColor("#282a36"))
    darkPalette.setColor(QPalette.ToolTipBase, QColor("#44475a"))
    darkPalette.setColor(QPalette.ToolTipText, QColor("#f8f8f2"))
    darkPalette.setColor(QPalette.Text, QColor("#f8f8f2"))
    darkPalette.setColor(QPalette.Button, QColor("#282a36"))
    darkPalette.setColor(QPalette.ButtonText, QColor("#f8f8f2"))
    darkPalette.setColor(QPalette.Link, QColor("#8be9fd"))
    darkPalette.setColor(QPalette.Highlight, QColor("#707070"))
    darkPalette.setColor(QPalette.HighlightedText, QColor("#f8f8f2"))
    app.setPalette(darkPalette)

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

class FLIMDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("FLIM Data Parameters")
        # Do not force a fixed size; we'll use adjustSize() later.
        self.setStyleSheet("background-color: #282a36; color: #f8f8f2;")
        self.default_font = QFont("Arial", 12)

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(15, 15, 15, 15)

        # Add logo at the top.
        self.add_logo(main_layout)

        # --- Acquisition Settings Group ---
        acquisition_box = QGroupBox("Acquisition Settings")
        acquisition_box.setFont(self.default_font)
        acquisition_box.setStyleSheet("""
            QGroupBox {
                border: 1px solid #707070;
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #282a36, stop:1 #33353b);
                margin-top: 10px;
                padding: 10px;
                border-radius: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #f8f8f2;
            }
        """)
        acq_layout = QVBoxLayout()
        acq_layout.addWidget(self.create_flim_type_widget())
        acq_layout.addWidget(self.create_laser_info_widget())
        acquisition_box.setLayout(acq_layout)
        main_layout.addWidget(acquisition_box)

        # --- Channel Settings Group ---
        channel_box = QGroupBox("Channel Settings")
        channel_box.setFont(self.default_font)
        channel_box.setStyleSheet("""
            QGroupBox {
                border: 1px solid #707070;
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #282a36, stop:1 #33353b);
                margin-top: 10px;
                padding: 10px;
                border-radius: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px;
                color: #f8f8f2;
            }
        """)
        chan_layout = QVBoxLayout()
        # Add an instruction label.
        instruct_label = QLabel("For each channel, select the corresponding data (if applicable):")
        instruct_label.setFont(self.default_font)
        chan_layout.addWidget(instruct_label)
        chan_layout.addWidget(self.create_channel_config_widget())
        chan_layout.addWidget(self.create_gs_calc_widget())
        channel_box.setLayout(chan_layout)
        main_layout.addWidget(channel_box)

        # Confirm button (blue)
        confirm_button = QPushButton("Confirm Settings")
        confirm_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        confirm_button.setFont(self.default_font)
        confirm_button.setStyleSheet("""
            QPushButton {
                background-color: #007acc;
                color: white;
                font-weight: bold;
                border-radius: 4px;
                padding: 8px 15px;
            }
            QPushButton:hover {
                background-color: #005f99;
            }
        """)
        confirm_button.clicked.connect(self.confirm_settings)
        main_layout.addWidget(confirm_button)

        self.adjustSize()

    def add_logo(self, layout):
        """Adds a centered logo at the top."""
        logo_path = "/Users/solano.a/Documents/2023 Napari code/napari-hello/logo FLIMa_finalv3-2.png"
        logo_label = QLabel()
        logo_label.setAlignment(Qt.AlignCenter)
        logo_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        logo_label.setFont(self.default_font)
        if os.path.exists(logo_path):
            pixmap = QPixmap(logo_path).scaled(200, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            logo_label.setPixmap(pixmap)
        else:
            logo_label.setText("Logo not found")
        layout.addWidget(logo_label)

    def create_flim_type_widget(self):
        """Creates and returns the FLIM Type widget."""
        group = QGroupBox("FLIM Type")
        group.setFont(self.default_font)
        form = QFormLayout()
        form.setSpacing(10)
        self.flim_type_combo = QComboBox()
        self.flim_type_combo.addItems(["FD FLIM", "TCSPC FLIM"])
        self.flim_type_combo.setFont(self.default_font)
        self.flim_type_combo.setFixedWidth(200)
        self.flim_type_combo.setStyleSheet("""
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
        form.addRow("Select Type:", self.flim_type_combo)
        group.setLayout(form)
        return group

    def create_laser_info_widget(self):
        """Creates and returns the Laser Information widget."""
        group = QGroupBox("Laser Information")
        group.setFont(self.default_font)
        form = QFormLayout()
        form.setSpacing(10)
        self.laser_freq_spin = QSpinBox()
        self.laser_freq_spin.setRange(1, 100000)
        self.laser_freq_spin.setFont(self.default_font)
        self.laser_freq_spin.setFixedWidth(200)
        self.laser_freq_spin.setStyleSheet("""
            QSpinBox {
                background-color: white;
                color: black;
                border: 1px solid #707070;
                padding: 5px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: white;
                border: 1px solid #707070;
                width: 15px;
                height: 15px;
            }
        """)
        self.harmonic_spin = QSpinBox()
        self.harmonic_spin.setRange(1, 10)
        self.harmonic_spin.setFont(self.default_font)
        self.harmonic_spin.setFixedWidth(200)
        self.harmonic_spin.setStyleSheet("""
            QSpinBox {
                background-color: white;
                color: black;
                border: 1px solid #707070;
                padding: 5px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: white;
                border: 1px solid #707070;
                width: 15px;
                height: 15px;
            }
        """)
        form.addRow("Laser Frequency (MHz):", self.laser_freq_spin)
        form.addRow("Harmonic:", self.harmonic_spin)
        group.setLayout(form)
        return group

    def create_channel_config_widget(self):
        """Creates and returns the Channel Configuration widget."""
        group = QGroupBox("Channel Configuration")
        group.setFont(self.default_font)
        group.setStyleSheet("""
            QGroupBox {
                border: 1px solid #707070;
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #282a36, stop:1 #33353b);
                margin-top: 10px;
                padding: 5px;
                border-radius: 5px;
            }
        """)
        vlayout = QVBoxLayout()
        vlayout.setSpacing(10)
        instruct = QLabel("For each channel, select the data available:")
        instruct.setFont(self.default_font)
        instruct.setStyleSheet("color: #f8f8f2;")
        vlayout.addWidget(instruct)
        
        form = QFormLayout()
        form.setSpacing(10)
        self.num_channels_spin = QSpinBox()
        self.num_channels_spin.setRange(1, 10)
        self.num_channels_spin.setFont(self.default_font)
        self.num_channels_spin.setFixedWidth(200)
        self.num_channels_spin.setStyleSheet("""
            QSpinBox {
                background-color: white;
                color: black;
                border: 1px solid #707070;
                padding: 5px;
            }
            QSpinBox::up-button, QSpinBox::down-button {
                background-color: white;
                border: 1px solid #707070;
                width: 15px;
                height: 15px;
            }
        """)
        self.num_channels_spin.valueChanged.connect(self.update_channel_config)
        form.addRow("Number of Channels:", self.num_channels_spin)
        vlayout.addLayout(form)

        #from qtpy.QtWidgets import QScrollArea
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        self.channel_config_widget = QWidget()
        self.channel_config_layout = QVBoxLayout(self.channel_config_widget)
        scroll_area.setWidget(self.channel_config_widget)
        vlayout.addWidget(scroll_area)

        group.setLayout(vlayout)
        self.update_channel_config(self.num_channels_spin.value())
        return group

    def update_channel_config(self, num_channels):
        """Updates the dynamic channel assignment controls."""
        clear_layout(self.channel_config_layout)
        self.channel_comboboxes = []
        for i in range(num_channels):
            h_layout = QHBoxLayout()
            label = QLabel(f"Channel {i+1}:")
            label.setFont(self.default_font)
            label.setStyleSheet("color: #f8f8f2;")
            label.setFixedWidth(100)
            combo = QComboBox()
            combo.addItems(["None", "Intensity", "G-values", "S-values", "Phase-values", "Modulation-values"])
            combo.setFont(self.default_font)
            combo.setFixedWidth(200)
            combo.setStyleSheet("""
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
            self.channel_comboboxes.append(combo)
            h_layout.addWidget(label)
            h_layout.addWidget(combo)
            h_layout.addStretch()
            self.channel_config_layout.addLayout(h_layout)

    def create_gs_calc_widget(self):
        """Creates and returns the G & S Calculation widget."""
        group = QGroupBox("G & S Calculation")
        group.setFont(self.default_font)
        group.setStyleSheet("""
            QGroupBox {
                border: 1px solid #707070;
                background-color: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #282a36, stop:1 #33353b);
                margin-top: 10px;
                padding: 5px;
                border-radius: 5px;
            }
        """)
        vlayout = QVBoxLayout()
        self.gs_calc_checkbox = QCheckBox("Calculate G and S Coordinates Automatically")
        self.gs_calc_checkbox.setFont(self.default_font)
        self.gs_calc_checkbox.setChecked(True)
        vlayout.addWidget(self.gs_calc_checkbox)
        group.setLayout(vlayout)
        self.gs_calc_checkbox.toggled.connect(self.toggle_manual_gs)
        return group

    def toggle_manual_gs(self, checked):
        # In this version, GS Calculation is handled solely by the checkbox.
        pass

    def confirm_settings(self):
        """Collects and displays a summary of the current settings, then accepts the dialog."""
        flim_type = self.flim_type_combo.currentText()
        laser_freq = self.laser_freq_spin.value()
        harmonic = self.harmonic_spin.value()
        num_channels = self.num_channels_spin.value()
        channel_assignments = [combo.currentText() for combo in self.channel_comboboxes]
        gs_calc = self.gs_calc_checkbox.isChecked()

        summary = (
            f"FLIM Type: {flim_type}\n"
            f"Laser Frequency: {laser_freq} MHz\n"
            f"Harmonic: {harmonic}\n"
            f"Number of Channels: {num_channels}\n"
            f"Channel Assignments: {channel_assignments}\n"
            f"Calculate G & S: {'Yes' if gs_calc else 'No'}"
        )
        # from qtpy.QtWidgets import QMessageBox
        QMessageBox.information(self, "Settings Confirmed", summary)
        self.accept()

    def get_parameters(self):
        """
        Collects and returns all user-input parameters as a dictionary.
        This method can be called after the dialog is accepted.
        """
        params = {
            "flim_type": self.flim_type_combo.currentText(),
            "laser_frequency": self.laser_freq_spin.value(),
            "harmonic": self.harmonic_spin.value(),
            "num_channels": self.num_channels_spin.value(),
            "channel_assignments": [combo.currentText() for combo in self.channel_comboboxes],
            "calculate_gs": self.gs_calc_checkbox.isChecked()
        }
        return params

# Uncomment the following block to test the FLIMDialog in isolation.
# if __name__ == '__main__':
#     import sys
#     app = QApplication(sys.argv)
#     dlg = FLIMDialog()
#     dlg.show()
#     dlg.adjustSize()  # Set initial size to minimal required by content.
#     if dlg.exec_() == QDialog.Accepted:
#         params = dlg.get_parameters()
#         print("User Parameters:")
#         print(params)
#     sys.exit(app.exec_())





