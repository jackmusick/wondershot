import os

import pytest

# Scroll-stitch is gated on numpy at runtime (scroll_capture_available);
# bare CI runners don't have the spike extra — skip, don't error.
np = pytest.importorskip("numpy")

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QImage


@pytest.fixture(scope="session", autouse=True)
def qapp():
    from PySide6.QtGui import QGuiApplication
    app = QGuiApplication.instance() or QGuiApplication([])
    yield app


def make_rgb(height=60, width=40, seed=7) -> np.ndarray:
    """Deterministic noise image: every row is unique."""
    rng = np.random.default_rng(seed)
    return rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)


def to_gray_noise(height, width, seed):
    from wondershot.stitch import to_gray
    return to_gray(make_rgb(height, width, seed))


def test_rgb_qimage_roundtrip_exact():
    from wondershot.stitch import qimage_to_rgb, rgb_to_qimage
    arr = make_rgb()
    img = rgb_to_qimage(arr)
    assert img.width() == 40 and img.height() == 60
    assert img.format() == QImage.Format_RGB888
    back = qimage_to_rgb(img)
    assert np.array_equal(arr, back)


def test_qimage_to_rgb_handles_other_formats():
    """Real frames arrive as RGB32/ARGB32 from the appsink; conversion
    must normalize any input format to (H, W, 3) RGB."""
    from wondershot.stitch import qimage_to_rgb
    img = QImage(10, 8, QImage.Format_ARGB32_Premultiplied)
    img.fill(0xFF336699)  # opaque RGB(0x33, 0x66, 0x99)
    arr = qimage_to_rgb(img)
    assert arr.shape == (8, 10, 3)
    assert tuple(arr[0, 0]) == (0x33, 0x66, 0x99)


def test_to_gray_shape_and_range():
    from wondershot.stitch import to_gray
    arr = make_rgb()
    g = to_gray(arr)
    assert g.shape == (60, 40)
    assert g.dtype == np.float32
    assert 0.0 <= g.min() and g.max() <= 255.0


def test_detect_offset_finds_scroll():
    """cur is prev scrolled up by d rows: cur[y] == prev[y + d]."""
    from wondershot.stitch import detect_offset, to_gray
    tall = make_rgb(height=300, width=40, seed=1)
    prev = to_gray(tall[0:200])
    for d in (1, 17, 60, 130):
        cur = to_gray(tall[d:200 + d])
        got, conf = detect_offset(prev, cur)
        assert got == d
        assert conf >= 0.5


def test_detect_offset_identical_frames_is_zero():
    from wondershot.stitch import detect_offset, to_gray
    g = to_gray(make_rgb(height=200, width=40, seed=2))
    got, conf = detect_offset(g, g)
    assert got == 0
    assert conf >= 0.5


def test_detect_offset_unrelated_frames_is_none():
    """A scene change (different window content) must not stitch."""
    from wondershot.stitch import detect_offset, to_gray
    a = to_gray(make_rgb(height=200, width=40, seed=3))
    b = to_gray(make_rgb(height=200, width=40, seed=4))
    assert detect_offset(a, b) == (None, 0.0)


def test_textured_xs_skips_flat_bands():
    """Band x-positions must come from textured columns only."""
    from wondershot.stitch import textured_xs
    strip = np.zeros((64, 300), dtype=np.float32)   # flat everywhere
    strip[:, 100:148] = make_rgb(64, 48, seed=20).mean(axis=2)
    xs = textured_xs(strip, band_w=48, n=5, var_min=100.0)
    # linspace(0, 252, 5) -> [0, 63, 126, 189, 252]; x=126 sits inside
    # the textured block and x=63 overlaps it by 11 columns (mixture
    # variance ~3000, still >= var_min) — both may survive; x=0, 189,
    # 252 are fully flat and must not.
    assert xs
    assert all(60 <= x <= 148 for x in xs)


def test_textured_xs_narrow_image_uses_single_band():
    from wondershot.stitch import textured_xs
    strip = to_gray_noise(64, 40, seed=21)
    assert textured_xs(strip, band_w=48, n=5, var_min=100.0) == [0]


def test_detect_offset_blank_frame_is_low_confidence():
    """A featureless frame must not produce a confident offset.
    (v1's documented limitation was uniform-band false matches; v2
    must refuse outright: no textured bands survive var_min, and the
    full-overlap fallback against a noise prev can't beat threshold/2.)"""
    from wondershot.stitch import detect_offset, to_gray
    prev = to_gray(make_rgb(height=200, width=120, seed=22))
    blank = np.full((200, 120), 255.0, dtype=np.float32)
    d, conf = detect_offset(prev, blank)
    assert d is None
    assert conf == 0.0


def test_detect_offset_wide_frame_multiband_consensus():
    """Wide noise: all 5 bands textured, all agree -> confidence 1.0."""
    from wondershot.stitch import detect_offset, to_gray
    tall = make_rgb(height=400, width=300, seed=23)
    prev = to_gray(tall[0:250])
    cur = to_gray(tall[37:287])
    assert detect_offset(prev, cur) == (37, 1.0)


def _frame_with_chrome(content: np.ndarray, header: np.ndarray,
                       footer: np.ndarray) -> np.ndarray:
    return np.vstack([header, content, footer])


def test_static_bands_detects_header_and_footer():
    from wondershot.stitch import static_bands, to_gray
    tall = make_rgb(height=400, width=40, seed=5)
    header = make_rgb(height=15, width=40, seed=6)
    footer = make_rgb(height=25, width=40, seed=7)
    prev = to_gray(_frame_with_chrome(tall[0:200], header, footer))
    cur = to_gray(_frame_with_chrome(tall[50:250], header, footer))
    assert static_bands(prev, cur) == (15, 25)


def test_static_bands_none_when_everything_scrolls():
    from wondershot.stitch import static_bands, to_gray
    tall = make_rgb(height=400, width=40, seed=8)
    prev = to_gray(tall[0:200])
    cur = to_gray(tall[50:250])
    assert static_bands(prev, cur) == (0, 0)


def test_static_bands_identical_frames_returns_zero():
    """Whole frame 'static' is meaningless — refuse, don't crop all."""
    from wondershot.stitch import static_bands, to_gray
    g = to_gray(make_rgb(height=200, width=40, seed=9))
    assert static_bands(g, g) == (0, 0)


def _window_frames(tall: np.ndarray, viewport: int, offsets):
    """Simulate a user scrolling: viewport-sized windows of a tall page."""
    from wondershot.stitch import rgb_to_qimage
    return [rgb_to_qimage(tall[o:o + viewport]) for o in offsets]


def test_stitcher_reconstructs_tall_image():
    from wondershot.stitch import ScrollStitcher, qimage_to_rgb
    tall = make_rgb(height=900, width=120, seed=10)
    offsets = [0, 30, 60, 95, 140, 200, 260, 300]
    st = ScrollStitcher()
    for f in _window_frames(tall, viewport=200, offsets=offsets):
        st.add_frame(f)
    out = qimage_to_rgb(st.result())
    expected = tall[0:offsets[-1] + 200]   # rows 0..500
    assert out.shape == expected.shape
    assert np.array_equal(out, expected)
    assert st.frames_used == len(offsets)


def test_stitcher_drops_no_motion_frames():
    from wondershot.stitch import ScrollStitcher, qimage_to_rgb
    tall = make_rgb(height=600, width=80, seed=11)
    frames = _window_frames(tall, 200, [0, 0, 40, 40, 40, 80])
    st = ScrollStitcher()
    for f in frames:
        st.add_frame(f)
    out = qimage_to_rgb(st.result())
    assert np.array_equal(out, tall[0:280])
    assert st.frames_dropped == 3


def test_stitcher_strips_fixed_header_and_footer():
    from wondershot.stitch import ScrollStitcher, qimage_to_rgb, rgb_to_qimage
    tall = make_rgb(height=700, width=100, seed=12)
    header = make_rgb(height=18, width=100, seed=13)
    footer = make_rgb(height=22, width=100, seed=14)
    st = ScrollStitcher()
    for o in [0, 35, 70, 110]:
        st.add_frame(rgb_to_qimage(
            _frame_with_chrome(tall[o:o + 160], header, footer)))
    out = qimage_to_rgb(st.result())
    assert np.array_equal(out, tall[0:110 + 160])


def test_stitcher_single_frame_passthrough():
    from wondershot.stitch import ScrollStitcher, qimage_to_rgb, rgb_to_qimage
    arr = make_rgb(height=150, width=60, seed=15)
    st = ScrollStitcher()
    st.add_frame(rgb_to_qimage(arr))
    assert np.array_equal(qimage_to_rgb(st.result()), arr)


def test_stitcher_empty_result_is_null_image():
    from wondershot.stitch import ScrollStitcher
    assert ScrollStitcher().result().isNull()


def test_stitcher_scene_change_does_not_append_garbage():
    """detect_offset -> None must not vstack unrelated content."""
    from wondershot.stitch import ScrollStitcher, qimage_to_rgb, rgb_to_qimage
    a = make_rgb(height=200, width=60, seed=16)
    b = make_rgb(height=200, width=60, seed=17)
    st = ScrollStitcher()
    st.add_frame(rgb_to_qimage(a))
    st.add_frame(rgb_to_qimage(b))
    assert np.array_equal(qimage_to_rgb(st.result()), a)
    assert st.frames_dropped == 1


def test_stitcher_drops_low_confidence_frames():
    """min_confidence above what detect_offset can ever report (1.0
    is the max) forces every moving pair onto the drop path — the
    canvas must stay at frame 0 rather than risk a misaligned seam."""
    from wondershot.stitch import ScrollStitcher, qimage_to_rgb
    tall = make_rgb(height=600, width=80, seed=30)
    st = ScrollStitcher(min_confidence=1.1)
    for f in _window_frames(tall, 200, [0, 40, 80]):
        st.add_frame(f)
    assert np.array_equal(qimage_to_rgb(st.result()), tall[0:200])
    assert st.frames_used == 1
    assert st.frames_dropped == 2


def test_stitcher_matches_against_last_stitched_frame():
    """A dropped frame (here: unrelated content) must not become the
    match reference — the next clean frame re-matches against the
    last STITCHED frame, so the canvas stays gap-free. Under v1's
    'always resync' the clean frame would match the garbage frame
    and be dropped (or worse, mis-appended)."""
    from wondershot.stitch import ScrollStitcher, qimage_to_rgb, rgb_to_qimage
    tall = make_rgb(height=600, width=80, seed=31)
    garbage = make_rgb(height=200, width=80, seed=32)
    st = ScrollStitcher()
    st.add_frame(rgb_to_qimage(tall[0:200]))
    st.add_frame(rgb_to_qimage(garbage))          # dropped: no match
    st.add_frame(rgb_to_qimage(tall[60:260]))     # must still stitch
    out = qimage_to_rgb(st.result())
    assert np.array_equal(out, tall[0:260])
    assert st.frames_used == 2
    assert st.frames_dropped == 1


# -- realistic fixtures: QPainter text-like pages (stitch v2 bar) ----------

def render_text_page(height=1400, width=420, seed=3):
    """Text-like page: rows of varying-width rounded rects (words),
    margins, occasional paragraph gaps. Returns (H, W, 3) uint8."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter
    from wondershot.stitch import qimage_to_rgb
    rng = np.random.default_rng(seed)
    img = QImage(width, height, QImage.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    y = 18
    while y < height - 24:
        x = 28
        while x < width - 80:
            w = int(rng.integers(18, 70))
            shade = int(rng.integers(40, 90))
            p.setBrush(QColor(shade, shade, shade))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(x, y, w, 11), 3, 3)
            x += w + 9
        y += 19 if rng.random() > 0.15 else 34  # paragraph gaps
    p.end()
    return qimage_to_rgb(img)


def viewport_at(page: np.ndarray, y: float, vh: int) -> np.ndarray:
    """Viewport sampled at a (possibly fractional) offset via linear
    row interpolation — what a compositor mid-smooth-scroll shows.
    QPainter cannot do this: unscaled image blits snap to integer
    positions even with SmoothPixmapTransform (measured)."""
    i = int(np.floor(y))
    f = float(y) - i
    if f == 0.0:
        return page[i:i + vh].copy()
    a = page[i:i + vh].astype(np.float32)
    b = page[i + 1:i + 1 + vh].astype(np.float32)
    return ((1.0 - f) * a + f * b).astype(np.uint8)


def test_textpage_integral_offsets_reconstruct_exactly():
    """Discrete scrolling (wheel clicks, Page Down) lands on integral
    offsets — reconstruction must be pixel-exact on text-like pages."""
    from wondershot.stitch import ScrollStitcher, qimage_to_rgb, rgb_to_qimage
    page = render_text_page()
    offsets = [0, 40, 85, 130, 190, 250, 310]
    st = ScrollStitcher()
    for o in offsets:
        st.add_frame(rgb_to_qimage(viewport_at(page, float(o), 300)))
    out = qimage_to_rgb(st.result())
    expected = page[0:offsets[-1] + 300]
    assert out.shape == expected.shape
    assert np.array_equal(out, expected)
    assert st.frames_used == len(offsets)
    assert st.frames_dropped == 0


def test_textpage_kinetic_fractional_offsets_within_tolerance():
    """Kinetic/smooth scrolling lands frames at fractional offsets;
    integer matching is off by <=1 per seam, so reconstruction can't
    be exact — the bar is mean abs diff < 8.0 against the source page
    and total height within +-2px (prototype measured: diff 1.58,
    height exactly 540, under the last-stitched-reference policy)."""
    from wondershot.stitch import ScrollStitcher, qimage_to_rgb, rgb_to_qimage
    page = render_text_page()
    offsets = [0.0, 28.3, 61.7, 97.2, 133.9, 168.4, 202.0, 239.6]
    st = ScrollStitcher()
    for o in offsets:
        st.add_frame(rgb_to_qimage(viewport_at(page, o, 300)))
    out = qimage_to_rgb(st.result())
    assert st.frames_used == len(offsets)
    expected_h = int(round(offsets[-1])) + 300
    assert abs(out.shape[0] - expected_h) <= 2
    m = min(out.shape[0], expected_h)
    diff = float(np.abs(out[:m].astype(np.float32)
                        - page[:m].astype(np.float32)).mean())
    assert diff < 8.0


def test_textpage_mid_animation_blur_frame_is_dropped():
    """A frame captured mid-kinetic-animation (simulated as a 50/50
    blend of two scroll positions) must be dropped, and the stitch
    must recover on the next clean frame."""
    from wondershot.stitch import ScrollStitcher, qimage_to_rgb, rgb_to_qimage
    page = render_text_page()
    clean = [0.0, 60.2]
    a = viewport_at(page, 100.4, 300).astype(np.float32)
    b = viewport_at(page, 124.9, 300).astype(np.float32)
    blur = ((a + b) / 2).astype(np.uint8)
    st = ScrollStitcher()
    for o in clean:
        st.add_frame(rgb_to_qimage(viewport_at(page, o, 300)))
    st.add_frame(rgb_to_qimage(blur))
    assert st.frames_dropped == 1
    # recovery: a clean frame after the blur still stitches
    st.add_frame(rgb_to_qimage(viewport_at(page, 150.0, 300)))
    assert st.frames_used == 3
    out = qimage_to_rgb(st.result())
    m = min(out.shape[0], 450)
    diff = float(np.abs(out[:m].astype(np.float32)
                        - page[:m].astype(np.float32)).mean())
    assert diff < 8.0


def test_textpage_fixed_header_chrome_cropped_and_exact():
    """A sticky header (window chrome) composited above the scrolling
    viewport must be detected by static_bands and cropped; with
    integral offsets the output must be an exact contiguous slice of
    the page starting at row 0 (prototype: static_bands locks at
    exactly the 30px chrome height for this fixture/these offsets,
    because page row 40 under the header is textured while page row 0
    is margin)."""
    from wondershot.stitch import ScrollStitcher, qimage_to_rgb, rgb_to_qimage
    page = render_text_page()
    chrome = np.full((30, page.shape[1], 3), 200, dtype=np.uint8)
    chrome[10:20, 20:200] = 60   # toolbar-ish texture in the chrome
    st = ScrollStitcher()
    for o in [0, 40, 85, 130, 190]:
        frame = np.vstack([chrome, viewport_at(page, float(o), 300)])
        st.add_frame(rgb_to_qimage(frame))
    out = qimage_to_rgb(st.result())
    assert st.frames_used == 5
    assert np.array_equal(out, page[0:out.shape[0]])
    assert out.shape[0] == 190 + 300


def test_detect_offset_bimodal_votes_is_none_not_crash():
    """A scroll past the overlap window can leave exactly two bands
    voting distant spurious offsets (here 60 and 117). The averaged
    median lands between the clusters, no vote is within tol, and
    _consensus must report no-consensus — not crash on the median of
    an empty inlier list (np.median([]) is NaN; pre-fix this raised
    ValueError out of ScrollStitcher.add_frame)."""
    from wondershot.stitch import detect_offset, to_gray
    page = render_text_page()
    prev = to_gray(page[0:300])
    cur = to_gray(page[280:580])   # 280 > h - band: no true overlap
    assert detect_offset(prev, cur) == (None, 0.0)
