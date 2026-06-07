"""Settings-driven Windows hotkey: chord conversion + rebind plumbing.

Jack 2026-06-07: "Windows DEFINITELY can update keybinds" — the chord
lives in settings.hotkey_capture, edited via Settings → General, and
the backend re-registers on apply.
"""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from wondershot.hotkey import (MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN,
                               VK_SNAPSHOT, WinHotkeyBackend, qt_to_win)


def test_default_chord():
    assert qt_to_win("Ctrl+Shift+Print") == (MOD_CONTROL | MOD_SHIFT,
                                             VK_SNAPSHOT)


@pytest.mark.parametrize("chord,expected", [
    ("Ctrl+Alt+S", (MOD_CONTROL | MOD_ALT, ord("S"))),
    ("Meta+Shift+4", (MOD_WIN | MOD_SHIFT, ord("4"))),
    ("F9", (0, 0x78)),
    ("Ctrl+F12", (MOD_CONTROL, 0x7B)),
    ("Alt+Space", (MOD_ALT, 0x20)),
])
def test_common_chords(chord, expected):
    assert qt_to_win(chord) == expected


@pytest.mark.parametrize("bad", ["", "Ctrl+Shift", "A+B", "Ctrl+Bogus"])
def test_unparseable_chords_return_none(bad):
    assert qt_to_win(bad) is None


def test_backend_falls_back_to_default_on_garbage():
    class S:
        hotkey_capture = "total nonsense"
    b = WinHotkeyBackend(settings=S())
    assert b._chord() == (MOD_CONTROL | MOD_SHIFT, VK_SNAPSHOT)


def test_backend_reads_settings_chord():
    class S:
        hotkey_capture = "Ctrl+Alt+W"
    b = WinHotkeyBackend(settings=S())
    assert b._chord() == (MOD_CONTROL | MOD_ALT, ord("W"))
