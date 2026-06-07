"""Sidecar file plumbing: paths, atomic JSON, versioning, related files."""
import json
import os

import pytest


def test_paths(tmp_path):
    from wondershot import sidecar
    img = str(tmp_path / "shot.png")
    assert sidecar.sidecar_dir(img) == str(tmp_path / ".wondershot")
    assert sidecar.sidecar_path(img) == str(
        tmp_path / ".wondershot" / "shot.png.json")
    assert sidecar.base_path(img, 0) == str(
        tmp_path / ".wondershot" / "shot.png.base.0.png")
    assert sidecar.base_path(img, 12) == str(
        tmp_path / ".wondershot" / "shot.png.base.12.png")


def test_name_includes_extension_no_stem_collisions(tmp_path):
    from wondershot import sidecar
    a = sidecar.sidecar_path(str(tmp_path / "shot.png"))
    b = sidecar.sidecar_path(str(tmp_path / "shot.jpg"))
    assert a != b


def test_save_load_roundtrip(tmp_path):
    from wondershot import sidecar
    img = str(tmp_path / "shot.png")
    data = {"version": 1, "bases": 2, "items": [{"type": "rect"}],
            "effects": {}}
    assert sidecar.save(img, data) is True
    assert sidecar.load(img) == data
    # atomic write: no .tmp left behind
    assert not os.path.exists(sidecar.sidecar_path(img) + ".tmp")


def test_load_missing_returns_none(tmp_path):
    from wondershot import sidecar
    assert sidecar.load(str(tmp_path / "nope.png")) is None


def test_load_corrupt_returns_none(tmp_path):
    from wondershot import sidecar
    img = str(tmp_path / "shot.png")
    os.makedirs(sidecar.sidecar_dir(img))
    with open(sidecar.sidecar_path(img), "w") as f:
        f.write("{not json")
    assert sidecar.load(img) is None


def test_future_version_returns_none(tmp_path):
    """Unknown format -> editor must fall back to today's flat open."""
    from wondershot import sidecar
    img = str(tmp_path / "shot.png")
    sidecar.save(img, {"version": 1, "bases": 1, "items": []})
    raw = json.load(open(sidecar.sidecar_path(img)))
    raw["version"] = 99
    with open(sidecar.sidecar_path(img), "w") as f:
        json.dump(raw, f)
    assert sidecar.load(img) is None


def test_is_library_file(tmp_path):
    from wondershot import sidecar

    class S:
        library_dir = str(tmp_path / "lib")
        extra_dirs = [str(tmp_path / "extra")]

    os.makedirs(S.library_dir)
    os.makedirs(S.extra_dirs[0])
    assert sidecar.is_library_file(str(tmp_path / "lib" / "a.png"), S())
    assert sidecar.is_library_file(str(tmp_path / "extra" / "b.png"), S())
    assert not sidecar.is_library_file(str(tmp_path / "other.png"), S())
    assert not sidecar.is_library_file("", S())
    assert not sidecar.is_library_file(None, S())
    assert not sidecar.is_library_file(str(tmp_path / "lib" / "a.png"),
                                       None)


def test_related_files(tmp_path):
    from wondershot import sidecar
    img = str(tmp_path / "shot.png")
    assert sidecar.related_files(img) == []
    sidecar.save(img, {"version": 1, "bases": 2, "items": []})
    for n in (0, 1):
        with open(sidecar.base_path(img, n), "wb") as f:
            f.write(b"png")
    # a neighbor's files must NOT be picked up
    sidecar.save(str(tmp_path / "other.png"), {"version": 1, "bases": 1,
                                               "items": []})
    rel = sidecar.related_files(img)
    assert sidecar.sidecar_path(img) in rel
    assert sidecar.base_path(img, 0) in rel
    assert sidecar.base_path(img, 1) in rel
    assert len(rel) == 3


def test_rename_files(tmp_path):
    from wondershot import sidecar
    old = str(tmp_path / "old.png")
    new = str(tmp_path / "new name.png")  # spaces must survive globbing
    sidecar.save(old, {"version": 1, "bases": 1, "items": []})
    with open(sidecar.base_path(old, 0), "wb") as f:
        f.write(b"png")
    sidecar.rename_files(old, new)
    assert sidecar.related_files(old) == []
    assert os.path.exists(sidecar.sidecar_path(new))
    assert os.path.exists(sidecar.base_path(new, 0))


def test_rename_files_noop_without_sidecar(tmp_path):
    from wondershot import sidecar
    sidecar.rename_files(str(tmp_path / "a.png"), str(tmp_path / "b.png"))
    # must not raise, must not create the dir
    assert not os.path.isdir(sidecar.sidecar_dir(str(tmp_path / "a.png")))
