import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QGuiApplication, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class _Settings:
    quick_bar_enabled = True
    quick_bar_timeout = 8


@pytest.fixture
def shot(tmp_path):
    img = QImage(120, 80, QImage.Format_RGB32)
    img.fill(Qt.darkCyan)
    p = str(tmp_path / "shot.png")
    img.save(p)
    return p


def _bar(shot):
    from wondershot.capture_window import QuickActionBar
    return QuickActionBar(_Settings(), shot)


def test_signals_carry_path_and_dismiss(qapp, shot):
    bar = _bar(shot)
    got = {}
    bar.edit_requested.connect(lambda p: got.setdefault("edit", p))
    bar.share_requested.connect(lambda p: got.setdefault("share", p))
    bar.trash_requested.connect(lambda p: got.setdefault("trash", p))
    dismissed = []
    bar.dismissed.connect(lambda: dismissed.append(1))
    bar.edit_btn.click()
    assert got["edit"] == shot
    assert dismissed  # acting on the file also dismisses the bar
    bar2 = _bar(shot)
    bar2.share_requested.connect(lambda p: got.setdefault("share", p))
    bar2.share_btn.click()
    assert got["share"] == shot
    bar3 = _bar(shot)
    bar3.trash_requested.connect(lambda p: got.setdefault("trash", p))
    bar3.trash_btn.click()
    assert got["trash"] == shot


def test_copy_puts_image_on_clipboard(qapp, shot):
    QGuiApplication.clipboard().clear()
    bar = _bar(shot)
    bar.copy_btn.click()
    assert not QGuiApplication.clipboard().image().isNull()


def test_escape_dismisses(qapp, shot):
    bar = _bar(shot)
    dismissed = []
    bar.dismissed.connect(lambda: dismissed.append(1))
    QTest.keyClick(bar, Qt.Key_Escape)
    assert dismissed


def test_timer_uses_setting_and_starts_on_show(qapp, shot):
    s = _Settings()
    s.quick_bar_timeout = 3
    from wondershot.capture_window import QuickActionBar
    bar = QuickActionBar(s, shot)
    assert bar._timer.interval() == 3000
    assert not bar._timer.isActive()
    bar.show()
    assert bar._timer.isActive()
    bar.close()


def test_thumbnail_loaded(qapp, shot):
    bar = _bar(shot)
    assert bar.thumb.pixmap() is not None
    assert not bar.thumb.pixmap().isNull()


def test_rule_position_bottom_center():
    from wondershot.capture_window import quickbar_rule_position
    avail = QRect(0, 0, 1920, 1080)
    x, y = quickbar_rule_position(avail, bar_w=480, bar_h=110)
    assert x == (1920 - 480) // 2
    assert y == 1080 - 110 - 96  # generous taskbar clearance, bubble precedent
    # multi-monitor: a screen whose origin isn't 0,0
    avail2 = QRect(1920, 0, 2560, 1440)
    x2, y2 = quickbar_rule_position(avail2, bar_w=480, bar_h=110)
    assert x2 == 1920 + (2560 - 480) // 2
    assert y2 == 1440 - 110 - 96
