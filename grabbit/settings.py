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
