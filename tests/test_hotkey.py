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


@pytest.mark.parametrize("platform", ["win32", "darwin"])
def test_factory_picks_null_elsewhere(monkeypatch, platform):
    from wondershot import hotkey
    monkeypatch.setattr(sys, "platform", platform)
    b = hotkey.create_hotkey_backend()
    assert isinstance(b, hotkey.NullHotkeyBackend)


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
