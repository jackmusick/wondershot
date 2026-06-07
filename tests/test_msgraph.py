import json
import os
import time


def test_token_cache_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("WONDERSHOT_DATA_DIR", str(tmp_path))
    from wondershot import msgraph
    assert msgraph.connected_account() == ""
    msgraph.save_tokens({"access_token": "at", "refresh_token": "rt",
                         "expires_in": 3600}, "client", "jack@example.com")
    assert msgraph.connected_account() == "jack@example.com"
    if os.name == "posix":
        assert oct(os.stat(msgraph.token_path()).st_mode & 0o777) == "0o600"
    t = msgraph.load_tokens()
    assert t["refresh_token"] == "rt"
    assert t["expires_at"] > time.time()
    assert msgraph.ensure_access_token() == "at"  # not expired -> cached
    msgraph.disconnect()
    assert msgraph.connected_account() == ""


def test_expired_token_requires_refresh(tmp_path, monkeypatch):
    monkeypatch.setenv("WONDERSHOT_DATA_DIR", str(tmp_path))
    from wondershot import msgraph
    msgraph.save_tokens({"access_token": "old", "expires_in": 0},
                        "client", "x")
    # expires_at is already in the past (60s safety margin)
    calls = {}
    monkeypatch.setattr(msgraph, "_post_form",
                        lambda url, fields: calls.update(fields) or
                        {"access_token": "new", "expires_in": 3600})
    assert msgraph.ensure_access_token() == "new"
    assert calls["grant_type"] == "refresh_token"
