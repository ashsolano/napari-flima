
import sys, os
from qtpy.QtGui import QPixmap, QFont, QPalette, QColor
from qtpy.QtCore import Qt
from qtpy.QtWidgets import (
    QApplication, QDialog, QVBoxLayout, QLabel, QGroupBox,
    QFormLayout, QComboBox, QSpinBox, QCheckBox, QPushButton,
    QSizePolicy, QScrollArea, QWidget, QHBoxLayout, QMessageBox
)
from napari_flima import get_logo_path



def clear_layout(layout):
    if layout is None: return
    while layout.count():
        itm = layout.takeAt(0)
        w = itm.widget()
        if w:
            w.setParent(None)
        else:
            clear_layout(itm.layout())

def set_napari_palette(app):
    p = QPalette()
    p.setColor(QPalette.Window, QColor("#282a36"))
    p.setColor(QPalette.WindowText, QColor("#f8f8f2"))
    p.setColor(QPalette.Base, QColor("#282a36"))
    p.setColor(QPalette.Text, QColor("#f8f8f2"))
    p.setColor(QPalette.Button, QColor("#282a36"))
    p.setColor(QPalette.ButtonText, QColor("#f8f8f2"))
    p.setColor(QPalette.Highlight, QColor("#707070"))
    p.setColor(QPalette.HighlightedText, QColor("#f8f8f2"))
    app.setPalette(p)

class FLIMDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        
        self.setWindowFlags(self.windowFlags() | Qt.Window)

        
        # ───── Simplified stylesheet ─────
        self.setStyleSheet("""
            /* Dialog & GroupBoxes */
            QDialog, QGroupBox {
                background-color: #282a36;
                color: #f8f8f2;
                font-family: Arial;
                font-size: 12px;
            }
            QGroupBox {
                border: 1px solid #707070;
                border-radius: 5px;
                margin-top: 10px;
                padding: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
            }

            /* Buttons */
            QPushButton {
                background-color: #007acc;
                color: white;
                border-radius: 4px;
                padding: 4px 10px;
            }
            QPushButton:hover {
                background-color: #005f99;
            }

            /* Combos: white & padded */
            QComboBox {
                background-color: white;
                color: black;
                border: 1px solid #707070;
                padding: 2px 6px;   /* room for native arrow */
                min-height: 24px;
            }
            QComboBox QAbstractItemView {
                background-color: white;
                color: black;
            }

            /* SpinBoxes: only change bg/text—let Fusion draw arrows */
            QSpinBox {
                background-color: white;
                color: black;
            }
        """)

        self.setWindowTitle("FLIM Data Parameters")
        self.default_font = QFont("Arial", 12)

        main = QVBoxLayout(self)
        main.setContentsMargins(15,15,15,15)
        main.setSpacing(12)

        self.add_logo(main)
        main.addWidget(self._make_acquisition_group())
        main.addWidget(self._make_channel_group())

        confirm_btn = QPushButton("Confirm Settings")
        confirm_btn.setFont(self.default_font)
        confirm_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        confirm_btn.clicked.connect(self._confirm)
        main.addWidget(confirm_btn)

        self.adjustSize()


    def _make_acquisition_group(self):
        gb = QGroupBox("Acquisition Settings"); gb.setFont(self.default_font)
        form = QFormLayout()
        self.combo_type = QComboBox(); self.combo_type.addItems(["TCSPC FLIM", "FD FLIM", "Other"])
        self.spin_freq = QSpinBox();  self.spin_freq.setRange(1,100000)
        self.spin_harm = QSpinBox();  self.spin_harm.setRange(1,10)
        for w in (self.combo_type, self.spin_freq, self.spin_harm):
            w.setFont(self.default_font)
        form.addRow("Select Type:", self.combo_type)
        form.addRow("Laser Frequency (MHz):", self.spin_freq)
        form.addRow("Harmonic:", self.spin_harm)
        gb.setLayout(form)
        return gb

    def _make_channel_group(self):
        gb = QGroupBox("Channel Settings"); gb.setFont(self.default_font)
        v = QVBoxLayout()
        v.addWidget(QLabel("For each channel, select the corresponding data:", alignment=Qt.AlignLeft))
        self.spin_nch = QSpinBox(); self.spin_nch.setRange(1,10)
        self.spin_nch.setFont(self.default_font)
        
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        
        self.spin_nch.valueChanged.connect(lambda n: self._update_channels(n, scroll))
        v.addWidget(self.spin_nch)

        cont = QWidget(); self.ch_layout = QVBoxLayout(cont)
        scroll.setWidget(cont)
        v.addWidget(scroll)

        self.chk_gs = QCheckBox("Calculate G and S Coordinates Automatically")
        self.chk_gs.setFont(self.default_font)
        self.chk_gs.setChecked(True)
        v.addWidget(self.chk_gs)

        gb.setLayout(v)
        self._update_channels(self.spin_nch.value(), scroll)
        return gb

    def _update_channels(self, n, scroll):
        clear_layout(self.ch_layout)
        self.channel_combos = []
        for i in range(n):
            h = QHBoxLayout()
            lbl = QLabel(f"Channel {i+1}:", font=self.default_font)
            lbl.setStyleSheet("QLabel {color: white}")
            combo = QComboBox()
            combo.addItems([
                "None", "Intensity", "G-values", "S-values",
                "Phase-values", "Modulation-values"
            ])
            combo.setFont(self.default_font)
            h.addWidget(lbl); h.addWidget(combo); h.addStretch()
            self.ch_layout.addLayout(h)
            self.channel_combos.append(combo)
        scroll.setMinimumHeight(min(50*n, 200))

    def _confirm(self):
        params = self.get_parameters()
        lines = []
        for k, v in params.items():
            if k == "calculate_gs":
                label = "Calculate GS"
            else:
                label = k.replace('_', ' ').title()
            lines.append(f"{label}: {v}")

        summary = "\n".join(lines) + "\n\nProceed with these settings?"
        if QMessageBox.question(
                self, "Confirm Settings", summary,
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes
            ) == QMessageBox.Yes:
            self.accept()

    def get_parameters(self):
        return {
            "flim_type": self.combo_type.currentText(),
            "laser_frequency": self.spin_freq.value(),
            "harmonic": self.spin_harm.value(),
            "num_channels": self.spin_nch.value(),
            "channel_assignments": [c.currentText() for c in self.channel_combos],
            "calculate_gs": self.chk_gs.isChecked()
        }
    
    def add_logo(self, layout):
        """Adds a centered logo at the top."""
        logo_path = get_logo_path()
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






