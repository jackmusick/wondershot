"""App settings backed by QSettings (~/.config/grabbit/grabbit.conf)."""

from __future__ import annotations

import os

from PySide6.QtCore import QSettings, QStandardPaths


def _default_library() -> str:
    pictures = QStandardPaths.writableLocation(QStandardPaths.PicturesLocation)
    return os.path.join(pictures or os.path.expanduser("~/Pictures"), "Screenshots")


class Settings:
    def __init__(self):
        self._s = QSettings("grabbit", "grabbit")

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
