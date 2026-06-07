"""Minimal ctypes binding for the libei RECEIVE path (EI client).

Step capture needs to OBSERVE pointer-button events coming over the
InputCapture portal's EIS fd. snegg (freedesktop's Python libei
binding) is NOT on PyPI (verified 2026-06-07: pypi.org/pypi/snegg/json
returns 404), so this is a hand-rolled binding against the system
libei.so.1 (Fedora package `libei`) covering ONLY what the receive
path needs: receiver context, backend-fd setup, the handshake
(CONNECT / SEAT_ADDED -> bind pointer+button capabilities) and
BUTTON_BUTTON decoding with timestamps. No sender support, no
emulation, no keyboard/touch.

Enum values verified against libei 1.5.0 src/libei.h; every symbol
used here verified exported by `nm -D /usr/lib64/libei.so.1`.

Sole consumer today: spikes/inputcapture_probe.py. The interception-
semantics question (do apps still receive clicks while we observe?)
cannot be answered in code — it is a manual checklist item.

Stdlib-only on purpose (no gi, no Qt): the probe runs under the
SYSTEM python, and unit tests inject a plain-Python fake `lib`.
"""

from __future__ import annotations

import ctypes
import ctypes.util
from dataclasses import dataclass

# enum ei_event_type (libei.h, 1.5.0)
EI_EVENT_CONNECT = 1
EI_EVENT_DISCONNECT = 2
EI_EVENT_SEAT_ADDED = 3
EI_EVENT_SEAT_REMOVED = 4
EI_EVENT_DEVICE_ADDED = 5
EI_EVENT_DEVICE_REMOVED = 6
EI_EVENT_DEVICE_PAUSED = 7
EI_EVENT_DEVICE_RESUMED = 8
EI_EVENT_BUTTON_BUTTON = 500

# enum ei_device_capability (libei.h, 1.5.0)
EI_DEVICE_CAP_POINTER = 1 << 0
EI_DEVICE_CAP_BUTTON = 1 << 5


@dataclass(frozen=True)
class ButtonEvent:
    time_us: int    # microseconds; FRAME-derived, monotonic domain
    button: int     # evdev BTN_* code (BTN_LEFT = 0x110)
    is_press: bool


def open_libei() -> ctypes.CDLL:
    """Load libei.so.1 and declare the receive-path prototypes.

    Raises OSError when the library is not installed."""
    name = ctypes.util.find_library("ei") or "libei.so.1"
    lib = ctypes.CDLL(name)
    p = ctypes.c_void_p
    lib.ei_new_receiver.restype = p
    lib.ei_new_receiver.argtypes = [p]
    lib.ei_configure_name.restype = None
    lib.ei_configure_name.argtypes = [p, ctypes.c_char_p]
    lib.ei_setup_backend_fd.restype = ctypes.c_int
    lib.ei_setup_backend_fd.argtypes = [p, ctypes.c_int]
    lib.ei_get_fd.restype = ctypes.c_int
    lib.ei_get_fd.argtypes = [p]
    lib.ei_dispatch.restype = None
    lib.ei_dispatch.argtypes = [p]
    lib.ei_get_event.restype = p
    lib.ei_get_event.argtypes = [p]
    lib.ei_event_get_type.restype = ctypes.c_int
    lib.ei_event_get_type.argtypes = [p]
    lib.ei_event_get_seat.restype = p
    lib.ei_event_get_seat.argtypes = [p]
    lib.ei_event_get_time.restype = ctypes.c_uint64
    lib.ei_event_get_time.argtypes = [p]
    lib.ei_event_button_get_button.restype = ctypes.c_uint32
    lib.ei_event_button_get_button.argtypes = [p]
    lib.ei_event_button_get_is_press.restype = ctypes.c_bool
    lib.ei_event_button_get_is_press.argtypes = [p]
    lib.ei_event_unref.restype = p
    lib.ei_event_unref.argtypes = [p]
    lib.ei_unref.restype = p
    lib.ei_unref.argtypes = [p]
    # ei_seat_bind_capabilities is VARIADIC with a NULL sentinel —
    # declaring argtypes would break the varargs call; leave it bare
    # and wrap every argument in a ctypes type at the call site.
    lib.ei_seat_bind_capabilities.restype = None
    return lib


class EiButtonReader:
    """RECEIVE-path EI client: handshake + pointer-button events only.

    Drive it from a select() loop: when `.fd` is readable, call
    dispatch(); it returns the ButtonEvents decoded since the last
    call. SEAT_ADDED is answered with a pointer+button capability
    bind (NULL-terminated varargs, per libei's sentinel contract);
    devices resume on their own; everything else is consumed and
    released. `lib` is injectable so tests run without libei."""

    def __init__(self, fd: int, name: bytes = b"wondershot", lib=None):
        self._lib = lib if lib is not None else open_libei()
        self._ctx = self._lib.ei_new_receiver(None)
        if not self._ctx:
            raise OSError("ei_new_receiver failed")
        self._lib.ei_configure_name(self._ctx, name)
        rc = self._lib.ei_setup_backend_fd(self._ctx, fd)
        if rc != 0:
            self._lib.ei_unref(self._ctx)
            self._ctx = None
            raise OSError(f"ei_setup_backend_fd failed (rc={rc})")
        self.connected = False
        self.disconnected = False

    @property
    def fd(self) -> int:
        return self._lib.ei_get_fd(self._ctx)

    def dispatch(self) -> list[ButtonEvent]:
        self._lib.ei_dispatch(self._ctx)
        out: list[ButtonEvent] = []
        while True:
            ev = self._lib.ei_get_event(self._ctx)
            if not ev:
                return out
            try:
                kind = self._lib.ei_event_get_type(ev)
                if kind == EI_EVENT_CONNECT:
                    self.connected = True
                elif kind == EI_EVENT_DISCONNECT:
                    self.disconnected = True
                elif kind == EI_EVENT_SEAT_ADDED:
                    seat = self._lib.ei_event_get_seat(ev)
                    self._lib.ei_seat_bind_capabilities(
                        ctypes.c_void_p(seat),
                        ctypes.c_int(EI_DEVICE_CAP_POINTER),
                        ctypes.c_int(EI_DEVICE_CAP_BUTTON),
                        ctypes.c_void_p(None))
                elif kind == EI_EVENT_BUTTON_BUTTON:
                    out.append(ButtonEvent(
                        time_us=int(self._lib.ei_event_get_time(ev)),
                        button=int(
                            self._lib.ei_event_button_get_button(ev)),
                        is_press=bool(
                            self._lib.ei_event_button_get_is_press(ev))))
                # DEVICE_ADDED/RESUMED/etc.: nothing to do on the
                # receive path — consumed and released.
            finally:
                self._lib.ei_event_unref(ev)

    def close(self) -> None:
        if self._ctx:
            self._lib.ei_unref(self._ctx)
            self._ctx = None
