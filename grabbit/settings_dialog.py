"""Settings dialog: library, capture behavior, hotkey guidance."""

from __future__ import annotations

import shutil

from PySide6.QtCore import QProcess, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("grabbit settings")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)

        form = QFormLayout()
        layout.addLayout(form)

        # library dir
        dir_row = QHBoxLayout()
        self.dir_edit = QLineEdit(settings.library_dir)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        dir_row.addWidget(self.dir_edit, 1)
        dir_row.addWidget(browse)
        form.addRow("Screenshot library:", dir_row)

        # extra watched folders (screen recordings etc.)
        extra_row = QHBoxLayout()
        self.extra_edit = QLineEdit(";".join(settings.extra_dirs))
        self.extra_edit.setPlaceholderText(
            "folders separated by ; (e.g. screen recordings)")
        add_extra = QPushButton("Add…")
        add_extra.clicked.connect(self._add_extra)
        extra_row.addWidget(self.extra_edit, 1)
        extra_row.addWidget(add_extra)
        form.addRow("Also watch:", extra_row)

        # backend
        self.backend_combo = QComboBox()
        self.backend_combo.addItem("Auto (Spectacle if available)", "auto")
        self.backend_combo.addItem("Spectacle", "spectacle")
        self.backend_combo.addItem("Desktop portal", "portal")
        i = self.backend_combo.findData(settings.backend)
        self.backend_combo.setCurrentIndex(max(0, i))
        form.addRow("Capture backend:", self.backend_combo)

        self.copy_check = QCheckBox("Copy image to clipboard after capture")
        self.copy_check.setChecked(settings.copy_after_capture)
        form.addRow("", self.copy_check)

        self.show_check = QCheckBox("Show grabbit window after capture")
        self.show_check.setChecked(settings.show_gallery_after_capture)
        form.addRow("", self.show_check)

        # camera for the recording bubble
        self.camera_combo = QComboBox()
        self.camera_combo.addItem("System default", "")
        self.mic_combo = QComboBox()
        self.mic_combo.addItem("System default", "")
        try:
            from PySide6.QtMultimedia import QMediaDevices
            for cam in QMediaDevices.videoInputs():
                self.camera_combo.addItem(cam.description(),
                                          cam.description())
            for mic in QMediaDevices.audioInputs():
                self.mic_combo.addItem(mic.description(), mic.description())
        except ImportError:
            pass
        i = self.camera_combo.findData(settings.camera_device)
        self.camera_combo.setCurrentIndex(max(0, i))
        form.addRow("Bubble camera:", self.camera_combo)

        i = self.mic_combo.findData(settings.mic_device)
        self.mic_combo.setCurrentIndex(max(0, i))
        form.addRow("Microphone:", self.mic_combo)

        self.mic_check = QCheckBox("Record microphone in screen recordings")
        self.mic_check.setChecked(settings.mic_enabled)
        form.addRow("", self.mic_check)

        self.noise_check = QCheckBox(
            "Noise suppression + auto gain (webrtcdsp)")
        self.noise_check.setChecked(settings.noise_suppression)
        form.addRow("", self.noise_check)

        # hotkey guidance
        hk = QGroupBox("Global capture hotkey")
        hk_layout = QVBoxLayout(hk)
        hint = QLabel(
            "Bind a key (e.g. <b>Meta+Shift+S</b>) to the command below in "
            "your desktop's shortcut settings. It reaches the running "
            "grabbit instantly.")
        hint.setWordWrap(True)
        hk_layout.addWidget(hint)
        cmd = QLineEdit("grabbit --capture")
        cmd.setReadOnly(True)
        cmd.setAlignment(Qt.AlignCenter)
        hk_layout.addWidget(cmd)
        if shutil.which("systemsettings") or shutil.which("kcmshell6"):
            btn = QPushButton("Open KDE Shortcuts settings")
            btn.clicked.connect(self._open_kde_shortcuts)
            hk_layout.addWidget(btn)
        layout.addWidget(hk)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "Choose screenshot library", self.dir_edit.text())
        if d:
            self.dir_edit.setText(d)

    def _add_extra(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "Add watched folder", self.dir_edit.text())
        if d:
            current = [x for x in self.extra_edit.text().split(";") if x]
            if d not in current:
                current.append(d)
            self.extra_edit.setText(";".join(current))

    def _open_kde_shortcuts(self) -> None:
        if shutil.which("systemsettings"):
            QProcess.startDetached("systemsettings", ["kcm_keys"])
        else:
            QProcess.startDetached("kcmshell6", ["kcm_keys"])

    def apply(self) -> bool:
        """Write values into settings. Returns True if watched dirs changed."""
        new_extras = [d for d in self.extra_edit.text().split(";") if d]
        moved = (self.dir_edit.text() != self.settings.library_dir
                 or new_extras != self.settings.extra_dirs)
        self.settings.library_dir = self.dir_edit.text()
        self.settings.extra_dirs = new_extras
        self.settings.backend = self.backend_combo.currentData()
        self.settings.camera_device = self.camera_combo.currentData()
        self.settings.mic_device = self.mic_combo.currentData()
        self.settings.mic_enabled = self.mic_check.isChecked()
        self.settings.noise_suppression = self.noise_check.isChecked()
        self.settings.copy_after_capture = self.copy_check.isChecked()
        self.settings.show_gallery_after_capture = self.show_check.isChecked()
        return moved
