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
