import subprocess

import pytest

from wondershot import ffmpegutil


@pytest.fixture(autouse=True)
def fresh_cache():
    ffmpegutil.reset_cache()
    yield
    ffmpegutil.reset_cache()


def test_ffmpeg_path_found(monkeypatch):
    monkeypatch.setattr(
        "shutil.which",
        lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    assert ffmpegutil.ffmpeg_path() == "/usr/bin/ffmpeg"


def test_ffmpeg_path_missing_raises_clear_error(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    with pytest.raises(ffmpegutil.FfmpegMissing) as exc:
        ffmpegutil.ffmpeg_path()
    msg = str(exc.value)
    assert "ffmpeg" in msg
    assert "PATH" in msg
    assert "Install" in msg


def test_have_ffmpeg_false_then_true(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert ffmpegutil.have_ffmpeg() is False
    ffmpegutil.reset_cache()
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffmpeg")
    assert ffmpegutil.have_ffmpeg() is True


def test_path_is_cached_after_first_hit(monkeypatch):
    calls = []

    def which(name):
        calls.append(name)
        return "/usr/bin/ffmpeg"

    monkeypatch.setattr("shutil.which", which)
    ffmpegutil.ffmpeg_path()
    ffmpegutil.ffmpeg_path()
    assert calls == ["ffmpeg"]


def test_run_ffmpeg_prepends_binary(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ffmpeg")
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"] = argv
        seen["timeout"] = kw.get("timeout")
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    r = ffmpegutil.run_ffmpeg(["-hide_banner", "-encoders"], timeout=10)
    assert seen["argv"] == ["/usr/bin/ffmpeg", "-hide_banner", "-encoders"]
    assert seen["timeout"] == 10
    assert r.returncode == 0
