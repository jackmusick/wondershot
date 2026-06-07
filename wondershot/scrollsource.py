"""Linux FrameSource: portal ScreenCast -> PipeWire -> Gst appsink.

WS-D SPIKE QUALITY. Reuses record.py's portal dance by subclassing
ScreenRecorder and overriding _launch_gst: instead of spawning a
gst-launch subprocess that encodes mp4, we build an in-process
pipeline ending in an appsink and emit each sample as a QImage.

The stitcher side (stitch.py) never sees Gst/PipeWire types — frames
cross this boundary as QImages only (WS-E portability seam).

Threading note: appsink's new-sample callback fires on a GStreamer
streaming thread, and the QImage is deep-copied before emitting.
BUT: connecting the signal to a plain-Python callable (ScrollStitcher
is not a QObject) gives a DIRECT connection — add_frame runs on the
streaming thread, not the Qt main loop. Acceptable for the spike
because the stitcher touches no UI and stop() drives the pipeline to
NULL (callbacks cease) before result() is read on the main thread.
Productization (WS-E) must put the stitcher behind a QObject so
delivery is queued.
"""

from __future__ import annotations

import signal as _signal
import sys

from PySide6.QtCore import QTimer, Signal
from PySide6.QtGui import QImage

from .record import _HAVE_GIO, ScreenRecorder


def _gst():
    import gi
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst
    if not Gst.is_initialized():
        Gst.init(None)
    return Gst


class ScreenCastFrameSource(ScreenRecorder):
    """FrameSource over the existing portal ScreenCast dance.

    Inherits the whole CreateSession/SelectSources/Start/
    OpenPipeWireRemote flow (and the persisted restore token) from
    ScreenRecorder; only the pipeline endpoint differs.
    Duck-types stitch.FrameSource: start()/stop()/frame/started/failed.
    """

    frame = Signal(QImage)

    def __init__(self, settings, fps: int = 10, parent=None):
        super().__init__(settings, parent)
        self.fps = fps
        self._pipeline = None

    def available(self) -> bool:
        if not _HAVE_GIO:
            return False
        try:
            _gst()
            return True
        except (ImportError, ValueError):
            return False

    # ScreenRecorder.start() runs the portal dance, then calls this
    # with the PipeWire fd + node id.
    def _launch_gst(self, fd: int, node: int) -> None:
        Gst = _gst()
        # videorate: pipewiresrc emits PTS-less buffers near stream
        # start (ROADMAP landmine); also throttles stitch input.
        desc = (
            f"pipewiresrc fd={fd} path={node} do-timestamp=true ! "
            "queue ! videoconvert ! videorate ! "
            f"video/x-raw,format=BGRx,framerate={self.fps}/1 ! "
            "appsink name=sink emit-signals=true max-buffers=2 "
            "drop=true sync=false"
        )
        try:
            self._pipeline = Gst.parse_launch(desc)
        except Exception as e:  # GLib.Error from parse_launch
            self._fail(f"could not build appsink pipeline: {e}")
            return
        sink = self._pipeline.get_by_name("sink")
        sink.connect("new-sample", self._on_sample)
        self._pipeline.set_state(Gst.State.PLAYING)
        self._busy = False
        self.recording = True
        self.started.emit()

    def _on_sample(self, sink):
        Gst = _gst()
        sample = sink.emit("pull-sample")
        if sample is None:
            return Gst.FlowReturn.OK
        caps = sample.get_caps().get_structure(0)
        w = caps.get_value("width")
        h = caps.get_value("height")
        buf = sample.get_buffer()
        ok, info = buf.map(Gst.MapFlags.READ)
        if not ok:
            return Gst.FlowReturn.OK
        try:
            stride = info.size // h  # BGRx rows may be padded
            img = QImage(bytes(info.data), w, h, stride,
                         QImage.Format_RGB32).copy()
        finally:
            buf.unmap(info)
        self.frame.emit(img)
        return Gst.FlowReturn.OK

    def stop(self) -> None:
        if self._pipeline is not None:
            Gst = _gst()
            self._pipeline.set_state(Gst.State.NULL)
            self._pipeline = None
        self.recording = False
        self._cleanup()  # base class: closes fd + portal session


# -- CLI runner (wondershot --scroll-spike) --------------------------------

def run_scroll_spike(out_path: str | None = None) -> int:
    """Record the screen-cast while the user scrolls; write a stitched
    PNG on Ctrl+C. Spike harness, not shippable UI."""
    try:
        from .stitch import ScrollStitcher
    except ImportError:
        print("numpy missing — install the spike extra:\n"
              "  pip install -e '.[spike]'", file=sys.stderr)
        return 2

    from PySide6.QtGui import QGuiApplication
    from .settings import Settings
    from .capture import timestamp_name, unique_path

    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    app.setApplicationName("wondershot")
    app.setOrganizationName("wondershot")

    settings = Settings()
    out = out_path or unique_path(settings.library_dir,
                                  timestamp_name("ScrollCapture"))
    source = ScreenCastFrameSource(settings, fps=10)
    if not source.available():
        print("needs python3-gobject + GStreamer (Gst) bindings",
              file=sys.stderr)
        return 2
    stitcher = ScrollStitcher()
    # Direct connection (non-QObject slot): add_frame runs on the Gst
    # streaming thread — see module docstring for why that's OK here.
    source.frame.connect(stitcher.add_frame)
    source.failed.connect(lambda m: (print(f"FAILED: {m}",
                                           file=sys.stderr),
                                     app.exit(1)))
    source.started.connect(lambda: print(
        "Recording — pick the window in the portal dialog, scroll it "
        "top-to-bottom slowly, then press Ctrl+C here."))

    # Let Ctrl+C reach Python inside the Qt loop.
    _signal.signal(_signal.SIGINT, lambda *_: app.exit(0))
    pump = QTimer()
    pump.timeout.connect(lambda: None)
    pump.start(200)

    source.start()
    code = app.exec()
    source.stop()
    if code != 0:
        return code
    img = stitcher.result()
    if img.isNull():
        print("no frames captured — nothing to write", file=sys.stderr)
        return 1
    img.save(out, "PNG")
    print(f"stitched {stitcher.frames_used} frames "
          f"({stitcher.frames_dropped} dropped) -> {out} "
          f"({img.width()}x{img.height()})")
    return 0
