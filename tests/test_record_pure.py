"""Pure-function unit tests for the in-process recorder.

No Gst, no portal, no I/O — these run on every platform.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from wondershot.record import (
    build_pipeline_description, elapsed_seconds, format_elapsed,
    pts_offset_ns, crop_props, halo_geometry,
)


# -- build_pipeline_description ------------------------------------------------

def test_description_has_verbatim_no_pts_fix():
    desc = build_pipeline_description(5, 7, "/t.mp4", mic_enabled=False)
    assert "videorate ! video/x-raw,format=I420,framerate=30/1" in desc
    assert "x264enc speed-preset=veryfast tune=zerolatency" in desc
    assert "mp4mux name=mux ! filesink location=/t.mp4" in desc
    assert "identity name=pause" in desc  # C1 tap, raw side


def test_description_pause_tap_precedes_encoder():
    desc = build_pipeline_description(5, 7, "/t.mp4", mic_enabled=False)
    assert desc.index("identity name=pause") < desc.index("x264enc")


def test_description_no_crop_no_halo_by_default():
    desc = build_pipeline_description(5, 7, "/t.mp4", mic_enabled=False)
    assert "videocrop" not in desc
    assert "cairooverlay" not in desc


def test_description_includes_audio_when_mic_enabled():
    desc = build_pipeline_description(5, 7, "/t.mp4", mic_enabled=True)
    assert "pulsesrc" in desc and "avenc_aac" in desc


def test_description_webrtcdsp_only_when_available():
    on = build_pipeline_description(5, 7, "/t.mp4", mic_enabled=True,
                                    noise_suppression=True, have_webrtcdsp=True)
    off = build_pipeline_description(5, 7, "/t.mp4", mic_enabled=True,
                                     noise_suppression=True,
                                     have_webrtcdsp=False)
    assert "webrtcdsp" in on
    assert "webrtcdsp" not in off


# -- crop (D1) -----------------------------------------------------------------

def test_crop_props_centred_rect_symmetric_borders():
    p = crop_props((100, 100, 200, 200), 400, 400)
    assert p == {"left": 100, "top": 100, "right": 100, "bottom": 100}


def test_crop_props_full_frame_all_zeros():
    p = crop_props((0, 0, 640, 480), 640, 480)
    assert p == {"left": 0, "top": 0, "right": 0, "bottom": 0}


def test_crop_props_over_edge_clamps_to_zero():
    p = crop_props((-10, -10, 700, 700), 640, 480)
    assert p == {"left": 0, "top": 0, "right": 0, "bottom": 0}


def test_description_with_crop_inserts_videocrop():
    crop = {"left": 10, "top": 20, "right": 30, "bottom": 40}
    desc = build_pipeline_description(5, 7, "/t.mp4", mic_enabled=False,
                                      crop=crop)
    assert "videocrop top=20 left=10 right=30 bottom=40" in desc
    # crop sits before videorate/encoder
    assert desc.index("videocrop") < desc.index("videorate")


# -- halo (B2) -----------------------------------------------------------------

def test_halo_geometry_centre_passes_through():
    assert halo_geometry(100, 80, 640, 480) == (100, 80, 24)


def test_halo_geometry_out_of_bounds_clamps_to_edges():
    assert halo_geometry(9999, 9999, 640, 480) == (640, 480, 24)


def test_halo_geometry_negative_clamps_to_zero():
    assert halo_geometry(-5, -5, 640, 480) == (0, 0, 24)


def test_description_with_halo_inserts_cairooverlay():
    desc = build_pipeline_description(5, 7, "/t.mp4", mic_enabled=False,
                                      halo=True)
    assert "cairooverlay name=halo" in desc
    assert desc.index("cairooverlay") < desc.index("x264enc")


def test_halo_sets_cursor_mode_metadata():
    """With halo on, SelectSources must request cursor_mode=4 (METADATA)."""
    from tests.test_record import FakeSettings
    from wondershot.record import ScreenRecorder
    rec = ScreenRecorder(FakeSettings("/tmp"))
    rec._halo = True
    captured = {}

    def fake_call(method, args):
        if method == "SelectSources":
            _session, options = args.unpack()
            captured["cursor_mode"] = options["cursor_mode"]

    rec._call = fake_call
    rec._on_request = lambda token, cb: None
    rec._restore_token = lambda: ""
    rec._created({"session_handle": "/s"})
    assert captured["cursor_mode"] == 4


def test_no_halo_keeps_cursor_mode_embedded():
    from tests.test_record import FakeSettings
    from wondershot.record import ScreenRecorder
    rec = ScreenRecorder(FakeSettings("/tmp"))
    rec._halo = False
    captured = {}
    rec._call = lambda m, a: captured.update(
        {"cursor_mode": a.unpack()[1]["cursor_mode"]}
        if m == "SelectSources" else {})
    rec._on_request = lambda token, cb: None
    rec._restore_token = lambda: ""
    rec._created({"session_handle": "/s"})
    assert captured["cursor_mode"] == 2


# -- clock + pts (C1) ----------------------------------------------------------

def test_elapsed_seconds_excludes_paused_span():
    # started at 0, now 100, paused 30s total -> 70 live
    assert elapsed_seconds(0, 100, paused_total=30.0) == 70.0


def test_elapsed_seconds_subtracts_active_pause():
    # paused_at=90, now=100 -> 10s of in-flight pause also excluded
    assert elapsed_seconds(0, 100, paused_total=0.0, paused_at=90) == 90.0


def test_elapsed_seconds_none_start_is_zero():
    assert elapsed_seconds(None, 100) == 0.0


def test_format_elapsed():
    assert format_elapsed(65) == "1:05"
    assert format_elapsed(0) == "0:00"
    assert format_elapsed(600) == "10:00"


def test_pts_offset_ns():
    assert pts_offset_ns(0) == 0
    assert pts_offset_ns(2.5) == 2_500_000_000
