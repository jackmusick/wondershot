import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


# -- probe ---------------------------------------------------------------

def test_is_kde_env():
    from wondershot.kwin import is_kde
    assert is_kde({"XDG_CURRENT_DESKTOP": "KDE"})
    assert is_kde({"XDG_CURRENT_DESKTOP": "wayland:KDE"})
    assert not is_kde({"XDG_CURRENT_DESKTOP": "GNOME"})
    assert not is_kde({})


# -- script text -----------------------------------------------------------

def test_script_embeds_callback_coordinates():
    from wondershot.kwin import build_geometry_script
    js = build_geometry_script(":1.42", "/wondershot/kwin",
                               "com.wondershot.kwin", "geometry")
    assert '":1.42"' in js
    assert '"/wondershot/kwin"' in js
    assert '"com.wondershot.kwin"' in js
    assert '"geometry"' in js
    # KWin 6 name with KWin 5 fallback — defensive across versions
    assert "workspace.activeWindow || workspace.activeClient" in js
    assert "frameGeometry" in js
    # geometry travels as ONE STRING — never trust KWin number marshalling
    assert '"," + g.y' in js


# -- reply parsing -----------------------------------------------------------

def test_parse_geometry_reply_good():
    from wondershot.kwin import parse_geometry_reply
    assert parse_geometry_reply("100,200,800,600") == (100, 200, 800, 600)
    assert parse_geometry_reply("-50,0,640,480") == (-50, 0, 640, 480)  # left monitor
    assert parse_geometry_reply("10.0,20.0,30.5,40.5") == (10, 20, 30, 40)


def test_parse_geometry_reply_bad():
    from wondershot.kwin import parse_geometry_reply
    assert parse_geometry_reply("") is None            # no active window
    assert parse_geometry_reply("1,2,3") is None       # wrong arity
    assert parse_geometry_reply("a,b,c,d") is None     # garbage
    assert parse_geometry_reply("0,0,0,600") is None   # degenerate width
    assert parse_geometry_reply("0,0,800,-1") is None  # degenerate height


# -- D-Bus call builders -------------------------------------------------------

def test_call_builders_are_plain_strings_and_ints():
    from wondershot.kwin import (build_load_call, build_run_call,
                                 build_stop_call, build_unload_call)
    svc, path, iface, method, args = build_load_call("/tmp/x.js", "wondershot-active-window")
    assert (svc, path, iface, method) == (
        "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "loadScript")
    assert args == ["/tmp/x.js", "wondershot-active-window"]
    svc, path, iface, method, args = build_run_call(7)
    assert (path, iface, method, args) == (
        "/Scripting/Script7", "org.kde.kwin.Script", "run", [])
    svc, path, iface, method, args = build_stop_call(7)
    assert (path, method) == ("/Scripting/Script7", "stop")
    svc, path, iface, method, args = build_unload_call("wondershot-active-window")
    assert (path, method, args) == (
        "/Scripting", "unloadScript", ["wondershot-active-window"])
    # compositor-safety: nothing but str/int ever goes over the wire —
    # check the args of ALL four builders, not just the last one
    for call in (build_load_call("/tmp/x.js", "p"), build_run_call(7),
                 build_stop_call(7), build_unload_call("p")):
        assert all(isinstance(a, (str, int)) for a in call[4])


# -- crop math -----------------------------------------------------------------

def test_map_global_rect_identity():
    from wondershot.kwin import map_global_rect
    virtual = QRect(0, 0, 1920, 1080)
    r = map_global_rect(QRect(100, 50, 640, 480), virtual, 1920, 1080)
    assert r == QRect(100, 50, 640, 480)


def test_map_global_rect_hidpi_scale():
    from wondershot.kwin import map_global_rect
    # 2x scale: image pixels are double the logical/global coordinates
    virtual = QRect(0, 0, 1920, 1080)
    r = map_global_rect(QRect(100, 50, 640, 480), virtual, 3840, 2160)
    assert r == QRect(200, 100, 1280, 960)


def test_map_global_rect_second_monitor_offset():
    from wondershot.kwin import map_global_rect
    # two 1920x1080 monitors side by side; window on the right one
    virtual = QRect(0, 0, 3840, 1080)
    r = map_global_rect(QRect(2000, 100, 800, 600), virtual, 3840, 1080)
    assert r == QRect(2000, 100, 800, 600)
    # left monitor at negative x (KDE allows it)
    virtual2 = QRect(-1920, 0, 3840, 1080)
    r2 = map_global_rect(QRect(-1820, 100, 800, 600), virtual2, 3840, 1080)
    assert r2 == QRect(100, 100, 800, 600)


def test_map_global_rect_clamps_to_image():
    from wondershot.kwin import map_global_rect
    virtual = QRect(0, 0, 1920, 1080)
    # window hangs off the bottom-right edge
    r = map_global_rect(QRect(1800, 1000, 400, 300), virtual, 1920, 1080)
    assert r == QRect(1800, 1000, 120, 80)


def test_map_global_rect_degenerate_inputs():
    from wondershot.kwin import map_global_rect
    assert map_global_rect(QRect(0, 0, 10, 10), QRect(), 100, 100).isEmpty()
    assert map_global_rect(QRect(0, 0, 10, 10), QRect(0, 0, 100, 100), 0, 0).isEmpty()


def test_crop_file_to_global_rect(qapp, tmp_path):
    from wondershot.kwin import crop_file_to_global_rect
    img = QImage(200, 100, QImage.Format_RGB32)
    img.fill(Qt.black)
    for x in range(50, 150):
        for y in range(20, 80):
            img.setPixelColor(x, y, Qt.white)
    p = str(tmp_path / "full.png")
    img.save(p)
    ok = crop_file_to_global_rect(p, QRect(50, 20, 100, 60),
                                  QRect(0, 0, 200, 100))
    assert ok
    out = QImage(p)
    assert out.size().width() == 100 and out.size().height() == 60
    assert out.pixelColor(0, 0) == Qt.white


def test_crop_file_failure_paths(qapp, tmp_path):
    from wondershot.kwin import crop_file_to_global_rect
    assert not crop_file_to_global_rect(str(tmp_path / "nope.png"),
                                        QRect(0, 0, 10, 10),
                                        QRect(0, 0, 100, 100))
    img = QImage(50, 50, QImage.Format_RGB32)
    img.fill(Qt.black)
    p = str(tmp_path / "x.png")
    img.save(p)
    # rect entirely outside the virtual area → empty crop → False, file intact
    assert not crop_file_to_global_rect(p, QRect(500, 500, 10, 10),
                                        QRect(0, 0, 50, 50))
    assert QImage(p).width() == 50


# -- ActiveWindowQuery against a fake transport -------------------------------

class FakeTransport:
    """Records calls; scriptable replies. service_name mimics a unique bus name."""

    def __init__(self, load_reply=5, run_ok=True, register_ok=True):
        self.calls = []
        self.registered = None
        self.unregistered = False
        self.load_reply = load_reply
        self.run_ok = run_ok
        self.register_ok = register_ok

    def service_name(self):
        return ":1.99"

    def register(self, path, obj):
        self.registered = (path, obj)
        return self.register_ok

    def unregister(self, path):
        self.unregistered = True

    def call(self, service, path, iface, method, args):
        self.calls.append((service, path, iface, method, list(args)))
        if method == "loadScript":
            return self.load_reply
        if method == "run":
            return True if self.run_ok else None
        return True  # stop / unloadScript


def test_query_happy_path(qapp):
    from wondershot.kwin import ActiveWindowQuery, PLUGIN_NAME
    t = FakeTransport()
    q = ActiveWindowQuery(transport=t, timeout_ms=5000)
    got, fails = [], []
    q.finished.connect(lambda x, y, w, h: got.append((x, y, w, h)))
    q.failed.connect(fails.append)
    q.start()
    # loadScript called with [tmpfile, plugin]; run on the returned id
    load = [c for c in t.calls if c[3] == "loadScript"]
    assert load and load[0][4][1] == PLUGIN_NAME
    assert load[0][4][0].endswith(".js")
    assert any(c[1] == "/Scripting/Script5" and c[3] == "run"
               for c in t.calls)
    # KWin's script calls back into our registered slot
    q.geometry("100,200,800,600")
    assert got == [(100, 200, 800, 600)]
    assert not fails
    # cleanup happened: stop + unloadScript + unregister + temp file gone
    assert any(c[3] == "stop" for c in t.calls)
    assert any(c[3] == "unloadScript" for c in t.calls)
    assert t.unregistered
    assert not q._timer.isActive()


def test_query_no_active_window(qapp):
    from wondershot.kwin import ActiveWindowQuery
    t = FakeTransport()
    q = ActiveWindowQuery(transport=t, timeout_ms=5000)
    fails = []
    q.failed.connect(fails.append)
    q.start()
    q.geometry("")  # script found no window
    assert fails and "active window" in fails[0]


def test_query_load_failure(qapp):
    from wondershot.kwin import ActiveWindowQuery
    t = FakeTransport(load_reply=None)
    q = ActiveWindowQuery(transport=t, timeout_ms=5000)
    fails = []
    q.failed.connect(fails.append)
    q.start()
    assert fails  # immediate failure, no hang
    assert t.unregistered  # cleanup still ran


def test_query_register_failure(qapp):
    from wondershot.kwin import ActiveWindowQuery
    t = FakeTransport(register_ok=False)
    q = ActiveWindowQuery(transport=t, timeout_ms=5000)
    fails = []
    q.failed.connect(fails.append)
    q.start()
    assert fails
    # never touched KWin if we couldn't even receive the answer
    assert not any(c[3] == "loadScript" for c in t.calls)


def test_query_timeout(qapp):
    from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
    from wondershot.kwin import ActiveWindowQuery
    t = FakeTransport()
    q = ActiveWindowQuery(transport=t, timeout_ms=30)
    fails = []
    q.failed.connect(fails.append)
    q.start()
    loop = QEventLoop()
    q.failed.connect(lambda *_: loop.quit())
    QTimer.singleShot(2000, loop.quit)  # safety
    loop.exec()
    assert fails and "timeout" in fails[0].lower()
    assert any(c[3] == "unloadScript" for c in t.calls)  # cleaned up


def test_late_reply_after_failure_is_ignored(qapp):
    from wondershot.kwin import ActiveWindowQuery
    t = FakeTransport(load_reply=None)
    q = ActiveWindowQuery(transport=t, timeout_ms=5000)
    got, fails = [], []
    q.finished.connect(lambda *a: got.append(a))
    q.failed.connect(fails.append)
    q.start()           # fails at loadScript
    q.geometry("1,2,3,4")  # straggler — must not emit finished
    assert fails and not got
