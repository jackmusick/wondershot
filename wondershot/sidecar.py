"""Sidecar persistence for library images — pure file plumbing, no widgets.

Layout, per image `<dir>/<name>` (name keeps its extension so shot.png
and shot.jpg never collide):

    <dir>/.wondershot/<name>.json          format-versioned document
    <dir>/.wondershot/<name>.base.<N>.png  base-image stack, N=0 = original
                                           capture, highest N = current base

The JSON document: {"version": 1, "bases": N, "items": [...],
"effects": {...}}. `items` are the serialized annotation objects
(items.item_from_dict rebuilds them); `effects` is a write-only record
of the output-effect settings at save time. Unknown versions load as
None so older builds fall back to opening the flattened PNG.
"""

from __future__ import annotations

import glob as _glob
import json
import os

FORMAT_VERSION = 1
SIDECAR_DIRNAME = ".wondershot"


def sidecar_dir(image_path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(image_path)),
                        SIDECAR_DIRNAME)


def sidecar_path(image_path: str) -> str:
    return os.path.join(sidecar_dir(image_path),
                        os.path.basename(image_path) + ".json")


def base_path(image_path: str, n: int) -> str:
    return os.path.join(sidecar_dir(image_path),
                        f"{os.path.basename(image_path)}.base.{n}.png")


def is_library_file(path: str | None, settings) -> bool:
    """True when `path` sits directly in a watched library folder.

    Library files autosave with no prompts and get sidecars; anything
    else (e.g. `wondershot -e /random/file.png`) keeps the save prompt.
    """
    if not path or settings is None:
        return False
    dirs = [getattr(settings, "library_dir", "") or ""]
    dirs += list(getattr(settings, "extra_dirs", []) or [])
    parent = os.path.dirname(os.path.abspath(path))
    return any(d and os.path.abspath(d) == parent for d in dirs)


def load(image_path: str) -> dict | None:
    """Parsed sidecar document, or None (missing / corrupt / future
    version) — None means 'open the flattened PNG as before'."""
    try:
        with open(sidecar_path(image_path), encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != FORMAT_VERSION:
        return None
    return data


def save(image_path: str, data: dict) -> bool:
    """Atomic JSON write (tmp + replace): a crash mid-save never leaves a
    truncated sidecar next to a good flattened PNG."""
    target = sidecar_path(image_path)
    try:
        os.makedirs(sidecar_dir(image_path), exist_ok=True)
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, target)
        return True
    except OSError:
        return False


def _base_glob(image_path: str) -> str:
    return os.path.join(
        sidecar_dir(image_path),
        _glob.escape(os.path.basename(image_path)) + ".base.*.png")


def related_files(image_path: str) -> list[str]:
    """Every sidecar file that belongs to image_path (JSON + bases) —
    what trash/rename must carry along with the image."""
    out = []
    sp = sidecar_path(image_path)
    if os.path.exists(sp):
        out.append(sp)
    out.extend(sorted(_glob.glob(_base_glob(image_path))))
    return out


def rename_files(old_image: str, new_image: str) -> None:
    """Follow an image rename: move the JSON and re-number-free base files
    to the new name. No-op when there is nothing to move."""
    if not related_files(old_image):
        return
    os.makedirs(sidecar_dir(new_image), exist_ok=True)
    old_sp = sidecar_path(old_image)
    if os.path.exists(old_sp):
        os.replace(old_sp, sidecar_path(new_image))
    for f in _glob.glob(_base_glob(old_image)):
        n = int(f.rsplit(".base.", 1)[1][:-len(".png")])
        os.replace(f, base_path(new_image, n))
