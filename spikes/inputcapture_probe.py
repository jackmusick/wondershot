#!/usr/bin/env python3
"""WS-D spike: probe org.freedesktop.portal.InputCapture on this box.

Answers: is the InputCapture portal present on Fedora/KDE, and can we
get far enough (session -> zones -> EIS fd) to observe pointer button
events? Findings decide whether step capture ships Linux-first or
Windows-first (see ROADMAP.md "WS-D capture-engine spike findings").

Standalone: run with the SYSTEM python (needs gi):
    python3 spikes/inputcapture_probe.py

Defensive D-Bus posture (see wondershot/hotkey.py landmine history):
talks only to org.freedesktop.portal.Desktop, explicit GLib.Variant
types everywhere, finite timeouts, GLib.Error caught per step.
"""
from __future__ import annotations

import os
import random
import select
import sys

try:
    import gi
    from gi.repository import Gio, GLib
except ImportError:
    print("FINDING: python3-gobject (gi) not importable — cannot probe")
    sys.exit(2)

BUS = "org.freedesktop.portal.Desktop"
PATH = "/org/freedesktop/portal/desktop"
IFACE = "org.freedesktop.portal.InputCapture"
TIMEOUT_MS = 5000

# InputCapture capabilities bitmask (portal spec)
CAP_KEYBOARD, CAP_POINTER, CAP_TOUCH = 1, 2, 4


def finding(msg: str) -> None:
    print(f"FINDING: {msg}", flush=True)


class Probe:
    def __init__(self):
        self.conn = Gio.bus_get_sync(Gio.BusType.SESSION, None)
        self.loop = GLib.MainLoop()
        self.session: str | None = None
        self.zone_set: int | None = None

    # -- plumbing (mirrors wondershot/record.py) ----------------------

    def _token(self) -> str:
        return f"wsprobe{random.randint(0, 2**31)}"

    def _request_path(self, token: str) -> str:
        sender = self.conn.get_unique_name()[1:].replace(".", "_")
        return (f"/org/freedesktop/portal/desktop/request/"
                f"{sender}/{token}")

    def _call_with_response(self, method: str, variant: GLib.Variant,
                            token: str) -> dict | None:
        """Synchronous request/Response: subscribe first, call, spin
        a main loop until the Response signal or timeout."""
        result: dict = {}

        def on_response(_c, _s, _p, _i, _m, params):
            code, results = params.unpack()
            result["code"] = code
            result["results"] = results
            self.loop.quit()

        sub = self.conn.signal_subscribe(
            BUS, "org.freedesktop.portal.Request", "Response",
            self._request_path(token), None,
            Gio.DBusSignalFlags.NONE, on_response)
        try:
            self.conn.call_sync(BUS, PATH, IFACE, method, variant,
                                None, Gio.DBusCallFlags.NONE,
                                TIMEOUT_MS, None)
        except GLib.Error as e:
            self.conn.signal_unsubscribe(sub)
            finding(f"{method} call failed: {e.message}")
            return None
        # Track the timeout source: if the Response arrives first, a
        # stale timeout would fire into the NEXT call's loop.run()
        # and quit it early. (On timeout the source self-removes by
        # returning None/False from loop.quit.)
        timeout_id = GLib.timeout_add(TIMEOUT_MS, self.loop.quit)
        self.loop.run()
        if "code" in result:
            GLib.Source.remove(timeout_id)
        self.conn.signal_unsubscribe(sub)
        if "code" not in result:
            finding(f"{method}: no Response within {TIMEOUT_MS}ms")
            return None
        if result["code"] != 0:
            finding(f"{method}: Response code {result['code']} "
                    "(1=cancelled, 2=other)")
            return None
        return result["results"]

    def _get_property(self, name: str):
        try:
            v = self.conn.call_sync(
                BUS, PATH, "org.freedesktop.DBus.Properties", "Get",
                GLib.Variant("(ss)", (IFACE, name)),
                None, Gio.DBusCallFlags.NONE, TIMEOUT_MS, None)
            return v.unpack()[0]
        except GLib.Error as e:
            finding(f"property {name} unavailable: {e.message}")
            return None

    # -- probe steps ---------------------------------------------------

    def check_available(self) -> bool:
        version = self._get_property("version")
        if version is None:
            finding("InputCapture portal NOT available on this box")
            return False
        finding(f"InputCapture portal present, version={version}")
        caps = self._get_property("SupportedCapabilities")
        if caps is not None:
            names = [n for bit, n in ((CAP_KEYBOARD, "KEYBOARD"),
                                      (CAP_POINTER, "POINTER"),
                                      (CAP_TOUCH, "TOUCHSCREEN"))
                     if caps & bit]
            finding(f"SupportedCapabilities={caps} ({'|'.join(names)})")
        return True

    def create_session(self) -> bool:
        token, stoken = self._token(), self._token()
        results = self._call_with_response(
            "CreateSession",
            GLib.Variant("(sa{sv})", ("", {
                "handle_token": GLib.Variant("s", token),
                "session_handle_token": GLib.Variant("s", stoken),
                "capabilities": GLib.Variant(
                    "u", CAP_POINTER | CAP_KEYBOARD),
            })), token)
        if results is None:
            finding("CreateSession FAILED — cannot probe further")
            return False
        self.session = results.get("session_handle", "")
        caps = results.get("capabilities")
        finding(f"CreateSession OK (granted capabilities={caps})")
        return bool(self.session)

    def get_zones(self) -> bool:
        token = self._token()
        results = self._call_with_response(
            "GetZones",
            # Signature is (o session_handle, a{sv} options) — no
            # parent_window string, unlike CreateSession.
            GLib.Variant("(oa{sv})", (self.session, {
                "handle_token": GLib.Variant("s", token)})), token)
        if results is None:
            finding("GetZones FAILED")
            return False
        zones = results.get("zones") or []
        self.zone_set = results.get("zone_set")
        finding(f"GetZones OK: zones={zones} zone_set={self.zone_set}")
        return bool(zones)

    def connect_eis(self) -> int:
        try:
            reply, fd_list = self.conn.call_with_unix_fd_list_sync(
                BUS, PATH, IFACE, "ConnectToEIS",
                GLib.Variant("(oa{sv})", (self.session, {})),
                None, Gio.DBusCallFlags.NONE, TIMEOUT_MS, None, None)
            fd = fd_list.get(reply.unpack()[0])
            finding(f"ConnectToEIS OK: got EIS fd={fd}")
            return fd
        except GLib.Error as e:
            finding(f"ConnectToEIS FAILED: {e.message}")
            return -1

    def observe_events(self, fd: int) -> None:
        """Try to see pointer-button events on the EIS fd."""
        try:
            import snegg.ei  # python libei bindings, if installed
        except ImportError:
            finding("no python libei bindings (snegg) installed — "
                    "cannot speak the EI protocol from Python here")
            # Honest fallback: EI requires a client handshake, so a
            # raw read should yield nothing; prove/record that.
            os.set_blocking(fd, False)
            r, _, _ = select.select([fd], [], [], 3.0)
            if r:
                data = os.read(fd, 4096)
                finding(f"raw read got {len(data)} bytes without a "
                        "handshake (unexpected — investigate)")
            else:
                finding("raw fd silent without EI handshake (expected); "
                        "event observation needs libei (C) or snegg — "
                        "fd plumbing itself works")
            return
        finding("snegg (python libei) present — attempting real "
                "event observation for 10s; CLICK SOME BUTTONS NOW")
        ctx = snegg.ei.Receiver.create_for_fd(fd=fd, name="ws-probe")
        deadline = GLib.get_monotonic_time() + 10_000_000
        saw = 0
        while GLib.get_monotonic_time() < deadline:
            r, _, _ = select.select([ctx.fd], [], [], 0.5)
            if not r:
                continue
            ctx.dispatch()
            for ev in ctx.events:
                if ev.event_type == snegg.ei.EventType.BUTTON_BUTTON:
                    saw += 1
                    finding(f"pointer BUTTON event observed: "
                            f"button={ev.button} state={ev.is_press}")
        finding(f"observed {saw} button events"
                if saw else "no button events observed (capture may "
                "need Enable + pointer barriers + activation)")

    def close(self) -> None:
        if self.session:
            try:
                self.conn.call_sync(
                    BUS, self.session,
                    "org.freedesktop.portal.Session", "Close",
                    None, None, Gio.DBusCallFlags.NONE, 1000, None)
            except GLib.Error:
                pass


def main() -> int:
    print("== InputCapture portal probe (WS-D spike) ==")
    print("Safe-by-construction: portal daemon only, typed variants,")
    print("finite timeouts. See wondershot/hotkey.py for why.\n")
    try:
        probe = Probe()
    except GLib.Error as e:
        finding(f"session bus unavailable: {e.message}")
        return 2
    try:
        if not probe.check_available():
            return 1
        if not probe.create_session():
            return 1
        probe.get_zones()
        fd = probe.connect_eis()
        if fd >= 0:
            probe.observe_events(fd)
            os.close(fd)
        return 0
    finally:
        probe.close()
        finding("probe done — copy FINDING lines into ROADMAP.md "
                "(WS-D findings section)")


if __name__ == "__main__":
    sys.exit(main())
