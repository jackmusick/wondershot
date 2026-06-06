"""In-app video playback with range-blur redaction and GIF conversion.

The video renders inside a QGraphicsScene (QGraphicsVideoItem), so blur
regions are ordinary graphics items drawn in true video-pixel coordinates —
exactly like annotations in the image editor, and immune to the native-
surface overlay problems QVideoWidget has on Wayland.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QProcess, QRect, QRectF, Qt, QUrl, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPen
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QGraphicsVideoItem
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
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


class VideoCanvas(QGraphicsView):
    """Graphics view hosting the video item; draws blur boxes in blur mode."""

    region_drawn = Signal(QRect)  # video pixel coords

    def __init__(self, pane: "VideoPane"):
        self.scene_ = QGraphicsScene()
        super().__init__(self.scene_)
        self.pane = pane
        self.blur_mode = False
        self._origin: QPointF | None = None
        self._band: QGraphicsRectItem | None = None
        self.setBackgroundBrush(QColor(26, 26, 29))
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setRenderHint(QPainter.Antialiasing)
        self.setFrameShape(QGraphicsView.NoFrame)

    def set_blur_mode(self, on: bool) -> None:
        self.blur_mode = on
        self.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)

    def fit(self) -> None:
        rect = self.scene_.sceneRect()
        if not rect.isEmpty():
            self.fitInView(rect, Qt.KeepAspectRatio)

    def resizeEvent(self, ev):  # noqa: N802
        super().resizeEvent(ev)
        self.fit()

    # -- drawing a region ----------------------------------------------------

    def mousePressEvent(self, ev):  # noqa: N802
        if not self.blur_mode or ev.button() != Qt.LeftButton:
            super().mousePressEvent(ev)
            return
        self._origin = self.mapToScene(ev.position().toPoint())
        self._band = QGraphicsRectItem(QRectF(self._origin, self._origin))
        pen = QPen(QColor("#3daee9"), 2, Qt.DashLine)
        pen.setCosmetic(True)
        self._band.setPen(pen)
        self._band.setBrush(QColor(61, 174, 233, 60))
        self._band.setZValue(10000)
        self.scene_.addItem(self._band)

    def mouseMoveEvent(self, ev):  # noqa: N802
        if self._band is None:
            super().mouseMoveEvent(ev)
            return
        pos = self.mapToScene(ev.position().toPoint())
        self._band.setRect(QRectF(self._origin, pos).normalized())

    def mouseReleaseEvent(self, ev):  # noqa: N802
        if self._band is None:
            super().mouseReleaseEvent(ev)
            return
        band, self._band = self._band, None
        rect = band.rect().toRect()
        self.scene_.removeItem(band)
        self._origin = None
        # scene coords ARE video pixel coords (video item sized to native)
        bounds = self.scene_.sceneRect().toRect()
        rect = rect.intersected(bounds)
        if rect.width() > 6 and rect.height() > 6:
            self.region_drawn.emit(rect)


class RangeBar(QWidget):
    """Timeline strip showing each blur's span as a colored band.

    Interactions (video scrubs live during every drag):
    - drag a band's edge: adjust its start/end independently
    - drag inside a band: move the whole span
    - drag on empty bar: define the active blur's span from scratch
    """

    PALETTE = ["#e05555", "#e0a030", "#46a3e0", "#9a59d0", "#43b97f"]
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
        order = []
        if 0 <= self.pane.active_idx < len(self.pane.redactions):
            order.append(self.pane.active_idx)
        order += [i for i in range(len(self.pane.redactions))
                  if i not in order]
        for i in order:
            red = self.pane.redactions[i]
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
            red = self.pane.redactions[hit[1]]
            self._scrub({"start": red.start, "end": red.end,
                         "move": red.start}[hit[0]])
        elif self.pane.redactions:
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
        for i, red in enumerate(self.pane.redactions):
            x1 = red.start * 1000 / dur * w
            x2 = red.end * 1000 / dur * w
            color = QColor(self.PALETTE[i % len(self.PALETTE)])
            active = i == self.pane.active_idx
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

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.path: str | None = None
        self._gif_proc: QProcess | None = None
        self._blur_proc: QProcess | None = None
        self.redactions: list[Redaction] = []
        self.active_idx = -1
        self._row_spins: list[tuple[QDoubleSpinBox, QDoubleSpinBox]] = []
        self._overlay_items: list = []
        self._pause_on_load = False

        self.player = QMediaPlayer(self)
        self.audio = QAudioOutput(self)
        self.player.setAudioOutput(self.audio)
        self.video_item = QGraphicsVideoItem()
        self.player.setVideoOutput(self.video_item)
        self.canvas = VideoCanvas(self)
        self.canvas.scene_.addItem(self.video_item)
        self.canvas.region_drawn.connect(self._region_drawn)
        self.video_item.nativeSizeChanged.connect(self._native_size_changed)

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
        self.blur_btn.setEnabled(shutil.which("ffmpeg") is not None)

        self.apply_btn = QPushButton("Apply blurs", self)
        self.apply_btn.setIcon(QIcon.fromTheme("dialog-ok-apply"))
        self.apply_btn.clicked.connect(self._apply_blurs)
        self.apply_btn.hide()

        self.gif_btn = QPushButton("Convert to GIF", self)
        self.gif_btn.setIcon(QIcon.fromTheme("video-x-generic"))
        self.gif_btn.clicked.connect(self._convert_gif)
        self.gif_btn.setEnabled(shutil.which("ffmpeg") is not None)

        controls = QHBoxLayout()
        controls.setContentsMargins(8, 4, 8, 0)
        controls.addWidget(self.play_btn)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.time_label)
        controls.addSpacing(12)
        controls.addWidget(self.blur_btn)
        controls.addWidget(self.apply_btn)
        controls.addWidget(self.gif_btn)

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
        layout.addWidget(self.canvas, 1)
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

    def _native_size_changed(self, size) -> None:
        if size.isEmpty():
            return
        self.video_item.setSize(size)
        self.canvas.scene_.setSceneRect(QRectF(QPointF(0, 0), size))
        self.canvas.fit()

    def _media_status(self, status) -> None:
        if self._pause_on_load and status == QMediaPlayer.BufferedMedia:
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
        self._update_overlay_visibility()
        if self.redactions:
            self.range_bar.update()

    def _duration_changed(self, dur: int) -> None:
        self.slider.setRange(0, dur)

    # -- redaction ------------------------------------------------------------

    def active_redaction(self) -> Redaction | None:
        if 0 <= self.active_idx < len(self.redactions):
            return self.redactions[self.active_idx]
        return None

    def set_active(self, idx: int) -> None:
        if idx != self.active_idx and 0 <= idx < len(self.redactions):
            self.active_idx = idx
            self._rebuild_rows()
            self.range_bar.update()

    def _blur_mode(self, on: bool) -> None:
        if on:
            self.player.pause()
            self.hint.setText(
                "Drag a box over the part of the video to blur")
            self.hint.show()
        else:
            self.hint.hide()
        self.canvas.set_blur_mode(on)

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
        self.hint.hide()
        self._rebuild_rows()
        self.refresh_overlays()

    # -- overlays ----------------------------------------------------------------

    def refresh_overlays(self) -> None:
        for item in self._overlay_items:
            if item.scene() is not None:
                self.canvas.scene_.removeItem(item)
        self._overlay_items = []
        for i, red in enumerate(self.redactions):
            color = QColor(RangeBar.PALETTE[i % len(RangeBar.PALETTE)])
            rect_item = QGraphicsRectItem(QRectF(red.rect))
            pen = QPen(color, 2, Qt.DashLine)
            pen.setCosmetic(True)
            rect_item.setPen(pen)
            frost = QColor(255, 255, 255, 70)
            rect_item.setBrush(QBrush(frost))
            rect_item.setZValue(5000)
            label = QGraphicsSimpleTextItem(str(i + 1), rect_item)
            label.setBrush(QBrush(QColor("white")))
            label.setPos(red.rect.x() + 6, red.rect.y() + 4)
            f = label.font()
            f.setBold(True)
            f.setPointSize(14)
            label.setFont(f)
            self.canvas.scene_.addItem(rect_item)
            self._overlay_items.append(rect_item)
        self._update_overlay_visibility()
        self.range_bar.setVisible(bool(self.redactions))
        self.range_bar.update()

    def _update_overlay_visibility(self) -> None:
        """A blur's frost is only shown while the playhead is inside its
        span — scrubbing previews exactly what gets blurred and when."""
        t = self.player.position() / 1000.0
        for item, red in zip(self._overlay_items, self.redactions):
            item.setVisible(red.start <= t <= red.end)

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
        color = RangeBar.PALETTE[i % len(RangeBar.PALETTE)]
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
        for item in self._overlay_items:
            item.setVisible(False)
        if on:
            self.hint.setText("Rendering — the result will appear in the "
                              "gallery when done. You can keep working.")
            self.hint.show()
        else:
            self.hint.hide()
            self._update_overlay_visibility()

    def _apply_blurs(self) -> None:
        if not self.path or not self.redactions or self._blur_proc is not None:
            return
        bad = [i + 1 for i, r in enumerate(self.redactions)
               if r.end <= r.start]
        if bad:
            self.status.emit(f"Blur {bad[0]}: end must be after start", 4000)
            return
        from .capture import unique_path
        native = self.video_item.nativeSize()
        graph, out_label = build_blur_filter(
            self.redactions,
            video_w=int(native.width()), video_h=int(native.height()))
        base, ext = os.path.splitext(os.path.basename(self.path))
        out = unique_path(self.settings.library_dir, f"{base}-redacted{ext}")
        tmp = self._render_temp(out)
        enc = pick_encoder()
        enc_opts = (["-crf", "20", "-preset", "veryfast"]
                    if enc == "libx264" else ["-q:v", "4"])
        if ext.lower() in (".mp4", ".m4v", ".mov"):
            enc_opts += ["-movflags", "+faststart"]  # instant seeking
        args = ["-y", "-i", self.path, "-filter_complex", graph,
                "-map", f"[{out_label}]", "-map", "0:a?", "-c:a", "copy",
                "-c:v", enc, *enc_opts, tmp]
        self._blur_proc = QProcess(self)
        self._blur_proc.finished.connect(
            lambda code, _st: self._blur_done(code, tmp, out))
        self.apply_btn.setText("Rendering…")
        self.status.emit("Rendering blurred video…", 0)
        self._set_rendering(True)
        self._blur_proc.start("ffmpeg", args)

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
            self.status.emit(f"Saved {os.path.basename(out)}", 4000)
            self.file_ready.emit(out)
        else:
            self._set_rendering(False)
            self._rebuild_rows()
            self.refresh_overlays()
            tail = err.strip().splitlines()[-1] if err.strip() else "unknown"
            self.status.emit(f"Blur render failed: {tail[:120]}", 6000)
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
        self._gif_proc.start("ffmpeg", ["-y", "-i", self.path,
                                        "-vf", vf, tmp])

    def _gif_done(self, code: int, tmp: str, out: str) -> None:
        proc, self._gif_proc = self._gif_proc, None
        if proc is not None:
            proc.deleteLater()
        self.gif_btn.setEnabled(True)
        self.gif_btn.setText("Convert to GIF")
        if code == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
            shutil.move(tmp, out)
            self.status.emit(f"GIF saved: {os.path.basename(out)}", 4000)
            self.file_ready.emit(out)
        else:
            self.status.emit("GIF conversion failed", 4000)
            if os.path.exists(tmp):
                os.unlink(tmp)
