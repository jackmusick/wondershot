# WS-C desktop checklist (live KDE session, NOT offscreen)

1. Quick bar: Settings → General → "Quick-action bar after capture" ON,
   "Show Wondershot window after capture" OFF. Capture a region — a
   frameless bar should appear bottom-center, above other windows, with
   a thumbnail of the shot. Verify: Edit opens the editor on the file;
   Copy → paste into another app; Save as → file lands where chosen;
   Share → URL on clipboard (with a provider configured) or a tray hint
   (without); Trash → file gone from the gallery, Ctrl+Z in the gallery
   restores it; Esc dismisses; left alone it dismisses after the
   configured timeout; hovering pauses the countdown.
2. Bar does NOT appear when "Show Wondershot window after capture" is ON.
3. Window mode: tray menu shows "Capture window" (KDE). Focus a window,
   trigger it — the saved PNG is exactly that window's frame, correct
   monitor, correct under HiDPI scaling. Repeat with a window on the
   second monitor. KWin must remain alive throughout (the whole point).
4. Off-KDE sanity (optional, any GNOME/wlroots session or
   XDG_CURRENT_DESKTOP unset): no "Capture window" in the tray, no
   "Window" button in the capture panel.

## Reviewer additions (quick bar / window mode)

5. Two captures back-to-back (<1 s apart, gallery hidden): the first
   quick bar is replaced cleanly by the second (no orphan/flash).
6. Quick-bar Esc under Wayland specifically: the bar is a frameless
   Qt.Tool window and may never get keyboard focus from KWin — confirm
   Esc actually dismisses (the ✕ and timeout are the fallbacks).
7. Share from the bar when the default provider is unconfigured but
   another is: toast flow works; note it rewrites your default provider
   (existing "clicking selects default" semantics).
8. If you ever run mixed per-monitor scale factors (1x + 2x): window
   capture crop alignment on the scaled monitor (uniform-scale
   assumption in the crop math).

## Stitch v2 (scroll capture)

9. `wondershot --scroll-spike` from a terminal: the portal picker MUST
   appear even though a recorder restore token is stored (the wrong-
   window bug fix). Pick the window you'll scroll.
10. After the scroll spike, start a normal recording: the picker must
    NOT appear (scroll session didn't clobber the recorder's token).
11. Scroll a long page with normal kinetic scrolling, Ctrl+C: inspect
    the stitched PNG — seams should now be clean (multi-band consensus
    + drop-on-low-confidence replaced the single-band matcher).
12. One deliberately fast flick-scroll mid-run: should just report
    dropped frames at exit (pre-review this could crash the stitcher).
