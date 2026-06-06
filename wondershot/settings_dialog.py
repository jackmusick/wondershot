"""Settings dialog: library, capture behavior, hotkey guidance."""

from __future__ import annotations

import shutil

from PySide6.QtCore import QObject, QProcess, QRunnable, Qt, Signal
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
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class _AuthSignal(QObject):
    code_ready = Signal(str, str)  # user_code, verification_uri
    done = Signal(str, str)        # account, error ('' on success)


class _DeviceAuthJob(QRunnable):
    """Device-code flow: emits the code, polls until signed in."""

    def __init__(self, client_id: str):
        super().__init__()
        self.client_id = client_id
        self.emitter = _AuthSignal()

    def run(self) -> None:
        import time
        from . import msgraph
        try:
            dc = msgraph.request_device_code(self.client_id)
            self.emitter.code_ready.emit(dc["user_code"],
                                         dc["verification_uri"])
            deadline = time.time() + int(dc.get("expires_in", 900))
            while time.time() < deadline:
                time.sleep(int(dc.get("interval", 5)))
                tokens = msgraph.poll_token(self.client_id,
                                            dc["device_code"])
                if tokens is not None:
                    account = msgraph.whoami(tokens["access_token"])
                    msgraph.save_tokens(tokens, self.client_id, account)
                    self.emitter.done.emit(account, "")
                    return
            self.emitter.done.emit("", "sign-in timed out")
        except Exception as e:  # noqa: BLE001 — show in the dialog
            self.emitter.done.emit("", str(e))


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Wondershot settings")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        tabs = QTabWidget(self)
        layout.addWidget(tabs)

        general = QWidget()
        gen_layout = QVBoxLayout(general)
        tabs.addTab(general, "General")
        form = QFormLayout()
        gen_layout.addLayout(form)

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

        self.show_check = QCheckBox("Show Wondershot window after capture")
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
        form.addRow("Camera:", self.camera_combo)

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
            "Wondershot instantly.")
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
        gen_layout.addWidget(hk)
        gen_layout.addStretch(1)

        tabs.addTab(self._build_share_tab(), "Sharing")

        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_share_tab(self) -> QWidget:
        s = self.settings
        w = QWidget()
        v = QVBoxLayout(w)

        form = QFormLayout()
        self.share_default = QComboBox()
        self.share_default.addItem("First configured", "")
        self.share_default.addItem("S3-compatible", "s3")
        self.share_default.addItem("Azure Blob", "azure")
        self.share_default.addItem("OneDrive / SharePoint", "onedrive")
        i = self.share_default.findData(s.share_provider)
        self.share_default.setCurrentIndex(max(0, i))
        form.addRow("Default provider:", self.share_default)

        self.share_expiry = QSpinBox()
        self.share_expiry.setRange(1, 7)
        self.share_expiry.setSuffix(" days")
        self.share_expiry.setValue(s.share_expiry_days)
        self.share_expiry.setToolTip(
            "S3 caps presigned links at 7 days; Azure follows suit here")
        form.addRow("Links expire after:", self.share_expiry)
        v.addLayout(form)

        s3 = QGroupBox("S3-compatible (AWS, MinIO, B2, R2, …)")
        s3f = QFormLayout(s3)
        self.s3_endpoint = QLineEdit(s.s3_endpoint)
        self.s3_endpoint.setPlaceholderText("https://s3.us-east-1.amazonaws.com")
        s3f.addRow("Endpoint:", self.s3_endpoint)
        self.s3_region = QLineEdit(s.s3_region)
        self.s3_region.setPlaceholderText("us-east-1")
        s3f.addRow("Region:", self.s3_region)
        self.s3_bucket = QLineEdit(s.s3_bucket)
        s3f.addRow("Bucket:", self.s3_bucket)
        self.s3_access_key = QLineEdit(s.s3_access_key)
        s3f.addRow("Access key:", self.s3_access_key)
        self.s3_secret_key = QLineEdit(s.s3_secret_key)
        self.s3_secret_key.setEchoMode(QLineEdit.Password)
        s3f.addRow("Secret key:", self.s3_secret_key)
        v.addWidget(s3)

        az = QGroupBox("Azure Blob Storage")
        azf = QFormLayout(az)
        self.azure_account = QLineEdit(s.azure_account)
        azf.addRow("Account:", self.azure_account)
        self.azure_container = QLineEdit(s.azure_container)
        azf.addRow("Container:", self.azure_container)
        self.azure_key = QLineEdit(s.azure_key)
        self.azure_key.setEchoMode(QLineEdit.Password)
        azf.addRow("Account key:", self.azure_key)
        v.addWidget(az)

        od = QGroupBox("OneDrive / SharePoint (Microsoft account)")
        odf = QFormLayout(od)
        self.graph_client = QLineEdit(s.graph_client_id)
        odf.addRow("Client ID:", self.graph_client)
        from .msgraph import connected_account
        account = connected_account()
        self.graph_status = QLabel(
            f"Connected as <b>{account}</b>" if account else "Not connected")
        odf.addRow("Status:", self.graph_status)
        self.graph_btn = QPushButton("Disconnect" if account else "Connect…")
        self.graph_btn.clicked.connect(self._graph_connect)
        odf.addRow("", self.graph_btn)
        dest_row = QHBoxLayout()
        self.graph_dest = QLabel(s.graph_drive_label or "My OneDrive")
        dest_btn = QPushButton("Change…")
        dest_btn.clicked.connect(self._graph_pick_destination)
        dest_row.addWidget(self.graph_dest, 1)
        dest_row.addWidget(dest_btn)
        odf.addRow("Destination:", dest_row)
        v.addWidget(od)

        warn = QLabel("S3/Azure credentials are stored unencrypted in "
                      "Wondershot's config file — use a scoped key. "
                      "OneDrive uses sign-in tokens instead.")
        warn.setWordWrap(True)
        warn.setStyleSheet("color: palette(mid);")
        v.addWidget(warn)
        v.addStretch(1)
        return w

    # -- OneDrive device-code flow ---------------------------------------

    def _graph_connect(self) -> None:
        from . import msgraph
        if msgraph.connected_account():
            msgraph.disconnect()
            self.graph_status.setText("Not connected")
            self.graph_btn.setText("Connect…")
            return
        from PySide6.QtCore import QThreadPool
        self.graph_btn.setEnabled(False)
        self.graph_status.setText("Starting sign-in…")
        job = _DeviceAuthJob(self.graph_client.text().strip())
        job.emitter.code_ready.connect(self._graph_show_code)
        job.emitter.done.connect(self._graph_done)
        self._auth_job = job  # keep emitter alive
        QThreadPool.globalInstance().start(job)

    def _graph_show_code(self, user_code: str, uri: str) -> None:
        from PySide6.QtGui import QDesktopServices, QGuiApplication
        from PySide6.QtCore import QUrl
        QGuiApplication.clipboard().setText(user_code)
        self.graph_status.setText(
            f"Enter code <b>{user_code}</b> (copied) at {uri}")
        QDesktopServices.openUrl(QUrl(uri))

    def _graph_done(self, account: str, error: str) -> None:
        self.graph_btn.setEnabled(True)
        if error:
            self.graph_status.setText(f"<i>{error}</i>")
            self.graph_btn.setText("Connect…")
        else:
            self.graph_status.setText(f"Connected as <b>{account}</b>")
            self.graph_btn.setText("Disconnect")

    def _graph_pick_destination(self) -> None:
        """My OneDrive (personal or business = whoever signed in), or a
        SharePoint site document library."""
        from PySide6.QtWidgets import QInputDialog, QMessageBox
        from . import msgraph
        if not msgraph.connected_account():
            QMessageBox.information(self, "Wondershot", "Connect first.")
            return
        choice, ok = QInputDialog.getItem(
            self, "Share destination", "Upload to:",
            ["My OneDrive", "A SharePoint site…"], 0, False)
        if not ok:
            return
        if choice == "My OneDrive":
            self.settings.graph_drive_id = ""
            self.settings.graph_drive_label = ""
            self.graph_dest.setText("My OneDrive")
            return
        query, ok = QInputDialog.getText(
            self, "Find site", "Search SharePoint sites:")
        if not ok or not query.strip():
            return
        try:
            from PySide6.QtGui import QGuiApplication
            QGuiApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                token = msgraph.ensure_access_token()
                sites = msgraph.sites_search(token, query.strip())
            finally:
                QGuiApplication.restoreOverrideCursor()
            if not sites:
                QMessageBox.information(self, "Wondershot",
                                        "No sites matched.")
                return
            names = [f'{x["name"]} — {x["url"]}' for x in sites]
            pick, ok = QInputDialog.getItem(self, "Site", "Site:",
                                            names, 0, False)
            if not ok:
                return
            site = sites[names.index(pick)]
            QGuiApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                drives = msgraph.site_drives(token, site["id"])
            finally:
                QGuiApplication.restoreOverrideCursor()
            if not drives:
                QMessageBox.information(self, "Wondershot",
                                        "Site has no document libraries.")
                return
            dnames = [x["name"] for x in drives]
            dpick, ok = QInputDialog.getItem(self, "Library",
                                             "Document library:",
                                             dnames, 0, False)
            if not ok:
                return
            drive = drives[dnames.index(dpick)]
            label = f'{site["name"]} / {drive["name"]}'
            self.settings.graph_drive_id = drive["id"]
            self.settings.graph_drive_label = label
            self.graph_dest.setText(label)
        except OSError as e:
            QMessageBox.warning(self, "Wondershot", str(e))

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
        self.settings.share_provider = self.share_default.currentData()
        self.settings.graph_client_id = self.graph_client.text().strip()
        self.settings.share_expiry_days = self.share_expiry.value()
        for field in ("s3_endpoint", "s3_region", "s3_bucket",
                      "s3_access_key", "s3_secret_key",
                      "azure_account", "azure_container", "azure_key"):
            setattr(self.settings, field, getattr(self, field).text().strip())
        return moved
