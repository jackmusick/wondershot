# Spike: pause/resume over the gst-launch recorder (2026-06-07)

**Question:** can the existing recorder — a `gst-launch-1.0 -e` argv
subprocess fed a portal/PipeWire screencast (`record.py` `_gst_args` /
`Popen`) — pause and resume a recording with gapless, A/V-synced output?

**Feasibility gate (from the plan):** pause/resume ships only if a
mechanism (a) works against a `gst-launch` argv subprocess AND
(b) produces gapless, A/V-synced output across a pause.

## Architecture analysis

- `gst-launch-1.0` exposes **no runtime control channel**. Its inputs
  after launch are POSIX signals only. There is no way to set the
  pipeline to `PAUSED`, no way to flip a `valve drop=true/false`
  property mid-run, no IPC of any kind. The only meaningful signal is
  SIGINT, which `-e` turns into EOS (that is the *stop* path, and even
  that can wedge — see Task 1's escalation ladder).
- The one externally available "pause" is `SIGSTOP`/`SIGCONT` on the
  process. That freezes the *process*, not the *pipeline clock*:
  `pipewiresrc do-timestamp=true` and `pulsesrc do-timestamp=true`
  stamp buffers with the running pipeline clock, so on `SIGCONT` the
  buffer PTS jump by the paused wall-time. `mp4mux` writes those
  timestamps as-is → a frozen-frame gap and desynced/dropped audio
  (pulse overruns — exactly the journal signature from the 2026-06-06
  EOS-wedge forensics).
- Worse: the `videorate` element in the video branch (the no-PTS
  landmine fix — pipewiresrc intermittently emits buffers with no PTS;
  videorate drops them and yields CFR output) will **backfill the
  entire pause gap with duplicated frames** to maintain CFR. The
  output would not even show a visible cut — it silently contains
  minutes of frozen video. That fails gate condition (b) by
  construction, before any probe runs.

## SIGSTOP probe (live-session step — manual checklist)

This session is non-interactive (no portal sessions / live recordings
allowed), so the confirmation probe is parked on the plan's manual
verification checklist:

1. Start a recording from the app (worktree build:
   `.venv/bin/wondershot`, Record).
2. `kill -STOP $(pgrep -f 'gst-launch-1.0 -e pipewiresrc')`, wait
   10 s, `kill -CONT` the same pid, record 5 more seconds, stop
   normally.
3. `ffprobe -show_streams <output>.mp4` and play it. Expected: the
   duration includes the paused 10 s as duplicated frames (videorate
   backfill) and/or desynced audio.
4. Paste the ffprobe output and observations back into this file.

The probe can only *confirm* the failure mode and quantify the damage;
it cannot pass the gate — no PTS-clean mechanism exists to test
against a gst-launch argv subprocess.

## Conclusion — gate FAILS (expected)

Pause/resume is **infeasible over gst-launch**: there is no control
channel for a clean pause, and the only available process-level pause
(SIGSTOP/SIGCONT) provably corrupts timestamps and is then masked by
videorate's CFR backfill into silently-wrong output. Clean pause needs
owning the pipeline in-process (gst python bindings / appsink) with
valves ahead of the mux and accumulated-offset PTS rewriting — the
same frame-source seam as the cursor halo (`spikes/cursor_halo_probe.md`)
and WS-D scroll capture. Parked in ROADMAP; pause/resume rides along
with that in-process pipeline rewrite.
