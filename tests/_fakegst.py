"""Fakeable pipeline doubles for the in-process recorder tests.

`ScreenRecorder` owns `self._pipeline`, duck-typed to the tiny lifecycle
surface (poll_status/error_text/send_eos/force_stop/pause/resume). These
fakes let every behavioral test run with NO GStreamer import.
"""


class FakePipeline:
    """A cooperative in-process pipeline double (no Gst)."""

    def __init__(self, status="running"):
        self._status = status  # "running" | "eos" | "error"
        self.eos_sent = False
        self.stopped = False
        self.paused = False

    def poll_status(self):
        # Mimic the real bus: an EOS event takes a poll cycle to propagate,
        # so the first poll after send_eos still reports "running" (the
        # observable 'Stopping…' window the UI keys off).
        if self._status == "eos_pending":
            self._status = "eos"
            return "running"
        return self._status

    def error_text(self):
        return "from element mux: wedged"

    def send_eos(self):
        self.eos_sent = True
        if self._status == "running":  # cooperative: finalizes on EOS
            self._status = "eos_pending"

    def force_stop(self):
        self.stopped = True
        self._status = "error"  # giving up == terminal, non-clean

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False


class WedgedPipeline(FakePipeline):
    """An EOS-ignoring pipeline: send_eos never finalizes, so the
    escalation ladder must force_stop it (2nd-SIGINT / SIGKILL analog)."""

    def send_eos(self):
        self.eos_sent = True  # stays "running" until force_stop
