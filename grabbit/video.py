"""In-app video playback pane with GIF conversion."""

from __future__ import annotations

import os
import shutil

from PySide6.QtCore import QProcess, Qt, QUrl, Signal
from PySide6.QtGui import QIcon
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)


def _fmt_ms(ms: int) -> str:
    s = max(0, ms) // 1000
    return f"{s // 60}:{s % 60:02d}"


class VideoPane(QWidget):
    gif_ready = Signal(str)  # path of the converted gif
    status = Signal(str, int)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.path: str | None = None
        self._gif_proc: QProcess | None = None

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.video = QVideoWidget(self)
        self.player.setVideoOutput(self.video)
        self.video.setStyleSheet("background: #1a1a1d;")

        self.play_btn = QPushButton(self)
        self.play_btn.setIcon(QIcon.fromTheme("media-playback-start"))
        self.play_btn.setFixedWidth(44)
        self.play_btn.clicked.connect(self.toggle)

        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self.player.setPosition)

        self.time_label = QLabel("0:00 / 0:00", self)

        self.gif_btn = QPushButton("Convert to GIF", self)
        self.gif_btn.setIcon(QIcon.fromTheme("video-x-generic"))
        self.gif_btn.clicked.connect(self._convert_gif)
        self.gif_btn.setEnabled(shutil.which("ffmpeg") is not None)

        controls = QHBoxLayout()
        controls.setContentsMargins(8, 4, 8, 4)
        controls.addWidget(self.play_btn)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.time_label)
        controls.addSpacing(12)
        controls.addWidget(self.gif_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.video, 1)
        layout.addLayout(controls)

        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.playbackStateChanged.connect(self._state_changed)
        self.player.mediaStatusChanged.connect(self._media_status)

    # -- playback ---------------------------------------------------------

    def load(self, path: str) -> None:
        self.path = path
        is_gif = path.lower().endswith(".gif")
        self.player.setSource(QUrl.fromLocalFile(path))
        # GIFs: autoplay and loop forever; videos: show the first frame
        # paused and wait for the user to hit play.
        self.player.setLoops(QMediaPlayer.Loops.Infinite if is_gif else 1)
        self.gif_btn.setVisible(not is_gif)
        self._pause_on_load = not is_gif
        self.player.play()

    def stop(self) -> None:
        self.player.stop()
        self.player.setSource(QUrl())
        self.path = None

    def toggle(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _media_status(self, status) -> None:
        if (getattr(self, "_pause_on_load", False)
                and status == QMediaPlayer.BufferedMedia):
            self._pause_on_load = False
            self.player.pause()
            self.player.setPosition(0)

    def _state_changed(self, state) -> None:
        playing = state == QMediaPlayer.PlayingState
        self.play_btn.setIcon(QIcon.fromTheme(
            "media-playback-pause" if playing else "media-playback-start"))

    def _position_changed(self, pos: int) -> None:
        if not self.slider.isSliderDown():
            self.slider.setValue(pos)
        self.time_label.setText(
            f"{_fmt_ms(pos)} / {_fmt_ms(self.player.duration())}")

    def _duration_changed(self, dur: int) -> None:
        self.slider.setRange(0, dur)

    # -- gif conversion ------------------------------------------------------

    def _convert_gif(self) -> None:
        if not self.path or self._gif_proc is not None:
            return
        from .capture import unique_path
        base = os.path.splitext(os.path.basename(self.path))[0]
        out = unique_path(self.settings.library_dir, f"{base}.gif")
        vf = ("fps=12,scale='min(720,iw)':-1:flags=lanczos,"
              "split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse")
        self._gif_proc = QProcess(self)
        self._gif_proc.finished.connect(
            lambda code, _st: self._gif_done(code, out))
        self.gif_btn.setEnabled(False)
        self.gif_btn.setText("Converting…")
        self.status.emit("Converting to GIF…", 0)
        self._gif_proc.start("ffmpeg", ["-y", "-i", self.path,
                                        "-vf", vf, out])

    def _gif_done(self, code: int, out: str) -> None:
        proc, self._gif_proc = self._gif_proc, None
        if proc is not None:
            proc.deleteLater()
        self.gif_btn.setEnabled(True)
        self.gif_btn.setText("Convert to GIF")
        if code == 0 and os.path.exists(out):
            self.status.emit(f"GIF saved: {os.path.basename(out)}", 4000)
            self.gif_ready.emit(out)
        else:
            self.status.emit("GIF conversion failed", 4000)
            if os.path.exists(out):
                os.unlink(out)
