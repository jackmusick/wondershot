"""In-app video playback pane with GIF conversion and range blurring."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass

from PySide6.QtCore import QEvent, QPoint, QProcess, QRect, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


def _fmt_ms(ms: int) -> str:
    s = max(0, ms) // 1000
    return f"{s // 60}:{s % 60:02d}"


@dataclass
class Redaction:
    """A blur region active for a span of the video, in video pixel coords."""
    rect: QRect
    start: float  # seconds
    end: float


def build_blur_filter(redactions, blur: int = 14,
                      video_w: int = 0, video_h: int = 0) -> tuple[str, str]:
    """ffmpeg filter_complex applying each redaction as a blurred overlay
    enabled only inside its time range. Returns (graph, output_label)."""
    n = len(redactions)
    splits = "".join(f"[c{i}]" for i in range(n))
    parts = [f"[0:v]split={n + 1}[base]{splits}"]
    cur = "base"
    for i, r in enumerate(redactions):
        x, y = max(0, r.rect.x()), max(0, r.rect.y())
        w, h = r.rect.width(), r.rect.height()
        if video_w and video_h:  # clamp to frame
            x, y = min(x, video_w - 4), min(y, video_h - 4)
            w = min(w, video_w - x)
            h = min(h, video_h - y)
        w, h = max(4, w - w % 2), max(4, h - h % 2)  # encoders want even dims
        x, y = x - x % 2, y - y % 2
        parts.append(f"[c{i}]crop={w}:{h}:{x}:{y},boxblur={blur}[b{i}]")
        out = f"v{i}"
        parts.append(
            f"[{cur}][b{i}]overlay={x}:{y}:"
            f"enable='between(t,{r.start:.3f},{r.end:.3f})'[{out}]")
        cur = out
    return ";".join(parts), cur


_encoder_cache: str | None = None


def pick_encoder() -> str:
    """Best available H.264-ish encoder on this system."""
    global _encoder_cache
    if _encoder_cache is None:
        try:
            out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"],
                                 capture_output=True, text=True,
                                 timeout=10).stdout
        except (OSError, subprocess.TimeoutExpired):
            out = ""
        for enc in ("libx264", "libopenh264", "mpeg4"):
            if enc in out:
                _encoder_cache = enc
                break
        else:
            _encoder_cache = "mpeg4"
    return _encoder_cache


class RedactOverlay(QWidget):
    """Transparent layer over the video for drawing/showing blur regions."""

    region_drawn = Signal(QRect)  # video pixel coords

    def __init__(self, video_widget: QVideoWidget, pane: "VideoPane"):
        super().__init__(video_widget)
        self.pane = pane
        self.active = False
        self._origin: QPoint | None = None
        self._band: QRect | None = None
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        video_widget.installEventFilter(self)
        self.setGeometry(video_widget.rect())

    def eventFilter(self, obj, ev):  # noqa: N802
        if ev.type() == QEvent.Resize:
            self.setGeometry(obj.rect())
        return False

    def set_active(self, on: bool) -> None:
        self.active = on
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not on)
        self.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)
        self._origin = self._band = None
        self.update()

    # -- coordinate mapping -------------------------------------------------

    def _video_size(self):
        sink = self.pane.player.videoSink()
        return sink.videoSize() if sink else None

    def display_rect(self) -> QRectF:
        """Where the (aspect-fit) video actually sits inside this widget."""
        vs = self._video_size()
        if not vs or vs.isEmpty():
            return QRectF(self.rect())
        scale = min(self.width() / vs.width(), self.height() / vs.height())
        w, h = vs.width() * scale, vs.height() * scale
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def widget_to_video(self, r: QRect) -> QRect:
        disp = self.display_rect()
        vs = self._video_size()
        if not vs or disp.width() < 1:
            return QRect()
        sx, sy = vs.width() / disp.width(), vs.height() / disp.height()
        out = QRect(round((r.x() - disp.x()) * sx),
                    round((r.y() - disp.y()) * sy),
                    round(r.width() * sx), round(r.height() * sy))
        return out.intersected(QRect(0, 0, vs.width(), vs.height()))

    def video_to_widget(self, r: QRect) -> QRectF:
        disp = self.display_rect()
        vs = self._video_size()
        if not vs or vs.isEmpty():
            return QRectF()
        sx, sy = disp.width() / vs.width(), disp.height() / vs.height()
        return QRectF(disp.x() + r.x() * sx, disp.y() + r.y() * sy,
                      r.width() * sx, r.height() * sy)

    # -- interaction ---------------------------------------------------------

    def mousePressEvent(self, ev):  # noqa: N802
        if self.active and ev.button() == Qt.LeftButton:
            self._origin = ev.position().toPoint()
            self._band = QRect(self._origin, self._origin)
            self.update()

    def mouseMoveEvent(self, ev):  # noqa: N802
        if self._origin is not None:
            self._band = QRect(self._origin,
                               ev.position().toPoint()).normalized()
            self.update()

    def mouseReleaseEvent(self, ev):  # noqa: N802
        if self._origin is None:
            return
        band, self._origin, self._band = self._band, None, None
        self.update()
        if band is not None and band.width() > 6 and band.height() > 6:
            video_rect = self.widget_to_video(band)
            if not video_rect.isEmpty():
                self.region_drawn.emit(video_rect)

    def paintEvent(self, _ev):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # existing redactions
        for i, red in enumerate(self.pane.redactions):
            r = self.video_to_widget(red.rect)
            p.setPen(QPen(QColor("#ff5555"), 2, Qt.DashLine))
            p.setBrush(QColor(255, 80, 80, 50))
            p.drawRect(r)
            p.setPen(QColor("white"))
            p.drawText(r.adjusted(6, 4, 0, 0).topLeft() + QPoint(0, 12),
                       f"{i + 1}")
        # live band
        if self._band is not None:
            p.setPen(QPen(QColor("#3daee9"), 2, Qt.DashLine))
            p.setBrush(QColor(61, 174, 233, 50))
            p.drawRect(self._band)
        elif self.active and not self.pane.redactions:
            p.setPen(QColor(255, 255, 255, 200))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "Drag a box over the area to blur")
        p.end()


class VideoPane(QWidget):
    file_ready = Signal(str)  # a new file (gif / redacted video) was produced
    status = Signal(str, int)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.path: str | None = None
        self._gif_proc: QProcess | None = None
        self._blur_proc: QProcess | None = None
        self.redactions: list[Redaction] = []

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.video = QVideoWidget(self)
        self.player.setVideoOutput(self.video)
        self.video.setStyleSheet("background: #1a1a1d;")
        self.overlay = RedactOverlay(self.video, self)
        self.overlay.region_drawn.connect(self._region_drawn)

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

        self.blur_btn = QPushButton("Blur region", self)
        self.blur_btn.setIcon(QIcon.fromTheme("view-private"))
        self.blur_btn.setCheckable(True)
        self.blur_btn.toggled.connect(self._blur_mode)
        self.blur_btn.setEnabled(shutil.which("ffmpeg") is not None)

        self.apply_btn = QPushButton("Apply blurs", self)
        self.apply_btn.setIcon(QIcon.fromTheme("dialog-ok-apply"))
        self.apply_btn.clicked.connect(self._apply_blurs)
        self.apply_btn.hide()

        controls = QHBoxLayout()
        controls.setContentsMargins(8, 4, 8, 4)
        controls.addWidget(self.play_btn)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.time_label)
        controls.addSpacing(12)
        controls.addWidget(self.blur_btn)
        controls.addWidget(self.apply_btn)
        controls.addWidget(self.gif_btn)

        # rows describing each redaction's time range
        self.redact_box = QWidget(self)
        self.redact_rows = QVBoxLayout(self.redact_box)
        self.redact_rows.setContentsMargins(8, 0, 8, 4)
        self.redact_rows.setSpacing(2)
        self.redact_box.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.video, 1)
        layout.addLayout(controls)
        layout.addWidget(self.redact_box)

        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.playbackStateChanged.connect(self._state_changed)
        self.player.mediaStatusChanged.connect(self._media_status)

    # -- playback ---------------------------------------------------------

    def load(self, path: str) -> None:
        self.path = path
        self._clear_redactions()
        is_gif = path.lower().endswith(".gif")
        self.blur_btn.setVisible(not is_gif)
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
        self._clear_redactions()

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

    # -- redaction ------------------------------------------------------------

    def _blur_mode(self, on: bool) -> None:
        if on:
            self.player.pause()
        self.overlay.set_active(on)

    def _region_drawn(self, video_rect: QRect) -> None:
        start = self.player.position() / 1000.0
        duration = self.player.duration() / 1000.0 or start + 5
        self.redactions.append(
            Redaction(video_rect, round(start, 1),
                      round(min(duration, start + 5), 1)))
        self.blur_btn.setChecked(False)
        self._rebuild_rows()
        self.overlay.update()

    def _clear_redactions(self) -> None:
        self.redactions.clear()
        self.blur_btn.setChecked(False)
        self._rebuild_rows()
        self.overlay.update()

    def _rebuild_rows(self) -> None:
        while self.redact_rows.count():
            item = self.redact_rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, red in enumerate(self.redactions):
            self.redact_rows.addWidget(self._make_row(i, red))
        has = bool(self.redactions)
        self.redact_box.setVisible(has)
        self.apply_btn.setVisible(has)
        self.apply_btn.setText(f"Apply blurs ({len(self.redactions)})")

    def _make_row(self, i: int, red: Redaction) -> QWidget:
        row = QWidget(self.redact_box)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(QLabel(f"Blur {i + 1}:", row))

        duration = max(self.player.duration() / 1000.0, red.end)

        def spin(value):
            s = QDoubleSpinBox(row)
            s.setRange(0.0, duration)
            s.setDecimals(1)
            s.setSingleStep(0.5)
            s.setSuffix(" s")
            s.setValue(value)
            return s

        start_spin, end_spin = spin(red.start), spin(red.end)
        start_spin.valueChanged.connect(
            lambda v, r=red: setattr(r, "start", v))
        end_spin.valueChanged.connect(lambda v, r=red: setattr(r, "end", v))

        def at_playhead(target_spin):
            target_spin.setValue(self.player.position() / 1000.0)

        from_btn = QToolButton(row)
        from_btn.setText("⌖")
        from_btn.setToolTip("Set start to playhead")
        from_btn.clicked.connect(lambda: at_playhead(start_spin))
        to_btn = QToolButton(row)
        to_btn.setText("⌖")
        to_btn.setToolTip("Set end to playhead")
        to_btn.clicked.connect(lambda: at_playhead(end_spin))

        rm = QToolButton(row)
        rm.setIcon(QIcon.fromTheme("edit-delete"))
        rm.setToolTip("Remove this blur")

        def remove():
            if red in self.redactions:
                self.redactions.remove(red)
            self._rebuild_rows()
            self.overlay.update()

        rm.clicked.connect(remove)

        lay.addWidget(QLabel("from", row))
        lay.addWidget(start_spin)
        lay.addWidget(from_btn)
        lay.addWidget(QLabel("to", row))
        lay.addWidget(end_spin)
        lay.addWidget(to_btn)
        lay.addStretch(1)
        lay.addWidget(rm)
        return row

    def _apply_blurs(self) -> None:
        if not self.path or not self.redactions or self._blur_proc is not None:
            return
        bad = [i + 1 for i, r in enumerate(self.redactions)
               if r.end <= r.start]
        if bad:
            self.status.emit(
                f"Blur {bad[0]}: end must be after start", 4000)
            return
        from .capture import unique_path
        sink = self.player.videoSink()
        vs = sink.videoSize() if sink else None
        graph, out_label = build_blur_filter(
            self.redactions,
            video_w=vs.width() if vs else 0,
            video_h=vs.height() if vs else 0)
        base, ext = os.path.splitext(os.path.basename(self.path))
        out = unique_path(self.settings.library_dir, f"{base}-redacted{ext}")
        enc = pick_encoder()
        enc_opts = (["-crf", "20", "-preset", "veryfast"]
                    if enc == "libx264" else ["-q:v", "4"])
        args = ["-y", "-i", self.path, "-filter_complex", graph,
                "-map", f"[{out_label}]", "-map", "0:a?", "-c:a", "copy",
                "-c:v", enc, *enc_opts, out]
        self._blur_proc = QProcess(self)
        self._blur_proc.finished.connect(
            lambda code, _st: self._blur_done(code, out))
        self.apply_btn.setEnabled(False)
        self.apply_btn.setText("Rendering…")
        self.status.emit("Rendering blurred video…", 0)
        self._blur_proc.start("ffmpeg", args)

    def _blur_done(self, code: int, out: str) -> None:
        proc, self._blur_proc = self._blur_proc, None
        if proc is not None:
            err = bytes(proc.readAllStandardError()).decode(errors="replace")
            proc.deleteLater()
        else:
            err = ""
        self.apply_btn.setEnabled(True)
        self._rebuild_rows()
        if code == 0 and os.path.exists(out) and os.path.getsize(out) > 0:
            self._clear_redactions()
            self.status.emit(f"Saved {os.path.basename(out)}", 4000)
            self.file_ready.emit(out)
        else:
            tail = err.strip().splitlines()[-1] if err.strip() else "unknown"
            self.status.emit(f"Blur render failed: {tail[:120]}", 6000)
            if os.path.exists(out):
                os.unlink(out)

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
            self.file_ready.emit(out)
        else:
            self.status.emit("GIF conversion failed", 4000)
            if os.path.exists(out):
                os.unlink(out)
