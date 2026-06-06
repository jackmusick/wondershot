import datetime as dt

from wondershot.gallery import _timestamp_labels


def _mtime(y, mo, d, h, mi):
    return dt.datetime(y, mo, d, h, mi).timestamp()


def test_timestamp_labels_today():
    now = dt.datetime.now()
    date_s, _ = _timestamp_labels(now.timestamp())
    assert date_s == "Today"


def test_timestamp_labels_past_date():
    date_s, time_s = _timestamp_labels(_mtime(2026, 1, 1, 12, 3))
    assert date_s == "01/01/2026"
    assert time_s == "12:03PM"


def test_timestamp_labels_strips_leading_zero_hour():
    _, time_s = _timestamp_labels(_mtime(2026, 1, 1, 9, 5))
    assert time_s == "9:05AM"
