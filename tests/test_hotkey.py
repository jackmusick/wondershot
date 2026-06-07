import os
import sys

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_factory_picks_kglobalaccel_on_linux(monkeypatch):
    from wondershot import hotkey
    monkeypatch.setattr(sys, "platform", "linux")
    b = hotkey.create_hotkey_backend()
    assert isinstance(b, hotkey.KGlobalAccelBackend)
    assert isinstance(b, hotkey.HotkeyBackend)


def test_factory_picks_null_on_darwin(monkeypatch):
    from wondershot import hotkey
    monkeypatch.setattr(sys, "platform", "darwin")
    b = hotkey.create_hotkey_backend()
    assert isinstance(b, hotkey.NullHotkeyBackend)


def test_factory_picks_win_backend_on_windows(monkeypatch):
    from wondershot import hotkey
    monkeypatch.setattr(sys, "platform", "win32")
    b = hotkey.create_hotkey_backend()
    assert isinstance(b, hotkey.WinHotkeyBackend)
    assert isinstance(b, hotkey.HotkeyBackend)
    assert hasattr(b, "pressed")


def test_win_backend_constructs_without_windows(monkeypatch):
    """Constructing (NOT registering) must never touch ctypes.windll —
    the factory runs at app startup on every platform under test."""
    from wondershot import hotkey
    b = hotkey.WinHotkeyBackend()
    assert b.active is False


def test_win_hotkey_constants():
    """The documented default binding: Ctrl+Shift+PrintScreen."""
    from wondershot import hotkey
    assert hotkey.MOD_CONTROL == 0x0002
    assert hotkey.MOD_SHIFT == 0x0004
    assert hotkey.MOD_NOREPEAT == 0x4000
    assert hotkey.VK_SNAPSHOT == 0x2C
    assert hotkey.WM_HOTKEY == 0x0312


def test_null_backend_register_is_inert():
    from wondershot import hotkey
    b = hotkey.NullHotkeyBackend()
    assert b.register() is False
    assert b.active is False
    assert hasattr(b, "pressed")  # the signal every backend must expose


def test_base_register_is_abstract():
    from wondershot import hotkey
    with pytest.raises(NotImplementedError):
        hotkey.HotkeyBackend().register()
