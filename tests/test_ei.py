"""EI receive-path state machine against a fake 'lib' (the feasible
analogue of a fake socket: the wire parsing is C's job inside libei;
what we own — and test — is the handshake/event handling around it).

The wrapper passes ctypes-wrapped args to variadic/pointer calls, so
the fake unwraps `.value` where needed."""
import ctypes

import pytest

from wondershot.ei import (
    EI_DEVICE_CAP_BUTTON,
    EI_DEVICE_CAP_POINTER,
    EI_EVENT_BUTTON_BUTTON,
    EI_EVENT_CONNECT,
    EI_EVENT_DEVICE_ADDED,
    EI_EVENT_DEVICE_RESUMED,
    EI_EVENT_DISCONNECT,
    EI_EVENT_SEAT_ADDED,
    ButtonEvent,
    EiButtonReader,
)


class FakeLib:
    """Scripted libei: hands out the queued events once, records what
    the wrapper does (binds, unrefs)."""

    def __init__(self, events=(), setup_rc=0):
        self._events = list(events)  # (type, payload dict) per event
        self._handed = 0
        self._setup_rc = setup_rc
        self.bound = []        # (seat, [vararg values]) per bind call
        self.unreffed = []     # event handles released
        self.ctx_unreffed = 0
        self.dispatch_calls = 0
        self.backend_fd = None
        self.name = None

    # context ---------------------------------------------------------
    def ei_new_receiver(self, user_data):
        return 0xC0FFEE

    def ei_configure_name(self, ctx, name):
        self.name = name

    def ei_setup_backend_fd(self, ctx, fd):
        self.backend_fd = fd
        return self._setup_rc

    def ei_get_fd(self, ctx):
        return 99

    def ei_unref(self, ctx):
        self.ctx_unreffed += 1

    # event pump ------------------------------------------------------
    def ei_dispatch(self, ctx):
        self.dispatch_calls += 1

    def ei_get_event(self, ctx):
        if self._handed >= len(self._events):
            return None
        self._handed += 1
        return self._handed  # handle = 1-based index into the script

    def _ev(self, handle):
        return self._events[handle - 1]

    def ei_event_get_type(self, h):
        return self._ev(h)[0]

    def ei_event_get_seat(self, h):
        return self._ev(h)[1]["seat"]

    def ei_event_get_time(self, h):
        return self._ev(h)[1]["time"]

    def ei_event_button_get_button(self, h):
        return self._ev(h)[1]["button"]

    def ei_event_button_get_is_press(self, h):
        return self._ev(h)[1]["press"]

    def ei_event_unref(self, h):
        self.unreffed.append(h)

    # seat ------------------------------------------------------------
    def ei_seat_bind_capabilities(self, seat, *varargs):
        self.bound.append((seat.value,
                           [a.value for a in varargs]))


def test_setup_wires_fd_and_name():
    lib = FakeLib()
    r = EiButtonReader(7, name=b"ws-probe", lib=lib)
    assert lib.backend_fd == 7
    assert lib.name == b"ws-probe"
    assert r.fd == 99


def test_setup_failure_raises_and_unrefs():
    lib = FakeLib(setup_rc=-22)
    with pytest.raises(OSError):
        EiButtonReader(7, lib=lib)
    assert lib.ctx_unreffed == 1


def test_handshake_binds_pointer_and_button_with_null_sentinel():
    lib = FakeLib(events=[
        (EI_EVENT_CONNECT, {}),
        (EI_EVENT_SEAT_ADDED, {"seat": 0xBEEF}),
    ])
    r = EiButtonReader(7, lib=lib)
    assert r.dispatch() == []
    assert r.connected
    assert len(lib.bound) == 1
    seat, args = lib.bound[0]
    assert seat == 0xBEEF
    assert args[:-1] == [EI_DEVICE_CAP_POINTER, EI_DEVICE_CAP_BUTTON]
    assert args[-1] is None  # NULL sentinel (variadic terminator)


def test_button_events_decode_with_timestamps():
    lib = FakeLib(events=[
        (EI_EVENT_CONNECT, {}),
        (EI_EVENT_SEAT_ADDED, {"seat": 1}),
        (EI_EVENT_DEVICE_ADDED, {}),
        (EI_EVENT_DEVICE_RESUMED, {}),
        (EI_EVENT_BUTTON_BUTTON,
         {"time": 1111, "button": 0x110, "press": True}),
        (EI_EVENT_BUTTON_BUTTON,
         {"time": 2222, "button": 0x110, "press": False}),
    ])
    r = EiButtonReader(7, lib=lib)
    events = r.dispatch()
    assert events == [
        ButtonEvent(time_us=1111, button=0x110, is_press=True),
        ButtonEvent(time_us=2222, button=0x110, is_press=False),
    ]


def test_every_event_handle_is_released():
    lib = FakeLib(events=[
        (EI_EVENT_CONNECT, {}),
        (EI_EVENT_SEAT_ADDED, {"seat": 1}),
        (EI_EVENT_BUTTON_BUTTON,
         {"time": 1, "button": 0x110, "press": True}),
    ])
    r = EiButtonReader(7, lib=lib)
    r.dispatch()
    assert lib.unreffed == [1, 2, 3]


def test_disconnect_sets_flag():
    lib = FakeLib(events=[(EI_EVENT_DISCONNECT, {})])
    r = EiButtonReader(7, lib=lib)
    r.dispatch()
    assert r.disconnected


def test_close_unrefs_context_once():
    lib = FakeLib()
    r = EiButtonReader(7, lib=lib)
    r.close()
    r.close()
    assert lib.ctx_unreffed == 1


def test_open_libei_loads_real_library_if_present():
    # Integration smoke: only meaningful where libei is installed
    # (Jack's Fedora box has libei-1.5.0). Skipped elsewhere.
    from wondershot.ei import open_libei
    try:
        lib = open_libei()
    except OSError:
        pytest.skip("libei.so.1 not installed on this box")
    for sym in ("ei_new_receiver", "ei_setup_backend_fd", "ei_dispatch",
                "ei_get_event", "ei_event_get_type", "ei_event_unref",
                "ei_seat_bind_capabilities", "ei_unref"):
        assert getattr(lib, sym) is not None
