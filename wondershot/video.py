"""In-app video playback with range-blur redaction and GIF conversion.

Playback uses QVideoWidget (the GPU-accelerated path — QGraphicsVideoItem
lagged on 60fps screencasts, and an QOpenGLWidget viewport rendered blank on
Wayland). Blur regions are painted by a transparent sibling widget stacked
above the video, with explicit widget↔video coordinate mapping through the
aspect-fit rectangle.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass

from . import ffmpegutil

from PySide6.QtCore import QPoint, QPointF, QProcess, QRect, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPen
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QCheckBox,
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


def build_frame_grab_args(src: str, position_s: float, out: str) -> list[str]:
    """ffmpeg args extracting one frame at position_s seconds.

    -ss before -i = fast input seek; with -frames:v 1 the decoder lands on
    the frame at/just after the seek point. This sidesteps grabbing from
    QVideoSink, whose Wayland subsurface frames aren't reliably readable.
    """
    return ["-y", "-ss", f"{position_s:.3f}", "-i", src,
            "-frames:v", "1", out]


def frame_output_name(src_name: str) -> str:
    """'<video-stem>-frame.png' library name for a grabbed frame."""
    return f"{os.path.splitext(src_name)[0]}-frame.png"


def trim_output_name(src_name: str, reencode: bool) -> str:
    """'<stem>-trimmed.<ext>' library name.

    Stream copy must keep the source container (H.264 can't live in WebM
    and vice versa — same constraint the blur pass handles); re-encode is
    always x264-family, so it always lands in .mp4.
    """
    base, ext = os.path.splitext(src_name)
    return f"{base}-trimmed{'.mp4' if reencode else ext}"


def build_trim_args(src: str, start_s: float, end_s: float, out: str,
                    reencode: bool, encoder: str = "libx264") -> list[str]:
    """ffmpeg args trimming src to [start_s, end_s].

    Both -ss and -to are INPUT options (before -i), so both are absolute
    source timestamps. Stream copy snaps the start back to the previous
    keyframe (instant, lossless); re-encode decodes from that keyframe and
    cuts exactly (frame-accurate, slower).
    """
    args = ["-y", "-ss", f"{start_s:.3f}", "-to", f"{end_s:.3f}", "-i", src]
    if reencode:
        enc_opts = (["-crf", "20", "-preset", "veryfast"]
                    if encoder == "libx264" else ["-q:v", "4"])
        args += ["-c:v", encoder, *enc_opts, "-c:a", "aac", "-b:a", "160k"]
    else:
        args += ["-c", "copy"]
    if os.path.splitext(out)[1].lower() in (".mp4", ".m4v", ".mov"):
        args += ["-movflags", "+faststart"]  # instant seeking
    return [*args, out]


_encoder_cache: str | None = None


def pick_encoder() -> str:
    """Best available H.264-ish encoder on this system."""
    global _encoder_cache
    if _encoder_cache is None:
        try:
            out = ffmpegutil.run_ffmpeg(["-hide_banner", "-encoders"],
                                        timeout=10).stdout
        except (ffmpegutil.FfmpegMissing, OSError,
                subprocess.TimeoutExpired):
            out = ""
        for enc in ("libx264", "libopenh264", "mpeg4"):
            if enc in out:
                _encoder_cache = enc
                break
        else:
            _encoder_cache = "mpeg4"
    return _encoder_cache


PALETTE = ["#e05555", "#e0a030", "#46a3e0", "#9a59d0", "#43b97f"]


class RedactOverlay(QWidget):
    """Transparent sibling stacked above the video widget: draws the drag
    band and the frosted blur regions, and maps widget↔video coordinates."""

    region_drawn = Signal(QRect)  # video pixel coords

    def __init__(self, parent: QWidget, pane: "VideoPane"):
        super().__init__(parent)
        self.pane = pane
        self.active = False
        self._origin: QPoint | None = None
        self._band: QRect | None = None
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def set_active(self, on: bool) -> None:
        self.active = on
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not on)
        self.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)
        self._origin = self._band = None
        self.update()

    # -- coordinate mapping ---------------------------------------------------

    def _video_size(self):
        sink = self.pane.player.videoSink()
        if sink is None:
            return None
        size = sink.videoSize()
        return size if size.isValid() and not size.isEmpty() else None

    def display_rect(self) -> QRectF:
        """Where the (aspect-fit) video actually sits inside this widget."""
        vs = self._video_size()
        if vs is None:
            return QRectF(self.rect())
        scale = min(self.width() / vs.width(), self.height() / vs.height())
        w, h = vs.width() * scale, vs.height() * scale
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def widget_to_video(self, r: QRect) -> QRect:
        disp = self.display_rect()
        vs = self._video_size()
        if vs is None or disp.width() < 1:
            return QRect()
        sx, sy = vs.width() / disp.width(), vs.height() / disp.height()
        out = QRect(round((r.x() - disp.x()) * sx),
                    round((r.y() - disp.y()) * sy),
                    round(r.width() * sx), round(r.height() * sy))
        return out.intersected(QRect(0, 0, vs.width(), vs.height()))

    def video_to_widget(self, r: QRect) -> QRectF:
        disp = self.display_rect()
        vs = self._video_size()
        if vs is None:
            return QRectF()
        sx, sy = disp.width() / vs.width(), disp.height() / vs.height()
        return QRectF(disp.x() + r.x() * sx, disp.y() + r.y() * sy,
                      r.width() * sx, r.height() * sy)

    # -- interaction -------------------------------------------------------------

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

    def mouseReleaseEvent(self, _ev):  # noqa: N802
        if self._origin is None:
            return
        band, self._origin, self._band = self._band, None, None
        self.update()
        if band is not None and band.width() > 6 and band.height() > 6:
            video_rect = self.widget_to_video(band)
            if not video_rect.isEmpty():
                self.region_drawn.emit(video_rect)

    # -- painting ------------------------------------------------------------------

    def paintEvent(self, _ev):  # noqa: N802
        # Wayland won't composite a translucent widget over the video
        # surface, so when the player is paused (drawing and scrubbing both
        # happen paused) we paint the current frame OURSELVES and decorate
        # on top. While playing we paint nothing and playback stays on the
        # fast path.
        if not self.pane.frozen_mode():
            return
        frame_img = self.pane.last_frame_image()
        if frame_img is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(26, 26, 29))
        disp = self.display_rect()
        p.drawImage(disp, frame_img)
        t = self.pane.player.position() / 1000.0
        for i, red in enumerate(self.pane.redactions):
            # Frost only inside its span — scrubbing previews what gets
            # blurred and when.
            if not (red.start <= t <= red.end):
                continue
            r = self.video_to_widget(red.rect)
            color = QColor(PALETTE[i % len(PALETTE)])
            p.setPen(QPen(color, 2, Qt.DashLine))
            p.setBrush(QColor(255, 255, 255, 70))
            p.drawRect(r)
            f = p.font()
            f.setBold(True)
            f.setPointSize(13)
            p.setFont(f)
            p.setPen(QColor("white"))
            p.drawText(r.adjusted(8, 6, 0, 0).topLeft() + QPoint(0, 14),
                       str(i + 1))
        if self._band is not None:
            p.setPen(QPen(QColor("#3daee9"), 2, Qt.DashLine))
            p.setBrush(QColor(61, 174, 233, 50))
            p.drawRect(self._band)
        elif self.active:
            p.setPen(QColor(255, 255, 255, 210))
            p.drawText(self.rect(), Qt.AlignCenter,
                       "Drag a box over the area to blur")
        p.end()


class VideoStack(QWidget):
    """Container keeping the overlay glued on top of the video widget."""

    def __init__(self, pane: "VideoPane"):
        super().__init__(pane)
        self.video = QVideoWidget(self)
        self.video.setStyleSheet("background: #1a1a1d;")
        self.overlay = RedactOverlay(self, pane)
        self.overlay.raise_()

    def resizeEvent(self, ev):  # noqa: N802
        super().resizeEvent(ev)
        self.video.setGeometry(self.rect())
        self.overlay.setGeometry(self.rect())
        self.overlay.raise_()


class RangeBar(QWidget):
    """Timeline strip showing each blur's span as a colored band.

    Interactions (video scrubs live during every drag):
    - drag a band's edge: adjust its start/end independently
    - drag inside a band: move the whole span
    - drag on empty bar: define the active blur's span from scratch
    """

    PALETTE = PALETTE
    EDGE_PX = 7

    def __init__(self, pane: "VideoPane"):
        super().__init__(pane)
        self.pane = pane
        self.setFixedHeight(20)
        self.setMouseTracking(True)
        self.setToolTip("Drag edges to adjust · drag inside to move · "
                        "drag empty space to redefine the selected blur")
        self._mode: tuple | None = None  # ("new",t0)|("start",i)|("end",i)|("move",i,offset)

    def _time_at(self, x: float) -> float:
        dur = max(1, self.pane.player.duration())
        return max(0.0, min(dur, x / max(1, self.width()) * dur)) / 1000.0

    def _x_of(self, seconds: float) -> float:
        dur = max(1, self.pane.player.duration())
        return seconds * 1000 / dur * self.width()

    def _hit(self, x: float) -> tuple | None:
        """Edge/inside hit-test, active band first."""
        spans = self.pane.spans()
        active = 0 if self.pane.trim is not None else self.pane.active_idx
        order = []
        if 0 <= active < len(spans):
            order.append(active)
        order += [i for i in range(len(spans)) if i not in order]
        for i in order:
            red = spans[i]
            x1, x2 = self._x_of(red.start), self._x_of(red.end)
            if abs(x - x1) <= self.EDGE_PX:
                return ("start", i)
            if abs(x - x2) <= self.EDGE_PX:
                return ("end", i)
            if x1 < x < x2:
                return ("move", i, self._time_at(x) - red.start)
        return None

    def _scrub(self, t: float) -> None:
        self.pane.player.setPosition(int(t * 1000))

    def mousePressEvent(self, ev):  # noqa: N802
        x = ev.position().x()
        t = self._time_at(x)
        self.pane.player.pause()
        hit = self._hit(x)
        if hit is not None:
            self._mode = hit
            self.pane.set_active(hit[1])
            red = self.pane.spans()[hit[1]]
            self._scrub({"start": red.start, "end": red.end,
                         "move": red.start}[hit[0]])
        elif self.pane.spans():
            self._mode = ("new", t)
            self._scrub(t)
        else:
            self._scrub(t)
        self.update()

    def mouseMoveEvent(self, ev):  # noqa: N802
        x = ev.position().x()
        if self._mode is None:
            hit = self._hit(x)
            if hit is None:
                self.setCursor(Qt.ArrowCursor)
            elif hit[0] in ("start", "end"):
                self.setCursor(Qt.SplitHCursor)
            else:
                self.setCursor(Qt.SizeHorCursor)
            return
        t = self._time_at(x)
        red = self.pane.active_redaction()
        if red is None:
            return
        kind = self._mode[0]
        if kind == "new":
            t0 = self._mode[1]
            red.start = round(min(t0, t), 2)
            red.end = round(max(t0, t), 2)
            self._scrub(t)
        elif kind == "start":
            red.start = round(min(t, red.end - 0.1), 2)
            self._scrub(red.start)
        elif kind == "end":
            red.end = round(max(t, red.start + 0.1), 2)
            self._scrub(red.end)
        elif kind == "move":
            span = red.end - red.start
            dur = self.pane.player.duration() / 1000.0
            new_start = max(0.0, min(t - self._mode[2], dur - span))
            red.start = round(new_start, 2)
            red.end = round(new_start + span, 2)
            self._scrub(red.start)
        self.pane.sync_active_row()
        self.update()

    def mouseReleaseEvent(self, _ev):  # noqa: N802
        self._mode = None
        self.pane.refresh_overlays()
        self.update()

    def paintEvent(self, _ev):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(24, 24, 27))
        p.drawRoundedRect(0, 4, w, h - 8, 4, 4)
        dur = max(1, self.pane.player.duration())
        spans = self.pane.spans()
        active_i = 0 if self.pane.trim is not None else self.pane.active_idx
        for i, red in enumerate(spans):
            x1 = red.start * 1000 / dur * w
            x2 = red.end * 1000 / dur * w
            color = (QColor("#3daee9") if self.pane.trim is not None
                     else QColor(PALETTE[i % len(PALETTE)]))
            active = i == active_i
            color.setAlpha(230 if active else 130)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(x1, 2 if active else 5,
                                     max(3.0, x2 - x1),
                                     (h - 4) if active else (h - 10)), 3, 3)
        # playhead
        x = self.pane.player.position() / dur * w
        p.setPen(QPen(QColor("white"), 2))
        p.drawLine(QPointF(x, 0), QPointF(x, h))
        p.end()


class VideoPane(QWidget):
    file_ready = Signal(str)  # a new file (gif / redacted video) was produced
    status = Signal(str, int)

    share_requested = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.path: str | None = None
        self._gif_proc: QProcess | None = None
        self._blur_proc: QProcess | None = None
        self._frame_proc: QProcess | None = None
        self.redactions: list[Redaction] = []
        self.trim: Redaction | None = None   # rect unused; start/end = kept span
        self._trim_proc: QProcess | None = None
        self.active_idx = -1
        self._row_spins: list[tuple[QDoubleSpinBox, QDoubleSpinBox]] = []
        self._pause_on_load = False

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        # QAudioOutput resolves the default device once at construction;
        # follow the system default as it changes (the backend re-lists
        # devices when the default flag moves between sinks).
        self._media_devices = QMediaDevices(self)
        self._media_devices.audioOutputsChanged.connect(
            self._refresh_audio_device)
        self.stack = VideoStack(self)
        self.player.setVideoOutput(self.stack.video)
        self.overlay = self.stack.overlay
        self.overlay.region_drawn.connect(self._region_drawn)
        # Keep the latest frame so the overlay can paint it while paused
        # (conversion to QImage is deferred to paint time).
        self._last_frame = None
        sink = self.stack.video.videoSink()
        if sink is not None:
            sink.videoFrameChanged.connect(self._frame_changed)

        self.play_btn = QPushButton(self)
        self.play_btn.setIcon(QIcon.fromTheme("media-playback-start"))
        self.play_btn.setFixedWidth(44)
        self.play_btn.clicked.connect(self.toggle)

        self.slider = QSlider(Qt.Horizontal, self)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self.player.setPosition)

        self.time_label = QLabel("0:00 / 0:00", self)

        self.blur_btn = QPushButton("Blur region", self)
        self.blur_btn.setIcon(QIcon.fromTheme("view-private"))
        self.blur_btn.setCheckable(True)
        self.blur_btn.toggled.connect(self._blur_mode)
        self.blur_btn.setEnabled(ffmpegutil.have_ffmpeg())

        self.apply_btn = QPushButton("Apply blurs", self)
        self.apply_btn.setIcon(QIcon.fromTheme("dialog-ok-apply"))
        self.apply_btn.clicked.connect(self._apply_blurs)
        self.apply_btn.hide()

        self.trim_btn = QPushButton("Trim", self)
        self.trim_btn.setIcon(QIcon.fromTheme("edit-cut"))
        self.trim_btn.setCheckable(True)
        self.trim_btn.toggled.connect(self._trim_mode)
        self.trim_btn.setEnabled(ffmpegutil.have_ffmpeg())

        self.trim_accurate = QCheckBox("Frame-accurate (re-encode)", self)
        self.trim_accurate.setToolTip(
            "Default trim is instant but snaps the start to the previous "
            "keyframe; re-encoding cuts exactly but takes longer")
        self.trim_accurate.hide()

        self.trim_apply_btn = QPushButton("Save trim", self)
        self.trim_apply_btn.setIcon(QIcon.fromTheme("dialog-ok-apply"))
        self.trim_apply_btn.clicked.connect(self._apply_trim)
        self.trim_apply_btn.hide()

        self.gif_btn = QPushButton("Convert to GIF", self)
        self.gif_btn.setIcon(QIcon.fromTheme("video-x-generic"))
        self.gif_btn.clicked.connect(self._convert_gif)
        self.gif_btn.setEnabled(ffmpegutil.have_ffmpeg())

        self.frame_btn = QPushButton("Save frame", self)
        self.frame_btn.setIcon(QIcon.fromTheme("camera-photo"))
        self.frame_btn.setToolTip(
            "Save the current frame as a PNG in the library")
        self.frame_btn.clicked.connect(self._save_frame)
        self.frame_btn.setEnabled(ffmpegutil.have_ffmpeg())

        controls = QHBoxLayout()
        controls.setContentsMargins(8, 4, 8, 0)
        controls.addWidget(self.play_btn)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.time_label)
        controls.addSpacing(12)
        controls.addWidget(self.blur_btn)
        controls.addWidget(self.apply_btn)
        controls.addWidget(self.trim_btn)
        controls.addWidget(self.trim_accurate)
        controls.addWidget(self.trim_apply_btn)
        controls.addWidget(self.gif_btn)
        controls.addWidget(self.frame_btn)

        self.range_bar = RangeBar(self)
        self.range_bar.hide()

        self.hint = QLabel(self)
        self.hint.setStyleSheet("color: palette(mid); padding: 0 8px;")
        self.hint.hide()

        # rows describing each redaction's time range
        self.redact_box = QWidget(self)
        self.redact_rows = QVBoxLayout(self.redact_box)
        self.redact_rows.setContentsMargins(8, 0, 8, 4)
        self.redact_rows.setSpacing(2)
        self.redact_box.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self.stack, 1)
        layout.addLayout(controls)
        layout.addWidget(self.range_bar)
        layout.addWidget(self.hint)
        layout.addWidget(self.redact_box)

        self.player.positionChanged.connect(self._position_changed)
        self.player.durationChanged.connect(self._duration_changed)
        self.player.playbackStateChanged.connect(self._state_changed)
        self.player.mediaStatusChanged.connect(self._media_status)

    # -- playback -----------------------------------------------------------

    def load(self, path: str) -> None:
        self.path = path
        self._clear_redactions()
        is_gif = path.lower().endswith(".gif")
        self.blur_btn.setVisible(not is_gif)
        self.trim_btn.setVisible(not is_gif)
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

    def _refresh_audio_device(self) -> None:
        self.audio.setDevice(QMediaDevices.defaultAudioOutput())

    def toggle(self) -> None:
        if self.player.playbackState() == QMediaPlayer.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def _media_status(self, status) -> None:
        if self._pause_on_load and status == QMediaPlayer.BufferedMedia:
            self._pause_on_load = False
            self.player.pause()
            self.player.setPosition(0)

    def _frame_changed(self, frame) -> None:
        if frame.isValid():
            self._last_frame = frame
            if self.frozen_mode():
                self.overlay.update()

    def last_frame_image(self):
        if self._last_frame is not None and self._last_frame.isValid():
            img = self._last_frame.toImage()
            if not img.isNull():
                return img
        return None

    def frozen_mode(self) -> bool:
        """Editing blurs on a paused frame: the live video surface is a
        native Wayland subsurface that sits above ALL widget painting, so
        while decorating we hide it and paint the frame ourselves."""
        return (self.player.playbackState() != QMediaPlayer.PlayingState
                and (self.overlay.active or bool(self.redactions)
                     or self.trim is not None)
                and self._last_frame is not None)

    def _sync_video_surface(self) -> None:
        self.stack.video.setVisible(not self.frozen_mode())
        self.overlay.update()

    def _state_changed(self, state) -> None:
        playing = state == QMediaPlayer.PlayingState
        self.play_btn.setIcon(QIcon.fromTheme(
            "media-playback-pause" if playing else "media-playback-start"))
        self._sync_video_surface()

    def _position_changed(self, pos: int) -> None:
        if not self.slider.isSliderDown():
            self.slider.setValue(pos)
        self.time_label.setText(
            f"{_fmt_ms(pos)} / {_fmt_ms(self.player.duration())}")
        if self.redactions or self.trim is not None:
            self.overlay.update()
            self.range_bar.update()

    def _duration_changed(self, dur: int) -> None:
        self.slider.setRange(0, dur)

    # -- redaction ------------------------------------------------------------

    def _notify(self, msg: str, ms: int = 4000) -> None:
        """Status both to the main window bar and visibly in this pane."""
        self.status.emit(msg, ms)
        self.hint.setText(msg)
        self.hint.show()
        if ms:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(
                ms, lambda: self.hint.hide()
                if self.hint.text() == msg else None)

    def active_redaction(self) -> Redaction | None:
        if self.trim is not None:
            return self.trim
        if 0 <= self.active_idx < len(self.redactions):
            return self.redactions[self.active_idx]
        return None

    def set_active(self, idx: int) -> None:
        if self.trim is not None:
            return
        if idx != self.active_idx and 0 <= idx < len(self.redactions):
            self.active_idx = idx
            self._rebuild_rows()
            self.range_bar.update()

    def spans(self) -> list[Redaction]:
        """What the timeline bar edits: the trim span while trimming,
        otherwise the blur redactions."""
        return [self.trim] if self.trim is not None else self.redactions

    def _blur_mode(self, on: bool) -> None:
        if on:
            self.trim_btn.setChecked(False)
            self.player.pause()
            self.hint.setText(
                "Drag a box over the part of the video to blur")
            self.hint.show()
        else:
            self.hint.hide()
        self.overlay.set_active(on)
        self._sync_video_surface()

    def _trim_mode(self, on: bool) -> None:
        if on and self.redactions:
            self.trim_btn.setChecked(False)
            self._notify("Apply or remove the pending blurs before trimming")
            return
        if on:
            self.player.pause()
            dur = self.player.duration() / 1000.0
            self.trim = Redaction(QRect(), 0.0, round(max(dur, 0.1), 2))
            self._notify("Drag the timeline edges to choose the section to "
                         "keep, then Save trim — the video scrubs as you "
                         "drag", 0)
        else:
            self.trim = None
            self.hint.hide()
        self.trim_accurate.setVisible(on)
        self.trim_apply_btn.setVisible(on)
        self.blur_btn.setEnabled(not on and ffmpegutil.have_ffmpeg())
        self.range_bar.setVisible(on or bool(self.redactions))
        self.range_bar.update()
        self._sync_video_surface()

    def _region_drawn(self, video_rect: QRect) -> None:
        start = self.player.position() / 1000.0
        duration = self.player.duration() / 1000.0 or start + 5
        self.redactions.append(
            Redaction(video_rect, round(start, 2),
                      round(min(duration, start + 5), 2)))
        self.active_idx = len(self.redactions) - 1
        self.blur_btn.setChecked(False)
        self.hint.setText(
            "Now drag across the timeline bar to set when this blur is "
            "active — the video scrubs as you drag")
        self.hint.show()
        self._rebuild_rows()
        self.refresh_overlays()

    def _clear_redactions(self) -> None:
        self.redactions.clear()
        self.active_idx = -1
        self.blur_btn.setChecked(False)
        self.trim_btn.setChecked(False)
        self.hint.hide()
        self._rebuild_rows()
        self.refresh_overlays()

    def refresh_overlays(self) -> None:
        self._sync_video_surface()
        self.range_bar.setVisible(bool(self.redactions) or self.trim is not None)
        self.range_bar.update()

    # -- rows -------------------------------------------------------------------

    def _rebuild_rows(self) -> None:
        while self.redact_rows.count():
            item = self.redact_rows.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._row_spins = []
        for i, red in enumerate(self.redactions):
            self.redact_rows.addWidget(self._make_row(i, red))
        has = bool(self.redactions)
        self.redact_box.setVisible(has)
        self.apply_btn.setVisible(has)
        self.apply_btn.setText(f"Apply blurs ({len(self.redactions)})")
        if not has:
            self.range_bar.hide()

    def sync_active_row(self) -> None:
        if self.trim is not None:
            return
        red = self.active_redaction()
        if red is None or self.active_idx >= len(self._row_spins):
            return
        start_spin, end_spin = self._row_spins[self.active_idx]
        for spin, val in ((start_spin, red.start), (end_spin, red.end)):
            spin.blockSignals(True)
            spin.setValue(val)
            spin.blockSignals(False)

    def _make_row(self, i: int, red: Redaction) -> QWidget:
        row = QWidget(self.redact_box)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)

        pick = QToolButton(row)
        pick.setText(str(i + 1))
        color = PALETTE[i % len(PALETTE)]
        weight = "bold" if i == self.active_idx else "normal"
        pick.setStyleSheet(
            f"QToolButton {{ color: {color}; font-weight: {weight}; }}")
        pick.setToolTip("Make this the blur the timeline bar edits")

        def activate():
            self.active_idx = i
            self._rebuild_rows()
            self.range_bar.update()

        pick.clicked.connect(activate)
        lay.addWidget(pick)

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
        self._row_spins.append((start_spin, end_spin))

        def changed(attr, v, r=red):
            setattr(r, attr, v)
            self.refresh_overlays()

        start_spin.valueChanged.connect(lambda v: changed("start", v))
        end_spin.valueChanged.connect(lambda v: changed("end", v))

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
            self.active_idx = min(self.active_idx,
                                  len(self.redactions) - 1)
            self._rebuild_rows()
            self.refresh_overlays()

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

    # -- rendering ----------------------------------------------------------------

    def _render_temp(self, final_path: str) -> str:
        """Render target in a hidden dir the gallery never lists, so a
        half-written file can't show up (and get played) mid-render."""
        tmp_dir = os.path.join(self.settings.library_dir, ".rendering")
        os.makedirs(tmp_dir, exist_ok=True)
        return os.path.join(tmp_dir, os.path.basename(final_path))

    def _set_rendering(self, on: bool) -> None:
        """Visually leave blur-editing mode while ffmpeg runs."""
        self.blur_btn.setChecked(False)
        self.blur_btn.setEnabled(not on)
        self.apply_btn.setEnabled(not on)
        self.redact_box.setVisible(not on and bool(self.redactions))
        self.range_bar.setVisible(not on and bool(self.redactions))
        if on:
            self.hint.setText("Rendering — the result will appear in the "
                              "gallery when done. You can keep working.")
            self.hint.show()
        else:
            self.hint.hide()
        self.overlay.update()

    def _apply_blurs(self) -> None:
        if not self.path or not self.redactions or self._blur_proc is not None:
            return
        bad = [i + 1 for i, r in enumerate(self.redactions)
               if r.end <= r.start]
        if bad:
            self.status.emit(f"Blur {bad[0]}: end must be after start", 4000)
            return
        from .capture import unique_path
        sink = self.player.videoSink()
        vs = sink.videoSize() if sink else None
        graph, out_label = build_blur_filter(
            self.redactions,
            video_w=vs.width() if vs else 0,
            video_h=vs.height() if vs else 0)
        base, ext = os.path.splitext(os.path.basename(self.path))
        # H.264 can't live in a WebM container (Spectacle records .webm) —
        # render to mp4 unless the source is already mp4-family, and
        # transcode audio when the container changes.
        if ext.lower() in (".mp4", ".m4v", ".mov"):
            out_ext, audio_opts = ext, ["-c:a", "copy"]
        else:
            out_ext, audio_opts = ".mp4", ["-c:a", "aac", "-b:a", "160k"]
        out = unique_path(self.settings.library_dir,
                          f"{base}-redacted{out_ext}")
        tmp = self._render_temp(out)
        enc = pick_encoder()
        enc_opts = (["-crf", "20", "-preset", "veryfast"]
                    if enc == "libx264" else ["-q:v", "4"])
        enc_opts += ["-movflags", "+faststart"]  # instant seeking
        args = ["-y", "-i", self.path, "-filter_complex", graph,
                "-map", f"[{out_label}]", "-map", "0:a?", *audio_opts,
                "-c:v", enc, *enc_opts, tmp]
        self._blur_proc = QProcess(self)
        self._blur_proc.finished.connect(
            lambda code, _st: self._blur_done(code, tmp, out))
        self.apply_btn.setText("Rendering…")
        self._notify("Rendering blurred video…", 0)
        self._set_rendering(True)
        self._blur_proc.start(ffmpegutil.ffmpeg_path(), args)

    def _blur_done(self, code: int, tmp: str, out: str) -> None:
        proc, self._blur_proc = self._blur_proc, None
        if proc is not None:
            err = bytes(proc.readAllStandardError()).decode(errors="replace")
            proc.deleteLater()
        else:
            err = ""
        self.apply_btn.setText(f"Apply blurs ({len(self.redactions)})")
        if code == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            shutil.move(tmp, out)
            self._set_rendering(False)
            self._clear_redactions()
            self._notify(f"Saved {os.path.basename(out)}")
            self.file_ready.emit(out)
        else:
            self._set_rendering(False)
            self._rebuild_rows()
            self.refresh_overlays()
            tail = err.strip().splitlines()[-1] if err.strip() else "unknown"
            self._notify(f"Blur render failed: {tail[:160]}", 10000)
            if os.path.exists(tmp):
                os.unlink(tmp)

    # -- gif conversion ------------------------------------------------------

    def _convert_gif(self) -> None:
        if not self.path or self._gif_proc is not None:
            return
        from .capture import unique_path
        base = os.path.splitext(os.path.basename(self.path))[0]
        out = unique_path(self.settings.library_dir, f"{base}.gif")
        tmp = self._render_temp(out)
        vf = ("fps=12,scale='min(720,iw)':-1:flags=lanczos,"
              "split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse")
        self._gif_proc = QProcess(self)
        self._gif_proc.finished.connect(
            lambda code, _st: self._gif_done(code, tmp, out))
        self.gif_btn.setEnabled(False)
        self.gif_btn.setText("Converting…")
        self.status.emit("Converting to GIF…", 0)
        self._gif_proc.start(ffmpegutil.ffmpeg_path(),
                             ["-y", "-i", self.path, "-vf", vf, tmp])

    def _gif_done(self, code: int, tmp: str, out: str) -> None:
        proc, self._gif_proc = self._gif_proc, None
        if proc is not None:
            proc.deleteLater()
        self.gif_btn.setEnabled(True)
        self.gif_btn.setText("Convert to GIF")
        if code == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            shutil.move(tmp, out)
            self._notify(f"GIF saved: {os.path.basename(out)}")
            self.file_ready.emit(out)
        else:
            self._notify("GIF conversion failed", 6000)
            if os.path.exists(tmp):
                os.unlink(tmp)

    # -- trim ----------------------------------------------------------------

    def _apply_trim(self) -> None:
        if not self.path or self.trim is None or self._trim_proc is not None:
            return
        if self.trim.end <= self.trim.start:
            self.status.emit("Trim: end must be after start", 4000)
            return
        from .capture import unique_path
        reencode = self.trim_accurate.isChecked()
        out = unique_path(
            self.settings.library_dir,
            trim_output_name(os.path.basename(self.path), reencode))
        tmp = self._render_temp(out)
        enc = pick_encoder() if reencode else "libx264"
        args = build_trim_args(self.path, self.trim.start, self.trim.end,
                               tmp, reencode, encoder=enc)
        self._trim_proc = QProcess(self)
        self._trim_proc.finished.connect(
            lambda code, _st: self._trim_done(code, tmp, out))
        self.trim_apply_btn.setEnabled(False)
        self.trim_apply_btn.setText("Trimming…")
        self._notify("Trimming — the result will appear in the gallery "
                     "when done", 0)
        self._trim_proc.start(ffmpegutil.ffmpeg_path(), args)

    def _trim_done(self, code: int, tmp: str, out: str) -> None:
        proc, self._trim_proc = self._trim_proc, None
        if proc is not None:
            err = bytes(proc.readAllStandardError()).decode(errors="replace")
            proc.deleteLater()
        else:
            err = ""
        self.trim_apply_btn.setEnabled(True)
        self.trim_apply_btn.setText("Save trim")
        if code == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            shutil.move(tmp, out)
            self.trim_btn.setChecked(False)  # exits trim mode
            self._notify(f"Saved {os.path.basename(out)}")
            self.file_ready.emit(out)
        else:
            tail = err.strip().splitlines()[-1] if err.strip() else "unknown"
            self._notify(f"Trim failed: {tail[:160]}", 10000)
            if os.path.exists(tmp):
                os.unlink(tmp)

    # -- frame grab ----------------------------------------------------------

    def _save_frame(self) -> None:
        if not self.path or self._frame_proc is not None:
            return
        from .capture import unique_path
        self.player.pause()
        pos = self.player.position() / 1000.0
        out = unique_path(self.settings.library_dir,
                          frame_output_name(os.path.basename(self.path)))
        tmp = self._render_temp(out)
        self._frame_proc = QProcess(self)
        self._frame_proc.finished.connect(
            lambda code, _st: self._frame_done(code, tmp, out))
        self.frame_btn.setEnabled(False)
        self._notify("Saving frame…", 0)
        self._frame_proc.start(ffmpegutil.ffmpeg_path(),
                               build_frame_grab_args(self.path, pos, tmp))

    def _frame_done(self, code: int, tmp: str, out: str) -> None:
        proc, self._frame_proc = self._frame_proc, None
        if proc is not None:
            err = bytes(proc.readAllStandardError()).decode(errors="replace")
            proc.deleteLater()
        else:
            err = ""
        self.frame_btn.setEnabled(True)
        if code == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            shutil.move(tmp, out)
            self._notify(f"Saved {os.path.basename(out)}")
            self.file_ready.emit(out)
        else:
            tail = err.strip().splitlines()[-1] if err.strip() else "unknown"
            self._notify(f"Frame grab failed: {tail[:160]}", 8000)
            if os.path.exists(tmp):
                os.unlink(tmp)
