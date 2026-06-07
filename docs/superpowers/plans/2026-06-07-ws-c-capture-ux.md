# WS-C: Capture UX — Post-Capture Quick-Action Bar + Auto-Size-to-Window

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Two capture-UX features per the spec Addendum (`docs/superpowers/specs/2026-06-06-snagit-parity-design.md`, "Session 2: WS-C"). (1) A frameless always-on-top **quick-action bar** that appears after a capture lands: thumbnail + Edit / Copy / Save-as / Share / Trash / dismiss, acting on the just-captured file, with an auto-dismiss timeout setting (default 8 s) and Esc-to-dismiss. (2) **Auto-size-to-window**: a "Window" capture mode that grabs the active window without an interactive pick by querying its frame geometry via KWin scripting D-Bus, then fullscreen-capturing and cropping to that rect. KDE-only; the option is hidden when the feature probe fails.

**Architecture:** The bar is a `QuickActionBar(QWidget)` added to `wondershot/capture_window.py` (frameless `Qt.Tool | WindowStaysOnTopHint`, exactly the `bubble.py` precedent — Wayland windows cannot self-position, so placement uses a KWin window rule written via `kwriteconfig6`, never `move()`). The bar owns Copy and Save-as internally and emits `edit_requested` / `share_requested` / `trash_requested` signals that `app.py` wires to the existing flows: `gallery.open_editor`, `gallery.editor.share_path`, `gallery._trash_paths`. The KWin geometry query lives in a new `wondershot/kwin.py`: pure functions (script-text construction, reply parsing, crop math, D-Bus call-argument builders) plus an `ActiveWindowQuery(QObject)` whose D-Bus traffic goes through an injectable transport so tests fake the bus. `CaptureManager` (capture.py) gains `capture_active_window()` which chains query → fullscreen capture → crop-in-place, with both backends funneling through a new `_finish(path)` seam.

**Compositor-safety posture (READ FIRST):** KWin hosts the Wayland compositor. The ROADMAP "Platform landmines" section records that a malformed KGlobalAccel D-Bus call **aborted KWin 6.6.5** (see also `wondershot/hotkey.py`'s module docstring). Rules enforced by this plan: kwin.py only calls the documented `org.kde.kwin.Scripting` methods (`loadScript`, `unloadScript`, `run`, `stop`) with **plain string/int arguments** — never dicts/variants; geometry comes *back to us* as a single comma-joined **string** via `callDBus` from the injected JS (so we never depend on KWin's number marshalling); every call has a hard timeout; any failure makes the feature silently unavailable, never an error dialog, never a retry loop. Also note the QtDBus landmine: signal/slot connects need `SLOT("name(sig)")` — we avoid signal connects entirely here by having KWin call a registered object's slot.

**Tech Stack:** Python ≥3.10, PySide6 only (no new deps). Tests: pytest, headless (`QT_QPA_PLATFORM=offscreen`), fake transports/settings — no real D-Bus, no network, no compositor.

**Execution environment:** Work in a git worktree branched from `main` (e.g. `git worktree add ../grabbit-wt/ws-c -b ws-c main`). Venv recipe from the worktree root:

```bash
python -m venv .venv && .venv/bin/pip install -e . pytest
```

Plain venv suffices — the optional extras (`spike`, `ai-local`) and `--system-site-packages` (only needed for the Gio/GLib portal path in recording) are NOT needed for this track's code or tests. Full suite must stay green: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q` (129 tests passing on main at start).

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `wondershot/settings.py` | Modify (append after `pin_on_top` setter, ~line 278) | `quick_bar_enabled` (bool, default true) and `quick_bar_timeout` (int seconds, default 8) QSettings properties |
| `wondershot/share.py` | Modify (after `configured_providers`, ~line 138) | `default_provider(settings)` — pick the share provider the bar's Share button uses |
| `wondershot/capture_window.py` | Modify (append after `CaptureWindow`; also add a "Window" button inside `CaptureWindow`) | `QuickActionBar` widget, `quickbar_rule_position()` pure placement math, `ensure_quickbar_rule()` KWin-rule glue; "Window" capture button gated by a constructor flag |
| `wondershot/settings_dialog.py` | Modify (General tab after `show_check` ~line 145; `apply()` ~line 672) | Quick-bar checkbox + timeout spinbox |
| `wondershot/app.py` | Modify (`_on_captured` ~line 164; `_build_tray` ~line 107; `trigger_capture` ~line 151; `__init__`) | Show/wire the bar; KWin feature probe; "Capture window" tray action gated on probe |
| `wondershot/kwin.py` | Create | KDE probe, KWin script-text builder, reply parser, D-Bus call builders, crop math, `crop_file_to_global_rect`, `ActiveWindowQuery` with injectable transport |
| `wondershot/capture.py` | Modify (`captured.emit` sites lines 119 + 167; public API ~line 50) | `_finish(path)` seam applying a pending window-crop; `capture_active_window()` |
| `wondershot/gallery.py` | Modify (`_open_capture_window` ~line 724; `_capture_mode` ~line 734) | Pass the probe flag into `CaptureWindow`; route `"window-auto"` mode |
| `ROADMAP.md` | Modify (WS-C section ~line 133) | Mark both WS-C items done — **cross-track caution**: the parallel stitch-v2 track may also edit ROADMAP.md (its findings/WS-D area); this is the ONLY file the two session-2 tracks can both touch. Keep the edit confined to the WS-C bullet block (lines 133–138) so any merge conflict is trivial |
| `tests/test_settings_quickbar.py` | Create | Settings property round-trips |
| `tests/test_share_default.py` | Create | `default_provider` selection logic |
| `tests/test_quickbar.py` | Create | Bar signals, Esc dismiss, auto-dismiss timer, thumbnail, rule-position math |
| `tests/test_settings_dialog_quickbar.py` | Create | Dialog `apply()` writes the two new settings |
| `tests/test_kwin.py` | Create | Script text, reply parsing, call builders, crop math, `crop_file_to_global_rect`, `ActiveWindowQuery` against a fake transport (success/no-window/timeout/load-failure) |
| `tests/test_capture_crop.py` | Create | `CaptureManager._finish` crops in place when a pending rect is set; clears it; passes through otherwise |
| `tests/test_capture_window_mode.py` | Create | `CaptureWindow(window_mode=True)` exposes a Window button emitting `"window-auto"`; hidden when flag false |

**Gotchas for someone new to this codebase:**

- **Headless test boilerplate**: set `os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")` BEFORE any Qt import, then a session-scoped `qapp` fixture (`QApplication.instance() or QApplication([])`). Widget tests need `QApplication` (from `PySide6.QtWidgets`); pure-QImage tests can use it too — just reuse one fixture shape everywhere (see `tests/test_gallery_trash.py` lines 1–14).
- **Never instantiate `Settings()` in tests** — its `__init__` opens the real user config and runs a migration. Use `Settings.__new__(Settings)` and inject a temp `QSettings` (pattern in `tests/test_settings_ai.py::make_settings`).
- `QSettings.value()` returns strings: bool properties compare against `(True, "true")`, int properties wrap `int(...)`. Copy the existing idiom exactly (`settings.py` lines 256–278).
- **Wayland cannot self-position windows** (`move()` is a no-op for top-levels). The bubble precedent (`bubble.py::ensure_position_rule`, lines 27–76) writes a KWin window rule via `kwriteconfig6` keyed on an exact window title, then pokes KWin to `reconfigure`, and `app.py::toggle_bubble` (line 241) delays `show()` by 300 ms so KWin picks the rule up. The bar copies this exactly.
- `CaptureManager.captured` is emitted from two places: `_spectacle_done` (capture.py line 119) and `_portal_response` (line 167). Both must funnel through the new `_finish`.
- `gallery._trash_paths(paths, confirm=False)` (gallery.py line 788) stages deletes with Ctrl+Z undo — that's the trash flow to reuse, NOT `QFile.moveToTrash` directly.
- `gallery.open_editor(path)` (line 746) opens a standalone editor window — the existing "edit this file" flow used by `wondershot -e`.
- `editor.share_path(path, provider)` (editor.py line 564) uploads off-thread and puts the URL on the clipboard; the gallery toolbar calls it as `self.editor.share_path(target, provider)`. The bar reuses the same entry point via app.py.
- `_capture_mode` in gallery.py (line 734) and `trigger_capture` in app.py (line 151) are the two mode dispatchers — both gain a `"window-auto"` entry.
- The offscreen platform DOES provide a `primaryScreen()` with a virtual geometry — never assert against its specific size; pass explicit `virtual` rects to the pure crop helpers in tests.
- Run all test commands from the worktree root. Full suite: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q`.
- **Cross-track safety (session 2 runs two parallel worktrees):** the stitch-v2 track owns `stitch.py`, `scrollsource.py`, `cli.py`, `tests/test_stitch.py` — do NOT touch those here. Note the addendum's stitch fix #1 ("separate token key or none") could add a settings key near `screencast_token` (settings.py ~line 250); WS-C's settings edit is ~line 278 — different region, but if both land, merge settings.py carefully. ROADMAP.md is the one shared file (see table).

**What is explicitly NOT headless-testable (GUI glue, no failing-test step):** the bar's always-on-top stacking / KWin-rule placement on a live compositor, the Save-as `QFileDialog`, `app.py`'s show-the-bar wiring (`_show_quick_bar`, `_share_from_bar`), `ensure_quickbar_rule()`'s `kwriteconfig6` subprocess calls, the tray-menu action, the real KWin round-trip in `ActiveWindowQuery` (the transport is faked), and gallery's `_open_capture_window`/`_capture_mode` routing. These are verified in the end-of-session desktop checklist (Task 10). Everything else — settings, signal wiring inside the bar, Esc/timer behavior, script text, reply parsing, call building, crop math, `_finish` — IS tested headless.

---

## Task 1: Settings keys `quick_bar_enabled` / `quick_bar_timeout`

**Files**
- Modify: `wondershot/settings.py` (insert after the `pin_on_top` setter, line 278, before the `# -- AI` comment block)
- Create: `tests/test_settings_quickbar.py`

- [x] Write the failing test:

```python
# tests/test_settings_quickbar.py
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings


def make_settings(tmp_path):
    from wondershot.settings import Settings
    s = Settings.__new__(Settings)
    s._s = QSettings(str(tmp_path / "test.ini"), QSettings.IniFormat)
    return s


def test_quick_bar_defaults(tmp_path):
    s = make_settings(tmp_path)
    assert s.quick_bar_enabled is True
    assert s.quick_bar_timeout == 8


def test_quick_bar_roundtrip(tmp_path):
    s = make_settings(tmp_path)
    s.quick_bar_enabled = False
    s.quick_bar_timeout = 15
    assert s.quick_bar_enabled is False
    assert s.quick_bar_timeout == 15
```

- [x] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_settings_quickbar.py -q` — expect `AttributeError: 'Settings' object has no attribute 'quick_bar_enabled'`.
- [x] Implement — in `wondershot/settings.py`, insert after line 278 (`self._s.setValue("pin_on_top", ...)` setter body), before the `# -- AI (OpenAI-compatible chat endpoint)` comment:

```python
    # -- post-capture quick-action bar ---------------------------------------

    @property
    def quick_bar_enabled(self) -> bool:
        """Show the quick-action bar after a capture lands."""
        return self._s.value("quick_bar_enabled", "true") in (True, "true")

    @quick_bar_enabled.setter
    def quick_bar_enabled(self, value: bool) -> None:
        self._s.setValue("quick_bar_enabled", "true" if value else "false")

    @property
    def quick_bar_timeout(self) -> int:
        """Seconds before the quick-action bar auto-dismisses."""
        return int(self._s.value("quick_bar_timeout", 8))

    @quick_bar_timeout.setter
    def quick_bar_timeout(self, value: int) -> None:
        self._s.setValue("quick_bar_timeout", int(value))
```

- [x] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_settings_quickbar.py -q` — expect 2 passed.
- [x] Commit: `git add wondershot/settings.py tests/test_settings_quickbar.py && git commit -m "WS-C: quick-bar settings (enabled + timeout)"`

---

## Task 2: `share.default_provider(settings)`

The bar's Share button is one click — no provider menu — so it needs a deterministic default: the configured `settings.share_provider` if it's actually configured, else the first configured provider, else `""`.

**Files**
- Modify: `wondershot/share.py` (insert after `configured_providers`, which ends at line 138)
- Create: `tests/test_share_default.py`

- [x] Write the failing test:

```python
# tests/test_share_default.py
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(autouse=True)
def _no_onedrive(monkeypatch):
    # onedrive_configured() (share.py line 125) ignores `settings` and reads
    # the REAL user's Graph token via msgraph.connected_account() — on a
    # machine with OneDrive connected these tests would otherwise see a
    # phantom configured provider. Force it off; tests stay hermetic.
    monkeypatch.setattr("wondershot.share.onedrive_configured",
                        lambda s: False)


class _S:
    """Just enough settings for share-config checks."""
    def __init__(self, **kw):
        defaults = dict(share_provider="",
                        s3_endpoint="", s3_bucket="",
                        s3_access_key="", s3_secret_key="",
                        azure_account="", azure_container="", azure_key="")
        defaults.update(kw)
        self.__dict__.update(defaults)
        self.graph_client_id = "x"

    @property
    def _qsettings_stub(self):  # never used; here so nothing touches disk
        raise AssertionError


def _s3(**kw):
    return _S(s3_endpoint="https://s3.example", s3_bucket="b",
              s3_access_key="k", s3_secret_key="s", **kw)


def test_no_providers_gives_empty():
    from wondershot.share import default_provider
    assert default_provider(_S()) == ""


def test_single_provider_wins_even_if_default_unset():
    from wondershot.share import default_provider
    assert default_provider(_s3()) == "s3"


def test_configured_default_respected():
    from wondershot.share import default_provider
    s = _s3(azure_account="a", azure_container="c",
            azure_key="aGV5",  # base64-ish
            share_provider="azure")
    assert default_provider(s) == "azure"


def test_stale_default_falls_back_to_first_configured():
    from wondershot.share import default_provider
    s = _s3(share_provider="azure")  # azure not configured
    assert default_provider(s) == "s3"
```

Note: the autouse `_no_onedrive` fixture above is REQUIRED, not optional — verified: `onedrive_configured` (share.py line 125) calls `msgraph.connected_account()` which reads the real token file on disk, so without the monkeypatch `test_no_providers_gives_empty` fails on any machine with OneDrive connected (Jack's likely is — see the recent OneDrive sign-in commits).

- [x] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_share_default.py -q` — expect `ImportError: cannot import name 'default_provider'`.
- [x] Implement — in `wondershot/share.py`, after `configured_providers` (line 138):

```python
def default_provider(settings) -> str:
    """Provider for one-click share surfaces (quick bar): the user's
    default if it's configured, else the first configured one, else ''."""
    providers = configured_providers(settings)
    if not providers:
        return ""
    if settings.share_provider in providers:
        return settings.share_provider
    return providers[0]
```

- [x] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_share_default.py -q` — expect 4 passed.
- [x] Commit: `git add wondershot/share.py tests/test_share_default.py && git commit -m "WS-C: default_provider() for one-click share surfaces"`

---

## Task 3: `QuickActionBar` widget + placement math

**Files**
- Modify: `wondershot/capture_window.py` (append after the `CaptureWindow` class, line 108)
- Create: `tests/test_quickbar.py`

The bar is a plain frameless always-on-top `Qt.Tool` window (the `bubble.py` precedent — no self-positioning tricks). Copy and Save-as are handled inside the widget; Edit/Share/Trash emit signals carrying the file path for app.py to wire. The auto-dismiss timer starts on show, pauses while the mouse is over the bar, and Esc dismisses.

- [x] Write the failing test:

```python
# tests/test_quickbar.py
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _Settings:
    quick_bar_enabled = True
    quick_bar_timeout = 8


@pytest.fixture
def shot(tmp_path):
    img = QImage(120, 80, QImage.Format_RGB32)
    img.fill(Qt.darkCyan)
    p = str(tmp_path / "shot.png")
    img.save(p)
    return p


def _bar(shot):
    from wondershot.capture_window import QuickActionBar
    return QuickActionBar(_Settings(), shot)


def test_signals_carry_path_and_dismiss(qapp, shot):
    bar = _bar(shot)
    got = {}
    bar.edit_requested.connect(lambda p: got.setdefault("edit", p))
    bar.share_requested.connect(lambda p: got.setdefault("share", p))
    bar.trash_requested.connect(lambda p: got.setdefault("trash", p))
    dismissed = []
    bar.dismissed.connect(lambda: dismissed.append(1))
    bar.edit_btn.click()
    assert got["edit"] == shot
    assert dismissed  # acting on the file also dismisses the bar
    bar2 = _bar(shot)
    bar2.share_requested.connect(lambda p: got.setdefault("share", p))
    bar2.share_btn.click()
    assert got["share"] == shot
    bar3 = _bar(shot)
    bar3.trash_requested.connect(lambda p: got.setdefault("trash", p))
    bar3.trash_btn.click()
    assert got["trash"] == shot


def test_copy_puts_image_on_clipboard(qapp, shot):
    QGuiApplication.clipboard().clear()
    bar = _bar(shot)
    bar.copy_btn.click()
    assert not QGuiApplication.clipboard().image().isNull()


def test_escape_dismisses(qapp, shot):
    bar = _bar(shot)
    dismissed = []
    bar.dismissed.connect(lambda: dismissed.append(1))
    QTest.keyClick(bar, Qt.Key_Escape)
    assert dismissed


def test_timer_uses_setting_and_starts_on_show(qapp, shot):
    s = _Settings()
    s.quick_bar_timeout = 3
    from wondershot.capture_window import QuickActionBar
    bar = QuickActionBar(s, shot)
    assert bar._timer.interval() == 3000
    assert not bar._timer.isActive()
    bar.show()
    assert bar._timer.isActive()
    bar.close()


def test_thumbnail_loaded(qapp, shot):
    bar = _bar(shot)
    assert bar.thumb.pixmap() is not None
    assert not bar.thumb.pixmap().isNull()


def test_rule_position_bottom_center():
    from wondershot.capture_window import quickbar_rule_position
    avail = QRect(0, 0, 1920, 1080)
    x, y = quickbar_rule_position(avail, bar_w=480, bar_h=110)
    assert x == (1920 - 480) // 2
    assert y == 1080 - 110 - 96  # generous taskbar clearance, bubble precedent
    # multi-monitor: a screen whose origin isn't 0,0
    avail2 = QRect(1920, 0, 2560, 1440)
    x2, y2 = quickbar_rule_position(avail2, bar_w=480, bar_h=110)
    assert x2 == 1920 + (2560 - 480) // 2
    assert y2 == 1440 - 110 - 96
```

- [x] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_quickbar.py -q` — expect `ImportError: cannot import name 'QuickActionBar'`.
- [x] Implement — append to `wondershot/capture_window.py` (after line 108). Also extend the module's imports: the file currently imports from `PySide6.QtCore` (`Qt, Signal`) and `PySide6.QtWidgets`; add what's listed below.

```python
# -- post-capture quick-action bar -------------------------------------------

QUICKBAR_TITLE = "wondershot quick actions"
QUICKBAR_RULE_ID = "wondershotquickbar"


def quickbar_rule_position(avail, bar_w: int = 480, bar_h: int = 110):
    """Bottom-center placement for the KWin window rule.

    Wayland gives no panel struts (availableGeometry == full screen), so
    leave the same generous bottom clearance the bubble uses.
    """
    x = avail.x() + (avail.width() - bar_w) // 2
    y = avail.y() + avail.height() - bar_h - 96
    return x, y


def ensure_quickbar_rule() -> None:
    """KWin window rule placing the bar bottom-center on open.

    Same mechanism as bubble.ensure_position_rule (see bubble.py:27):
    Wayland clients can't position their own top-levels; rule policy 3 =
    'apply initially'. No-op off KDE. GUI glue — not unit tested.
    """
    import shutil as _shutil
    import subprocess

    if not _shutil.which("kwriteconfig6"):
        return
    from PySide6.QtGui import QGuiApplication
    screen = QGuiApplication.primaryScreen()
    if screen is None:
        return
    x, y = quickbar_rule_position(screen.availableGeometry())

    def kwrite(key, value):
        subprocess.run(["kwriteconfig6", "--file", "kwinrulesrc",
                        "--group", QUICKBAR_RULE_ID, "--key", key, value],
                       capture_output=True, timeout=5)

    try:
        out = subprocess.run(
            ["kreadconfig6", "--file", "kwinrulesrc",
             "--group", "General", "--key", "rules"],
            capture_output=True, text=True, timeout=5).stdout.strip()
        rules = [r for r in out.split(",") if r]
        kwrite("Description", "Wondershot quick-action bar")
        kwrite("title", QUICKBAR_TITLE)
        kwrite("titlematch", "1")  # exact
        kwrite("position", f"{x},{y}")
        kwrite("positionrule", "3")  # apply initially
        if QUICKBAR_RULE_ID not in rules:
            rules.append(QUICKBAR_RULE_ID)
            subprocess.run(["kwriteconfig6", "--file", "kwinrulesrc",
                            "--group", "General", "--key", "rules",
                            ",".join(rules)],
                           capture_output=True, timeout=5)
        subprocess.run(["busctl", "--user", "call", "org.kde.KWin", "/KWin",
                        "org.kde.KWin", "reconfigure"],
                       capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


class QuickActionBar(QWidget):
    """Frameless always-on-top bar shown after a capture lands.

    Acts on the just-captured file. Copy/Save-as are handled here;
    Edit/Share/Trash are emitted for the app coordinator to wire into
    the existing gallery/editor flows. Mouse-first; Esc dismisses;
    auto-dismisses after settings.quick_bar_timeout seconds (paused
    while hovered).
    """

    edit_requested = Signal(str)
    share_requested = Signal(str)
    trash_requested = Signal(str)
    dismissed = Signal()

    def __init__(self, settings, path: str, parent=None):
        super().__init__(parent)
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QIcon, QPixmap
        from PySide6.QtWidgets import QToolButton

        self.settings = settings
        self.path = path
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                            | Qt.Tool)
        self.setWindowTitle(QUICKBAR_TITLE)

        row = QHBoxLayout(self)
        row.setContentsMargins(12, 8, 8, 8)
        row.setSpacing(6)

        self.thumb = QLabel(self)
        pm = QPixmap(path)
        if not pm.isNull():
            self.thumb.setPixmap(
                pm.scaledToHeight(56, Qt.SmoothTransformation))
        row.addWidget(self.thumb)
        row.addSpacing(8)

        def btn(text, icon, slot):
            b = QToolButton(self)
            b.setText(text)
            b.setIcon(QIcon.fromTheme(icon))
            b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            b.setAutoRaise(True)
            b.clicked.connect(slot)
            row.addWidget(b)
            return b

        self.edit_btn = btn("Edit", "document-edit",
                            lambda: self._act(self.edit_requested))
        self.copy_btn = btn("Copy", "edit-copy", self._copy)
        self.save_btn = btn("Save as", "document-save-as", self._save_as)
        self.share_btn = btn("Share", "document-send",
                             lambda: self._act(self.share_requested))
        self.trash_btn = btn("Trash", "user-trash",
                             lambda: self._act(self.trash_requested))

        self.close_btn = QToolButton(self)
        self.close_btn.setText("✕")
        self.close_btn.setAutoRaise(True)
        self.close_btn.setToolTip("Dismiss (Esc)")
        self.close_btn.clicked.connect(self.dismiss)
        row.addWidget(self.close_btn)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(max(2, int(settings.quick_bar_timeout)) * 1000)
        self._timer.timeout.connect(self.dismiss)

    # -- behavior ---------------------------------------------------------

    def _act(self, sig) -> None:
        sig.emit(self.path)
        self.dismiss()

    def _copy(self) -> None:
        from PySide6.QtGui import QGuiApplication, QImage
        img = QImage(self.path)
        if not img.isNull():
            QGuiApplication.clipboard().setImage(img)
        self.dismiss()

    def _save_as(self) -> None:  # GUI glue — file dialog, not unit tested
        import shutil as _shutil
        from PySide6.QtWidgets import QFileDialog
        self._timer.stop()  # don't vanish under the dialog
        dest, _ = QFileDialog.getSaveFileName(
            self, "Save copy", os.path.join(
                os.path.expanduser("~"), os.path.basename(self.path)),
            "Images (*.png *.jpg *.webp)")
        if dest:
            try:
                _shutil.copy2(self.path, dest)
            except OSError:
                pass
        self.dismiss()

    def dismiss(self) -> None:
        self._timer.stop()
        self.dismissed.emit()
        self.close()

    # -- events -------------------------------------------------------------

    def showEvent(self, ev):  # noqa: N802
        self._timer.start()
        super().showEvent(ev)

    def enterEvent(self, ev):  # noqa: N802 — hover pauses auto-dismiss
        self._timer.stop()
        super().enterEvent(ev)

    def leaveEvent(self, ev):  # noqa: N802
        self._timer.start()
        super().leaveEvent(ev)

    def keyPressEvent(self, ev):  # noqa: N802
        if ev.key() == Qt.Key_Escape:
            self.dismiss()
        else:
            super().keyPressEvent(ev)
```

Import notes for `capture_window.py`: the only new top-level import is `import os` (add it below `import shutil`, line 10). Everything else the bar needs at module level — `Qt`, `Signal`, `QHBoxLayout`, `QLabel`, `QWidget` — is already imported (lines 12–22); `QToolButton`, `QTimer`, `QIcon`, `QPixmap`, `QGuiApplication`, `QImage`, `QFileDialog` are imported lazily inside the methods above, so the existing `PySide6.QtWidgets` import block needs no change.

- [x] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_quickbar.py -q` — expect 6 passed.
- [x] Run the whole suite to catch import fallout: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q` — expect all green.
- [x] Commit: `git add wondershot/capture_window.py tests/test_quickbar.py && git commit -m "WS-C: QuickActionBar widget + KWin-rule placement helper"`

---

## Task 4: Settings dialog — quick-bar controls

**Files**
- Modify: `wondershot/settings_dialog.py` (General tab, after `form.addRow("", self.show_check)` at line 145; `apply()` after the `show_gallery_after_capture` line at line 672)
- Create: `tests/test_settings_dialog_quickbar.py`

- [x] Write the failing test (mirror the fixture shape of `tests/test_settings_dialog_ai.py` — read it first and reuse its `make_settings`/`qapp` idiom verbatim; the version below assumes the `test_settings_ai.py` injection pattern):

```python
# tests/test_settings_dialog_quickbar.py
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def make_settings(tmp_path):
    from wondershot.settings import Settings
    s = Settings.__new__(Settings)
    s._s = QSettings(str(tmp_path / "test.ini"), QSettings.IniFormat)
    return s


def test_apply_writes_quick_bar_settings(qapp, tmp_path):
    from wondershot.settings_dialog import SettingsDialog
    s = make_settings(tmp_path)
    s.library_dir = str(tmp_path)  # keep the dialog off the real library
    dlg = SettingsDialog(s)
    assert dlg.quickbar_check.isChecked() is True
    assert dlg.quickbar_timeout.value() == 8
    dlg.quickbar_check.setChecked(False)
    dlg.quickbar_timeout.setValue(20)
    dlg.apply()
    assert s.quick_bar_enabled is False
    assert s.quick_bar_timeout == 20
```

- [x] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_settings_dialog_quickbar.py -q` — expect `AttributeError: ... no attribute 'quickbar_check'`.
- [x] Implement — in `settings_dialog.py`, insert after line 145 (`form.addRow("", self.show_check)`):

```python
        self.quickbar_check = QCheckBox("Quick-action bar after capture")
        self.quickbar_check.setChecked(settings.quick_bar_enabled)
        form.addRow("", self.quickbar_check)

        self.quickbar_timeout = QSpinBox()
        self.quickbar_timeout.setRange(2, 60)
        self.quickbar_timeout.setSuffix(" s")
        self.quickbar_timeout.setValue(settings.quick_bar_timeout)
        self.quickbar_timeout.setToolTip(
            "Auto-dismiss the quick-action bar after this many seconds")
        form.addRow("Bar timeout:", self.quickbar_timeout)
```

`QSpinBox` may not yet be in the dialog's import block — check the `PySide6.QtWidgets` import at the top of `settings_dialog.py` and add `QSpinBox` if missing. Then in `apply()`, after line 672 (`self.settings.show_gallery_after_capture = ...`):

```python
        self.settings.quick_bar_enabled = self.quickbar_check.isChecked()
        self.settings.quick_bar_timeout = self.quickbar_timeout.value()
```

- [x] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_settings_dialog_quickbar.py -q` — expect 1 passed.
- [x] Commit: `git add wondershot/settings_dialog.py tests/test_settings_dialog_quickbar.py && git commit -m "WS-C: quick-bar settings in the General tab"`

---

## Task 5: app.py wiring of the quick bar (GUI glue — no headless test)

**This task is GUI glue and intentionally has no failing-test step**: it constructs an always-on-top window in response to a live capture and connects its signals to gallery flows that are already covered by their own tests (`test_gallery_trash.py`, `test_share.py`). Desktop verification happens in Task 10's checklist.

**Files**
- Modify: `wondershot/app.py` (`_on_captured`, lines 164–175; new methods after `show_gallery`, line 185)

- [x] Replace `_on_captured` (app.py lines 164–175) with:

```python
    def _on_captured(self, path: str) -> None:
        if self.settings.copy_after_capture:
            img = QImage(path)
            if not img.isNull():
                QGuiApplication.clipboard().setImage(img)
        self.gallery.rescan()
        self.gallery.select_path(path)
        if self.settings.show_gallery_after_capture or self._gallery_was_visible:
            self.show_gallery()
        elif self.settings.quick_bar_enabled:
            # gallery isn't coming forward — offer quick actions instead
            self._show_quick_bar(path)
        note = " · copied to clipboard" if self.settings.copy_after_capture else ""
        self.tray.showMessage("Wondershot", os.path.basename(path) + note,
                              self.icon, 2500)
```

(Behavioral decision, documented: the bar appears only when the gallery is *not* being brought forward — when the gallery shows, every bar action is already one click away in its toolbar. The spec Addendum's phrasing "after a capture lands (and preview is enabled)" is ambiguous about which "preview"; this plan reads it as the bar's own `quick_bar_enabled` setting plus the gallery-not-shown condition. If review disagrees, the gate is this one `elif` — trivial to flip.)

- [x] Add after `show_gallery` (line 185):

```python
    # -- post-capture quick-action bar ---------------------------------------

    def _show_quick_bar(self, path: str) -> None:
        from .capture_window import QuickActionBar, ensure_quickbar_rule
        old = getattr(self, "quick_bar", None)
        if old is not None:
            try:
                old.dismiss()
            except RuntimeError:
                pass  # already deleted (WA_DeleteOnClose)
        bar = QuickActionBar(self.settings, path)
        bar.setAttribute(Qt.WA_DeleteOnClose, True)
        bar.edit_requested.connect(self.gallery.open_editor)
        bar.share_requested.connect(self._share_from_bar)
        bar.trash_requested.connect(
            lambda p: self.gallery._trash_paths([p], confirm=False))
        self.quick_bar = bar
        ensure_quickbar_rule()
        # let KWin pick up the freshly-written position rule first
        # (same 300 ms dance as toggle_bubble, app.py line 241)
        QTimer.singleShot(300, bar.show)

    def _share_from_bar(self, path: str) -> None:
        from .share import default_provider
        provider = default_provider(self.settings)
        if not provider:
            self.tray.showMessage(
                "Wondershot", "Set up sharing in Settings → Sharing",
                self.icon, 3000)
            return
        # reuses the editor's async upload + clipboard flow; outcome toasts
        # arrive via the existing share_status → tray connection (line 90)
        self.gallery.editor.share_path(path, provider)
```

- [x] Sanity-run the suite (app.py is imported by tests indirectly): `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q` — all green.
- [x] Smoke-import: `QT_QPA_PLATFORM=offscreen .venv/bin/python -c "import wondershot.app"` — no traceback.
- [x] Commit: `git add wondershot/app.py && git commit -m "WS-C: show quick-action bar after capture; wire edit/share/trash"`

---

## Task 6: kwin.py pure layer — probe, script text, reply parsing, call builders, crop math

**Files**
- Create: `wondershot/kwin.py`
- Create: `tests/test_kwin.py`

- [x] Write the failing test:

```python
# tests/test_kwin.py
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
```

- [x] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_kwin.py -q` — expect `ModuleNotFoundError: No module named 'wondershot.kwin'`.
- [x] Implement — create `wondershot/kwin.py`:

```python
"""KWin scripting D-Bus: KDE probe + active-window frame geometry.

DANGER ZONE — KWin hosts the Wayland compositor. A malformed D-Bus call
into it has aborted KWin before (KGlobalAccel, kwin 6.6.5 — see
ROADMAP.md "Platform landmines" and hotkey.py's module docstring).
Rules in this module:

- only the documented org.kde.kwin.Scripting methods are called
  (loadScript / unloadScript, Script.run / Script.stop), with plain
  string/int arguments — never dicts, never variants;
- the geometry answer travels KWin→us as a single comma-joined STRING
  via callDBus from the injected script, so we never depend on KWin's
  number marshalling and our receiving slot is a simple @Slot(str);
- every call has a hard timeout; any failure is reported via failed()
  and the feature simply doesn't exist — no retries, no dialogs.
"""

from __future__ import annotations

import os
import tempfile

from PySide6.QtCore import QObject, QRect, QTimer, Signal, Slot

SERVICE = "org.kde.KWin"
SCRIPTING_PATH = "/Scripting"
SCRIPTING_IFACE = "org.kde.kwin.Scripting"
SCRIPT_IFACE = "org.kde.kwin.Script"
PLUGIN_NAME = "wondershot-active-window"
CALLBACK_PATH = "/wondershot/kwin"
CALLBACK_IFACE = "com.wondershot.kwin"
CALLBACK_METHOD = "geometry"


# -- feature probe -----------------------------------------------------------

def is_kde(env=None) -> bool:
    env = os.environ if env is None else env
    return "kde" in env.get("XDG_CURRENT_DESKTOP", "").lower()


def kwin_available() -> bool:
    """Cheap startup probe: KDE session + the KWin service on the bus.

    Never calls INTO KWin — just asks the bus daemon who's registered.
    """
    if not is_kde():
        return False
    try:
        from PySide6.QtDBus import QDBusConnection
        bus = QDBusConnection.sessionBus()
        return (bus.isConnected()
                and bool(bus.interface().isServiceRegistered(SERVICE)))
    except Exception:  # noqa: BLE001 — probe must never raise
        return False


# -- script text -----------------------------------------------------------

def build_geometry_script(service: str, path: str, iface: str,
                          method: str) -> str:
    """JS for KWin: report the active window's frame geometry back to us.

    activeWindow is KWin 6; activeClient the KWin 5 name — try both.
    The reply is one string ("x,y,w,h"), empty when there is no active
    window, so the D-Bus signature is always a lone 's'.
    """
    return (
        "var w = workspace.activeWindow || workspace.activeClient;\n"
        "if (w && w.frameGeometry) {\n"
        "    var g = w.frameGeometry;\n"
        f'    callDBus("{service}", "{path}", "{iface}", "{method}",\n'
        '             "" + g.x + "," + g.y + "," + g.width + "," + g.height);\n'
        "} else {\n"
        f'    callDBus("{service}", "{path}", "{iface}", "{method}", "");\n'
        "}\n"
    )


def parse_geometry_reply(text: str):
    """'x,y,w,h' -> (x, y, w, h) ints, or None for anything unusable."""
    parts = text.split(",")
    if len(parts) != 4:
        return None
    try:
        x, y, w, h = (int(float(p)) for p in parts)
    except ValueError:
        return None
    if w <= 0 or h <= 0:
        return None
    return (x, y, w, h)


# -- D-Bus call builders (pure; args are str/int ONLY — see module doc) -----

def build_load_call(script_path: str, plugin: str):
    return (SERVICE, SCRIPTING_PATH, SCRIPTING_IFACE, "loadScript",
            [script_path, plugin])


def build_run_call(script_id: int):
    return (SERVICE, f"/Scripting/Script{script_id}", SCRIPT_IFACE, "run", [])


def build_stop_call(script_id: int):
    return (SERVICE, f"/Scripting/Script{script_id}", SCRIPT_IFACE, "stop", [])


def build_unload_call(plugin: str):
    return (SERVICE, SCRIPTING_PATH, SCRIPTING_IFACE, "unloadScript",
            [plugin])


# -- crop math ----------------------------------------------------------------

def map_global_rect(rect: QRect, virtual: QRect, img_w: int,
                    img_h: int) -> QRect:
    """Map a global (logical) rect into a fullscreen image's pixel space.

    The fullscreen capture covers the virtual-desktop union of all
    screens; under HiDPI its pixel size exceeds the logical union, so
    scale by image/virtual per axis, translate off the union origin
    (which can be negative — left monitors), and clamp to the image.
    """
    if (virtual.width() <= 0 or virtual.height() <= 0
            or img_w <= 0 or img_h <= 0):
        return QRect()
    sx = img_w / virtual.width()
    sy = img_h / virtual.height()
    mapped = QRect(round((rect.x() - virtual.x()) * sx),
                   round((rect.y() - virtual.y()) * sy),
                   round(rect.width() * sx),
                   round(rect.height() * sy))
    return mapped.intersected(QRect(0, 0, img_w, img_h))


def crop_file_to_global_rect(path: str, rect: QRect, virtual: QRect) -> bool:
    """Crop the image at `path` in place to the global rect. False = no-op."""
    from PySide6.QtGui import QImage
    img = QImage(path)
    if img.isNull():
        return False
    target = map_global_rect(rect, virtual, img.width(), img.height())
    if target.isEmpty():
        return False
    return img.copy(target).save(path)
```

- [x] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_kwin.py -q` — expect all of Task 6's tests passing (the `ActiveWindowQuery` tests arrive in Task 7).
- [x] Commit: `git add wondershot/kwin.py tests/test_kwin.py && git commit -m "WS-C: kwin.py pure layer — probe, script text, call builders, crop math"`

---

## Task 7: `ActiveWindowQuery` with an injectable transport

The query object: register ourselves on the bus (so KWin's script can call us back at our unique bus name), write the script to a temp file, `loadScript` → `run`, await the `geometry` slot or a timeout, then always clean up (`stop`, `unloadScript`, unregister, delete temp file). All bus traffic goes through a transport object so tests inject a fake; the real transport is thin glue.

**Files**
- Modify: `wondershot/kwin.py` (append)
- Modify: `tests/test_kwin.py` (append)

- [ ] Write the failing tests (append to `tests/test_kwin.py`):

```python
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
```

- [ ] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_kwin.py -q` — expect the new tests failing with `ImportError: cannot import name 'ActiveWindowQuery'`.
- [ ] Implement — append to `wondershot/kwin.py`:

```python
# -- the query object ---------------------------------------------------------

class _DBusTransport:
    """Real session-bus transport. Thin glue — tests use FakeTransport."""

    def __init__(self):
        from PySide6.QtDBus import QDBusConnection
        self._bus = QDBusConnection.sessionBus()

    def service_name(self) -> str:
        return self._bus.baseService()

    def register(self, path: str, obj) -> bool:
        from PySide6.QtDBus import QDBusConnection
        return self._bus.registerObject(
            path, obj, QDBusConnection.ExportAllSlots)

    def unregister(self, path: str) -> None:
        self._bus.unregisterObject(path)

    def call(self, service, path, iface, method, args):
        """Blocking call with a hard 1 s timeout. None on any error."""
        from PySide6.QtDBus import QDBus, QDBusMessage
        msg = QDBusMessage.createMethodCall(service, path, iface, method)
        msg.setArguments(list(args))
        reply = self._bus.call(msg, QDBus.Block, 1000)
        if reply.type() != QDBusMessage.ReplyMessage:
            return None
        a = reply.arguments()
        return a[0] if a else True


class ActiveWindowQuery(QObject):
    """One-shot: emit finished(x, y, w, h) for the active window, or failed(msg).

    KWin runs our tiny script (build_geometry_script) which calls our
    registered `geometry` slot back with one string. Defensive posture
    throughout — see the module docstring.
    """

    finished = Signal(int, int, int, int)
    failed = Signal(str)

    def __init__(self, parent=None, transport=None, timeout_ms: int = 2000):
        super().__init__(parent)
        self._transport = transport
        self._script_id: int | None = None
        self._tmp: str | None = None
        self._done = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(timeout_ms)
        self._timer.timeout.connect(
            lambda: self._fail("KWin did not answer (timeout)"))

    def _t(self):
        if self._transport is None:
            self._transport = _DBusTransport()
        return self._transport

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        t = self._t()
        if not t.register(CALLBACK_PATH, self):
            self._fail("could not register D-Bus callback object",
                       registered=False)
            return
        script = build_geometry_script(t.service_name(), CALLBACK_PATH,
                                       CALLBACK_IFACE, CALLBACK_METHOD)
        fd, self._tmp = tempfile.mkstemp(suffix=".js",
                                         prefix="wondershot-kwin-")
        with os.fdopen(fd, "w") as f:
            f.write(script)
        # clear any stale copy left by a previous crash, then load
        t.call(*build_unload_call(PLUGIN_NAME))
        reply = t.call(*build_load_call(self._tmp, PLUGIN_NAME))
        if reply is None:
            self._fail("KWin loadScript failed")
            return
        try:
            self._script_id = int(reply)
        except (TypeError, ValueError):
            self._fail("KWin loadScript returned no script id")
            return
        if t.call(*build_run_call(self._script_id)) is None:
            self._fail("KWin script run failed")
            return
        self._timer.start()

    # -- KWin's script calls this back (via D-Bus, ExportAllSlots) ----------

    @Slot(str)
    def geometry(self, text: str) -> None:
        if self._done:
            return  # straggler after failure/timeout
        rect = parse_geometry_reply(text)
        if rect is None:
            self._fail("no active window")
            return
        self._done = True
        self._cleanup()
        self.finished.emit(*rect)

    # -- teardown -------------------------------------------------------------

    def _fail(self, msg: str, registered: bool = True) -> None:
        if self._done:
            return
        self._done = True
        if registered:
            self._cleanup()
        self.failed.emit(msg)

    def _cleanup(self) -> None:
        self._timer.stop()
        t = self._t()
        if self._script_id is not None:
            t.call(*build_stop_call(self._script_id))
        t.call(*build_unload_call(PLUGIN_NAME))
        t.unregister(CALLBACK_PATH)
        if self._tmp:
            try:
                os.unlink(self._tmp)
            except OSError:
                pass
            self._tmp = None
```

Note for the implementer: `test_query_load_failure` expects cleanup (`unregistered`) even though `loadScript` failed — `_fail` with default `registered=True` runs `_cleanup`, which calls `unloadScript` again (harmless, idempotent on KWin's side) and unregisters. `test_query_register_failure` passes `registered=False` so `_cleanup` is skipped — there is nothing to clean and `loadScript` was never called.

- [ ] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_kwin.py -q` — expect all passed (Task 6 + Task 7 tests).
- [ ] Commit: `git add wondershot/kwin.py tests/test_kwin.py && git commit -m "WS-C: ActiveWindowQuery — KWin script round-trip with injectable transport"`

---

## Task 8: CaptureManager — `_finish` crop seam + `capture_active_window`

**Files**
- Modify: `wondershot/capture.py`
- Create: `tests/test_capture_crop.py`

- [ ] Write the failing test:

```python
# tests/test_capture_crop.py
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


class _Settings:
    backend = "spectacle"
    capture_cursor = False
    capture_delay = 0

    def __init__(self, library_dir):
        self.library_dir = library_dir


def _manager(tmp_path):
    from wondershot.capture import CaptureManager
    return CaptureManager(_Settings(str(tmp_path)))


def _png(tmp_path, w=200, h=100):
    img = QImage(w, h, QImage.Format_RGB32)
    img.fill(Qt.blue)
    p = str(tmp_path / "full.png")
    img.save(p)
    return p


def test_finish_passthrough_without_pending_crop(qapp, tmp_path):
    m = _manager(tmp_path)
    p = _png(tmp_path)
    got = []
    m.captured.connect(got.append)
    m._finish(p)
    assert got == [p]
    assert QImage(p).width() == 200  # untouched


def test_finish_crops_and_clears_pending(qapp, tmp_path):
    m = _manager(tmp_path)
    p = _png(tmp_path)
    got = []
    m.captured.connect(got.append)
    m._pending_crop = QRect(10, 20, 50, 40)
    m._crop_virtual = QRect(0, 0, 200, 100)  # test seam: explicit virtual
    m._finish(p)
    assert got == [p]
    out = QImage(p)
    assert (out.width(), out.height()) == (50, 40)
    assert m._pending_crop is None  # one-shot


def test_finish_emits_uncropped_when_rect_unusable(qapp, tmp_path):
    m = _manager(tmp_path)
    p = _png(tmp_path)
    got = []
    m.captured.connect(got.append)
    m._pending_crop = QRect(9999, 9999, 10, 10)  # off-virtual
    m._crop_virtual = QRect(0, 0, 200, 100)
    m._finish(p)
    assert got == [p]  # degrade to the full shot, never fail the capture
    assert QImage(p).width() == 200


def test_public_capture_modes_clear_pending_crop(qapp, tmp_path, monkeypatch):
    m = _manager(tmp_path)
    m._pending_crop = QRect(0, 0, 10, 10)
    monkeypatch.setattr(m, "_capture", lambda mode: None)
    m.capture_region()
    assert m._pending_crop is None
```

- [ ] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_capture_crop.py -q` — expect `AttributeError: ... has no attribute '_finish'`.
- [ ] Implement — in `wondershot/capture.py`:

1. In `__init__` (after line 46, `self._portal_pending_path ...`), add:

```python
        self._pending_crop = None   # QRect: crop the next capture to this
        self._crop_virtual = None   # test seam; None = live screen union
        self._geom_query = None     # keep the KWin query alive
```

2. In the public API section, change the three public methods (lines 50–57) to clear any stale pending crop, and add the new mode:

```python
    def capture_region(self) -> None:
        self._pending_crop = None
        self._capture("region")

    def capture_fullscreen(self) -> None:
        self._pending_crop = None
        self._capture("fullscreen")

    def capture_window(self) -> None:
        self._pending_crop = None
        self._capture("window")

    def capture_active_window(self) -> None:
        """KDE-only: crop a fullscreen shot to the active window's frame.

        Geometry comes from KWin scripting (kwin.py — defensive, timed
        out, feature-probed); then we reuse the normal fullscreen path
        and crop in _finish. No interactive pick."""
        from .kwin import ActiveWindowQuery
        self._pending_crop = None
        q = ActiveWindowQuery(self)
        self._geom_query = q
        q.finished.connect(self._geometry_ready)
        q.failed.connect(
            lambda msg: self.failed.emit(f"window geometry: {msg}"))
        q.start()

    def _geometry_ready(self, x: int, y: int, w: int, h: int) -> None:
        from PySide6.QtCore import QRect
        self._pending_crop = QRect(x, y, w, h)
        self._capture("fullscreen")
```

3. Add `_finish` (place it just above `_spectacle_done`, ~line 114):

```python
    def _finish(self, path: str) -> None:
        """Common tail for both backends: apply a pending window crop."""
        crop, self._pending_crop = self._pending_crop, None
        if crop is not None:
            from .kwin import crop_file_to_global_rect
            virtual = self._crop_virtual
            if virtual is None:
                from PySide6.QtGui import QGuiApplication
                screen = QGuiApplication.primaryScreen()
                virtual = screen.virtualGeometry() if screen else None
            if virtual is not None:
                # False = unusable rect; degrade to the full shot
                crop_file_to_global_rect(path, crop, virtual)
        self.captured.emit(path)
```

4. Replace the two emit sites: in `_spectacle_done` (line 119) change `self.captured.emit(out)` → `self._finish(out)`; in `_portal_response` (line 167) change `self.captured.emit(dest)` → `self._finish(dest)`.

- [ ] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_capture_crop.py -q` — expect 4 passed.
- [ ] Full suite: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q` — all green.
- [ ] Commit: `git add wondershot/capture.py tests/test_capture_crop.py && git commit -m "WS-C: capture_active_window — KWin geometry, fullscreen + crop via _finish seam"`

---

## Task 9: UI gating — tray action, CaptureWindow button, gallery routing

The "Window" option appears ONLY when `kwin_available()` passes (KDE-only by design; off-KDE the option doesn't exist anywhere).

**Files**
- Modify: `wondershot/capture_window.py` (`CaptureWindow.__init__`, lines 28 + 93–101)
- Modify: `wondershot/app.py` (`__init__` ~line 96; `_build_tray` after the fullscreen action, line 115; `trigger_capture` mode map, line 157)
- Modify: `wondershot/gallery.py` (`_open_capture_window` line 724; `_capture_mode` line 734)
- Create: `tests/test_capture_window_mode.py`

- [ ] Write the failing test:

```python
# tests/test_capture_window_mode.py
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QPushButton


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _Settings:
    show_gallery_after_capture = True
    copy_after_capture = True
    capture_cursor = False
    capture_delay = 0


def _window_buttons(w):
    return [b for b in w.findChildren(QPushButton) if b.text() == "Window"]


def test_window_button_present_and_fires_mode(qapp):
    from wondershot.capture_window import CaptureWindow
    w = CaptureWindow(_Settings(), window_mode=True)
    btns = _window_buttons(w)
    assert len(btns) == 1
    fired = []
    w.capture_requested.connect(fired.append)
    btns[0].click()
    assert fired == ["window-auto"]


def test_window_button_hidden_without_probe(qapp):
    from wondershot.capture_window import CaptureWindow
    w = CaptureWindow(_Settings())  # default: no window mode
    assert not _window_buttons(w)
```

- [ ] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_capture_window_mode.py -q` — expect `TypeError: ... unexpected keyword argument 'window_mode'`.
- [ ] Implement `CaptureWindow` changes — signature (line 28) becomes:

```python
    def __init__(self, settings, parent=None, window_mode: bool = False):
```

and the secondary-actions row (lines 93–100) becomes:

```python
        row = QHBoxLayout()
        secondary = [("Full screen", "fullscreen")]
        if window_mode:
            secondary.append(("Window", "window-auto"))
        secondary.append(("Record", "record"))
        for label, mode in secondary:
            b = QPushButton(label)
            b.setFlat(True)
            b.setStyleSheet("color: palette(link);")
            b.clicked.connect(lambda _=False, m=mode: self._fire(m))
            row.addWidget(b)
```

Also update the signal docstring comment on line 26: `capture_requested = Signal(str)  # "region" | "fullscreen" | "window-auto" | "record"`.

- [ ] Run: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/test_capture_window_mode.py -q` — expect 2 passed.
- [ ] Wire app.py (GUI glue — no headless test for these three edits, stated explicitly):

  1. In `GrabbitApp.__init__`, right before `self.hotkey = create_hotkey_backend(self)` (line 96):

```python
        from .kwin import kwin_available
        self.kwin_ok = kwin_available()
        self.gallery.kwin_ok = self.kwin_ok  # gates the CaptureWindow button
```

  2. In `_build_tray`, after the "Capture full screen" action block (line 115, before `menu.addSeparator()`):

```python
        if self.kwin_ok:
            a = QAction("Capture window", menu)
            a.setToolTip("Grab the active window (no picker, KDE only)")
            a.triggered.connect(lambda: self.trigger_capture("window-auto"))
            menu.addAction(a)
```

  Gotcha: `_build_tray` runs from `__init__` line 88 — BEFORE the probe added in step 1 if you insert the probe at line 96. Move the two probe lines ABOVE `self.tray = self._build_tray()` (i.e., right after the gallery is constructed, ~line 84).

  3. In `trigger_capture` (line 157), extend the mode map:

```python
        fn = {
            "region": self.capture.capture_region,
            "fullscreen": self.capture.capture_fullscreen,
            "window": self.capture.capture_window,
            "window-auto": self.capture.capture_active_window,
        }[mode]
```

- [ ] Wire gallery.py (GUI glue — no headless test, stated explicitly):

  1. `_open_capture_window` (line 724): pass the flag —

```python
            self._capture_window = CaptureWindow(
                self.settings, window_mode=getattr(self, "kwin_ok", False))
```

  2. `_capture_mode` (line 734): add the branch before the final `else`:

```python
        elif mode == "window-auto":
            self.capture.capture_active_window()
```

- [ ] Full suite: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q` — all green. Smoke-import: `QT_QPA_PLATFORM=offscreen .venv/bin/python -c "import wondershot.app, wondershot.gallery, wondershot.capture_window"`.
- [ ] Commit: `git add wondershot/capture_window.py wondershot/app.py wondershot/gallery.py tests/test_capture_window_mode.py && git commit -m "WS-C: Window capture mode in tray + capture panel, gated on KWin probe"`

---

## Task 10: Full verification + ROADMAP update + desktop checklist

**Files**
- Modify: `ROADMAP.md` (WS-C section, lines 133–138)

- [ ] Run the complete suite: `QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest tests/ -q` — expect ~160 passed (129 baseline + ~31 new), 0 failures.
- [ ] Update `ROADMAP.md` WS-C section (lines 133–138) — replace the two bullets with:

```markdown
**WS-C — Capture UX** _(done 2026-06-07)_
- Post-capture quick-action toolbar: DONE — frameless always-on-top bar
  (KWin position rule, bubble precedent) with Edit/Copy/Save-as/Share/
  Trash/dismiss on the just-captured file; auto-dismiss setting
  (default 8 s), Esc dismisses; shown only when the gallery isn't
  brought forward.
- Auto-size-to-window: DONE — KDE-only via KWin scripting D-Bus
  (`kwin.py`: script injected via loadScript, geometry returned as one
  string to a registered slot, hard timeouts, feature-probe hides the
  mode off-KDE); fullscreen capture cropped to the active window's
  frame, multi-monitor + HiDPI aware. Trivial on X11/Win/mac later;
  GNOME needs an extension — documented, not built.
```

- [ ] Append the following to the desktop-only verification checklist that the session batches for Jack (per the Addendum's rule of engagement — create `docs/superpowers/plans/2026-06-07-ws-c-desktop-checklist.md` if the orchestrator hasn't designated a shared one):

```markdown
# WS-C desktop checklist (live KDE session, NOT offscreen)

1. Quick bar: Settings → General → "Quick-action bar after capture" ON,
   "Show Wondershot window after capture" OFF. Capture a region — a
   frameless bar should appear bottom-center, above other windows, with
   a thumbnail of the shot. Verify: Edit opens the editor on the file;
   Copy → paste into another app; Save as → file lands where chosen;
   Share → URL on clipboard (with a provider configured) or a tray hint
   (without); Trash → file gone from the gallery, Ctrl+Z in the gallery
   restores it; Esc dismisses; left alone it dismisses after the
   configured timeout; hovering pauses the countdown.
2. Bar does NOT appear when "Show Wondershot window after capture" is ON.
3. Window mode: tray menu shows "Capture window" (KDE). Focus a window,
   trigger it — the saved PNG is exactly that window's frame, correct
   monitor, correct under HiDPI scaling. Repeat with a window on the
   second monitor. KWin must remain alive throughout (the whole point).
4. Off-KDE sanity (optional, any GNOME/wlroots session or
   XDG_CURRENT_DESKTOP unset): no "Capture window" in the tray, no
   "Window" button in the capture panel.
```

- [ ] Commit: `git add ROADMAP.md docs/superpowers/plans/2026-06-07-ws-c-desktop-checklist.md && git commit -m "WS-C: roadmap + desktop verification checklist"`
- [ ] Request code review per superpowers:requesting-code-review before merge; do NOT merge to main yourself — finishing-a-development-branch handles integration.
