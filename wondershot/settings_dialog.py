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


class _ExchangeJob(QRunnable):
    """Swap an auth code (from the wondershot:// redirect) for tokens."""

    def __init__(self, client_id: str, code: str, verifier: str):
        super().__init__()
        self.client_id = client_id
        self.code = code
        self.verifier = verifier
        self.emitter = _AuthSignal()

    def run(self) -> None:
        from . import msgraph
        try:
            tokens = msgraph.exchange_code(self.client_id, self.code,
                                           self.verifier)
            account = msgraph.whoami(tokens["access_token"])
            msgraph.save_tokens(tokens, self.client_id, account)
            self.emitter.done.emit(account, "")
        except Exception as e:  # noqa: BLE001
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

        v.addWidget(self._build_onedrive_group(s))

        warn = QLabel("S3/Azure credentials are stored unencrypted in "
                      "Wondershot's config file — use a scoped key. "
                      "OneDrive uses sign-in tokens instead.")
        warn.setWordWrap(True)
        warn.setStyleSheet("color: palette(mid);")
        v.addWidget(warn)
        v.addStretch(1)
        return w

    # -- OneDrive / SharePoint -------------------------------------------

    def _build_onedrive_group(self, s):
        from PySide6.QtWidgets import (
            QComboBox, QStackedWidget, QWidget,
        )
        from .msgraph import DEFAULT_CLIENT_ID, connected_account

        od = QGroupBox("OneDrive / SharePoint (Microsoft account)")
        odf = QFormLayout(od)

        account = connected_account()
        self.graph_status = QLabel(
            f"Connected as <b>{account}</b>" if account else "Not connected")
        odf.addRow("Status:", self.graph_status)

        self.graph_btn = QPushButton("Disconnect" if account else "Connect…")
        self.graph_btn.clicked.connect(self._graph_connect)
        self.graph_code_btn = QPushButton("Use a code instead")
        self.graph_code_btn.setFlat(True)
        self.graph_code_btn.clicked.connect(self._graph_connect_code)
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.graph_btn)
        btn_row.addWidget(self.graph_code_btn)
        btn_row.addStretch(1)
        odf.addRow("", self._wrap(btn_row))

        # -- destination, inline (no popup) -------------------------------
        self.dest_combo = QComboBox()
        self.dest_combo.addItem("My OneDrive", "onedrive")
        self.dest_combo.addItem("A SharePoint site", "sharepoint")
        on_sp = bool(s.graph_drive_id)
        self.dest_combo.setCurrentIndex(1 if on_sp else 0)
        self.dest_combo.currentIndexChanged.connect(self._dest_mode_changed)
        odf.addRow("Save to:", self.dest_combo)

        self.sp_box = QWidget()
        spv = QFormLayout(self.sp_box)
        spv.setContentsMargins(0, 0, 0, 0)
        site_row = QHBoxLayout()
        self.sp_search = QLineEdit()
        self.sp_search.setPlaceholderText("search site name…")
        self.sp_search.returnPressed.connect(self._sp_find)
        find_btn = QPushButton("Find")
        find_btn.clicked.connect(self._sp_find)
        site_row.addWidget(self.sp_search, 1)
        site_row.addWidget(find_btn)
        spv.addRow("Site:", self._wrap(site_row))
        self.sp_site_combo = QComboBox()
        self.sp_site_combo.currentIndexChanged.connect(self._sp_site_chosen)
        spv.addRow("", self.sp_site_combo)
        self.sp_lib_combo = QComboBox()
        self.sp_lib_combo.currentIndexChanged.connect(self._sp_lib_chosen)
        spv.addRow("Library:", self.sp_lib_combo)
        self.sp_current = QLabel(s.graph_drive_label or "")
        self.sp_current.setStyleSheet("color: palette(mid);")
        spv.addRow("Selected:", self.sp_current)
        odf.addRow("", self.sp_box)
        self.sp_box.setVisible(on_sp)

        # -- client id: default unless changed ----------------------------
        self.client_is_default = (s.graph_client_id == DEFAULT_CLIENT_ID)
        self.graph_client = QLineEdit(s.graph_client_id)
        self.graph_client.setReadOnly(self.client_is_default)
        client_row = QHBoxLayout()
        client_row.addWidget(self.graph_client, 1)
        self.client_change_btn = QPushButton(
            "Change" if self.client_is_default else "Use default")
        self.client_change_btn.clicked.connect(self._toggle_client)
        client_row.addWidget(self.client_change_btn)
        odf.addRow("Client ID:", self._wrap(client_row))
        self._sites_cache = []
        self._drives_cache = []
        return od

    @staticmethod
    def _wrap(layout):
        from PySide6.QtWidgets import QWidget
        w = QWidget()
        layout.setContentsMargins(0, 0, 0, 0)
        w.setLayout(layout)
        return w

    def _toggle_client(self) -> None:
        from .msgraph import DEFAULT_CLIENT_ID
        if self.graph_client.isReadOnly():  # was default → allow editing
            self.graph_client.setReadOnly(False)
            self.graph_client.setFocus()
            self.client_change_btn.setText("Use default")
        else:  # reset to the shipped default
            self.graph_client.setText(DEFAULT_CLIENT_ID)
            self.graph_client.setReadOnly(True)
            self.client_change_btn.setText("Change")

    def _dest_mode_changed(self) -> None:
        sharepoint = self.dest_combo.currentData() == "sharepoint"
        self.sp_box.setVisible(sharepoint)
        if not sharepoint:
            self.settings.graph_drive_id = ""
            self.settings.graph_drive_label = ""
            self.sp_current.setText("")

    # -- connect (browser redirect, with device-code fallback) -----------

    def _graph_connect(self) -> None:
        from . import msgraph
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        if msgraph.connected_account():
            msgraph.disconnect()
            self.graph_status.setText("Not connected")
            self.graph_btn.setText("Connect…")
            return
        parent = self.parent()
        if parent is not None and hasattr(parent, "oauth_callback"):
            parent.oauth_callback.connect(self._oauth_redirect,
                                          Qt.UniqueConnection)
        self._pkce_verifier, challenge = msgraph.make_pkce()
        self._oauth_state = msgraph.new_state()
        url = msgraph.build_auth_url(self.graph_client.text().strip(),
                                     challenge, self._oauth_state)
        self.graph_status.setText("Waiting for sign-in in your browser…")
        QDesktopServices.openUrl(QUrl(url))

    def _oauth_redirect(self, url: str) -> None:
        import urllib.parse
        from PySide6.QtCore import QThreadPool
        params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        if params.get("state", [""])[0] != getattr(self, "_oauth_state", ""):
            return  # not ours / stale
        if "error" in params:
            self.graph_status.setText(
                f"<i>{params.get('error_description', params['error'])[0]}</i>")
            return
        code = params.get("code", [""])[0]
        if not code:
            return
        self.graph_status.setText("Completing sign-in…")
        job = _ExchangeJob(self.graph_client.text().strip(), code,
                           self._pkce_verifier)
        job.emitter.done.connect(self._graph_done)
        self._auth_job = job
        QThreadPool.globalInstance().start(job)

    def _graph_connect_code(self) -> None:
        from . import msgraph
        from PySide6.QtCore import QThreadPool
        if msgraph.connected_account():
            return
        self.graph_btn.setEnabled(False)
        self.graph_status.setText("Starting sign-in…")
        job = _DeviceAuthJob(self.graph_client.text().strip())
        job.emitter.code_ready.connect(self._graph_show_code)
        job.emitter.done.connect(self._graph_done)
        self._auth_job = job
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

    # -- SharePoint destination (inline) ---------------------------------

    def _sp_find(self) -> None:
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtWidgets import QMessageBox
        from . import msgraph
        if not msgraph.connected_account():
            QMessageBox.information(self, "Wondershot", "Connect first.")
            return
        query = self.sp_search.text().strip()
        if not query:
            return
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            token = msgraph.ensure_access_token()
            self._sites_cache = msgraph.sites_search(token, query)
        except OSError as e:
            self.sp_current.setText(f"search failed: {e}")
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        self.sp_site_combo.blockSignals(True)
        self.sp_site_combo.clear()
        for site in self._sites_cache:
            self.sp_site_combo.addItem(f'{site["name"]} — {site["url"]}')
        self.sp_site_combo.blockSignals(False)
        if self._sites_cache:
            self._sp_site_chosen()
        else:
            self.sp_current.setText("no sites matched")

    def _sp_site_chosen(self) -> None:
        from PySide6.QtGui import QGuiApplication
        from . import msgraph
        i = self.sp_site_combo.currentIndex()
        if i < 0 or i >= len(self._sites_cache):
            return
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            token = msgraph.ensure_access_token()
            self._drives_cache = msgraph.site_drives(
                token, self._sites_cache[i]["id"])
        except OSError as e:
            self.sp_current.setText(f"load failed: {e}")
            return
        finally:
            QGuiApplication.restoreOverrideCursor()
        self.sp_lib_combo.blockSignals(True)
        self.sp_lib_combo.clear()
        for d in self._drives_cache:
            self.sp_lib_combo.addItem(d["name"])
        self.sp_lib_combo.blockSignals(False)
        if self._drives_cache:
            self._sp_lib_chosen()

    def _sp_lib_chosen(self) -> None:
        si = self.sp_site_combo.currentIndex()
        di = self.sp_lib_combo.currentIndex()
        if not (0 <= si < len(self._sites_cache)):
            return
        if not (0 <= di < len(self._drives_cache)):
            return
        site = self._sites_cache[si]
        drive = self._drives_cache[di]
        label = f'{site["name"]} / {drive["name"]}'
        self.settings.graph_drive_id = drive["id"]
        self.settings.graph_drive_label = label
        self.sp_current.setText(label)

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
        from .msgraph import DEFAULT_CLIENT_ID
        self.settings.graph_client_id = (
            self.graph_client.text().strip() or DEFAULT_CLIENT_ID)
        self.settings.share_expiry_days = self.share_expiry.value()
        for field in ("s3_endpoint", "s3_region", "s3_bucket",
                      "s3_access_key", "s3_secret_key",
                      "azure_account", "azure_container", "azure_key"):
            setattr(self.settings, field, getattr(self, field).text().strip())
        return moved
