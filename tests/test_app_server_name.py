# tests/test_app_server_name.py
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_server_name_with_getuid():
    from wondershot.app import server_name
    if hasattr(os, "getuid"):
        assert server_name() == f"wondershot-{os.getuid()}"


def test_server_name_without_getuid(monkeypatch):
    """Windows has no os.getuid; startup must not crash (app.py:23)."""
    from wondershot.app import server_name
    monkeypatch.delattr(os, "getuid", raising=False)
    monkeypatch.setenv("USERNAME", "developer")
    name = server_name()
    assert name == "wondershot-developer"
