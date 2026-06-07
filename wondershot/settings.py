"""App settings backed by QSettings (~/.config/wondershot/wondershot.conf)."""

from __future__ import annotations

import os

from PySide6.QtCore import QSettings, QStandardPaths


def _default_library() -> str:
    pictures = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
    return os.path.join(pictures or os.path.expanduser("~/Pictures"), "Screenshots")


class Settings:
    def __init__(self):
        self._s = QSettings("wondershot", "wondershot")
        self._migrate_grabbit()

    def _migrate_grabbit(self) -> None:
        """One-time copy of the pre-rename config (grabbit → wondershot)."""
        if self._s.allKeys():
            return
        old = QSettings("grabbit", "grabbit")
        for key in old.allKeys():
            self._s.setValue(key, old.value(key))
        if old.allKeys():
            self._s.sync()

    @property
    def library_dir(self) -> str:
        path = self._s.value("library_dir", _default_library())
        os.makedirs(path, exist_ok=True)
        return path

    @library_dir.setter
    def library_dir(self, value: str) -> None:
        self._s.setValue("library_dir", value)

    @property
    def extra_dirs(self) -> list[str]:
        """Additional folders shown in the gallery (e.g. screen recordings)."""
        raw = self._s.value("extra_dirs", "")
        if not raw:
            # sensible default: pick up screen recordings if the dirs exist
            videos = QStandardPaths.writableLocation(
                QStandardPaths.MoviesLocation)
            candidates = [videos, os.path.join(videos or "", "Screencasts")]
            return [d for d in candidates if d and os.path.isdir(d)]
        return [d for d in raw.split(";") if d]

    @extra_dirs.setter
    def extra_dirs(self, dirs: list[str]) -> None:
        self._s.setValue("extra_dirs", ";".join(dirs))

    @property
    def backend(self) -> str:
        """'auto' | 'spectacle' | 'portal'"""
        return self._s.value("backend", "auto")

    @backend.setter
    def backend(self, value: str) -> None:
        self._s.setValue("backend", value)

    @property
    def camera_device(self) -> str:
        """Preferred camera description for the bubble ('' = default)."""
        return self._s.value("camera_device", "")

    @camera_device.setter
    def camera_device(self, value: str) -> None:
        self._s.setValue("camera_device", value)

    @property
    def mic_enabled(self) -> bool:
        return self._s.value("mic_enabled", "true") in (True, "true")

    @mic_enabled.setter
    def mic_enabled(self, value: bool) -> None:
        self._s.setValue("mic_enabled", "true" if value else "false")

    @property
    def mic_device(self) -> str:
        """Preferred microphone description ('' = default)."""
        return self._s.value("mic_device", "")

    @mic_device.setter
    def mic_device(self, value: str) -> None:
        self._s.setValue("mic_device", value)

    @property
    def noise_suppression(self) -> bool:
        return self._s.value("noise_suppression", "true") in (True, "true")

    @noise_suppression.setter
    def noise_suppression(self, value: bool) -> None:
        self._s.setValue("noise_suppression", "true" if value else "false")

    @property
    def capture_cursor(self) -> bool:
        """Include the pointer in screenshots (Spectacle backend only)."""
        return self._s.value("capture_cursor", "false") in (True, "true")

    @capture_cursor.setter
    def capture_cursor(self, value: bool) -> None:
        self._s.setValue("capture_cursor", "true" if value else "false")

    @property
    def capture_delay(self) -> int:
        """Seconds to wait before taking the shot."""
        return int(self._s.value("capture_delay", 0))

    @capture_delay.setter
    def capture_delay(self, value: int) -> None:
        self._s.setValue("capture_delay", int(value))

    # -- output effects (applied at save/flatten; persisted defaults) -------

    @property
    def effect_rounded(self) -> bool:
        return self._s.value("effect_rounded", "false") in (True, "true")

    @effect_rounded.setter
    def effect_rounded(self, value: bool) -> None:
        self._s.setValue("effect_rounded", "true" if value else "false")

    @property
    def effect_corner_radius(self) -> int:
        return int(self._s.value("effect_corner_radius", 16))

    @effect_corner_radius.setter
    def effect_corner_radius(self, value: int) -> None:
        self._s.setValue("effect_corner_radius", int(value))

    @property
    def effect_fade(self) -> bool:
        return self._s.value("effect_fade", "false") in (True, "true")

    @effect_fade.setter
    def effect_fade(self, value: bool) -> None:
        self._s.setValue("effect_fade", "true" if value else "false")

    @property
    def effect_fade_height(self) -> int:
        return int(self._s.value("effect_fade_height", 96))

    @effect_fade_height.setter
    def effect_fade_height(self, value: int) -> None:
        self._s.setValue("effect_fade_height", int(value))

    # -- sharing (S3-compatible / Azure Blob) -------------------------------
    # NOTE: credentials are stored in plaintext QSettings; the dialog
    # warns about this.

    _SHARE_KEYS = ("share_provider", "share_expiry_days",
                   "s3_endpoint", "s3_region", "s3_bucket",
                   "s3_access_key", "s3_secret_key",
                   "azure_account", "azure_container", "azure_key")

    @property
    def share_provider(self) -> str:
        """Default provider for the Share button: 's3' | 'azure' | ''."""
        return self._s.value("share_provider", "")

    @share_provider.setter
    def share_provider(self, value: str) -> None:
        self._s.setValue("share_provider", value)

    @property
    def graph_client_id(self) -> str:
        from .msgraph import DEFAULT_CLIENT_ID
        return self._s.value("graph_client_id", DEFAULT_CLIENT_ID)

    @graph_client_id.setter
    def graph_client_id(self, value: str) -> None:
        self._s.setValue("graph_client_id", value)

    @property
    def graph_drive_id(self) -> str:
        """'' = signed-in account's OneDrive; else a SharePoint drive id."""
        return self._s.value("graph_drive_id", "")

    @graph_drive_id.setter
    def graph_drive_id(self, value: str) -> None:
        self._s.setValue("graph_drive_id", value)

    @property
    def graph_drive_label(self) -> str:
        return self._s.value("graph_drive_label", "")

    @graph_drive_label.setter
    def graph_drive_label(self, value: str) -> None:
        self._s.setValue("graph_drive_label", value)

    @property
    def share_expiry_days(self) -> int:
        return int(self._s.value("share_expiry_days", 7))

    @share_expiry_days.setter
    def share_expiry_days(self, value: int) -> None:
        self._s.setValue("share_expiry_days", int(value))

    def _str_prop(key):  # noqa: N805 — tiny local factory
        def fget(self):
            return self._s.value(key, "")

        def fset(self, value):
            self._s.setValue(key, value)
        return property(fget, fset)

    s3_endpoint = _str_prop("s3_endpoint")
    s3_region = _str_prop("s3_region")
    s3_bucket = _str_prop("s3_bucket")
    s3_access_key = _str_prop("s3_access_key")
    s3_secret_key = _str_prop("s3_secret_key")
    azure_account = _str_prop("azure_account")
    azure_container = _str_prop("azure_container")
    azure_key = _str_prop("azure_key")
    del _str_prop

    # -- editor tool defaults (persist the last-used values) ---------------

    @property
    def stroke_width(self) -> int:
        return int(self._s.value("stroke_width", 10))

    @stroke_width.setter
    def stroke_width(self, value: int) -> None:
        self._s.setValue("stroke_width", int(value))

    @property
    def font_size(self) -> int:
        return int(self._s.value("font_size", 24))

    @font_size.setter
    def font_size(self, value: int) -> None:
        self._s.setValue("font_size", int(value))

    @property
    def tool_color(self) -> str:
        return self._s.value("tool_color", "#e3242b")

    @tool_color.setter
    def tool_color(self, value: str) -> None:
        self._s.setValue("tool_color", value)

    @property
    def screencast_token(self) -> str:
        """Portal restore token so the share picker shows only once."""
        return self._s.value("screencast_token", "")

    @screencast_token.setter
    def screencast_token(self, value: str) -> None:
        self._s.setValue("screencast_token", value)

    @property
    def copy_after_capture(self) -> bool:
        return self._s.value("copy_after_capture", "true") in (True, "true")

    @copy_after_capture.setter
    def copy_after_capture(self, value: bool) -> None:
        self._s.setValue("copy_after_capture", "true" if value else "false")

    @property
    def show_gallery_after_capture(self) -> bool:
        return self._s.value("show_gallery_after_capture", "true") in (True, "true")

    @show_gallery_after_capture.setter
    def show_gallery_after_capture(self, value: bool) -> None:
        self._s.setValue("show_gallery_after_capture", "true" if value else "false")

    @property
    def pin_on_top(self) -> bool:
        return self._s.value("pin_on_top", "false") in (True, "true")

    @pin_on_top.setter
    def pin_on_top(self, value: bool) -> None:
        self._s.setValue("pin_on_top", "true" if value else "false")

    # -- AI (OpenAI-compatible chat endpoint) -------------------------------
    # NOTE: the API key is stored in plaintext QSettings, same as the
    # S3/Azure credentials; the AI tab warns about this.

    @property
    def ai_endpoint(self) -> str:
        """Base URL, e.g. https://api.openai.com or http://localhost:11434."""
        return self._s.value("ai_endpoint", "")

    @ai_endpoint.setter
    def ai_endpoint(self, value: str) -> None:
        self._s.setValue("ai_endpoint", value)

    @property
    def ai_api_key(self) -> str:
        return self._s.value("ai_api_key", "")

    @ai_api_key.setter
    def ai_api_key(self, value: str) -> None:
        self._s.setValue("ai_api_key", value)

    @property
    def ai_model(self) -> str:
        return self._s.value("ai_model", "")

    @ai_model.setter
    def ai_model(self, value: str) -> None:
        self._s.setValue("ai_model", value)
