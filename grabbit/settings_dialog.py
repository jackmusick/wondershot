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

    def _open_kde_shortcuts(self) -> None:
        if shutil.which("systemsettings"):
            QProcess.startDetached("systemsettings", ["kcm_keys"])
        else:
            QProcess.startDetached("kcmshell6", ["kcm_keys"])

    def apply(self) -> bool:
        """Write values into settings. Returns True if the library moved."""
        moved = self.dir_edit.text() != self.settings.library_dir
        self.settings.library_dir = self.dir_edit.text()
        self.settings.backend = self.backend_combo.currentData()
        self.settings.copy_after_capture = self.copy_check.isChecked()
        self.settings.show_gallery_after_capture = self.show_check.isChecked()
        return moved
