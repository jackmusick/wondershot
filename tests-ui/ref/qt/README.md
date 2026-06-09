# Qt reference shots — the real parity oracle

Rendered deterministically from the Python/Qt app (the daily driver on `main`):

```
QT_QPA_PLATFORM=offscreen .venv/bin/python -c \
  "from wondershot.selftest import run_selftest; run_selftest('/tmp/qt-ref')"   # gallery.png, editor.png
# capture_window.png / settings_dialog.png: instantiate CaptureWindow(settings) /
#   SettingsDialog(settings) offscreen and .grab().save() (see M8 plan).
```

These — NOT wonderblob's shell — are what the Tauri UI must match for layout/feature
parity. wonderblob supplies the visual *tokens* (colors/radii); these supply the
*information architecture*:

- **gallery.png** — the main window: header (Capture · Record · Record region · Settings · Share),
  a horizontal tool rail, the editor canvas (always present), a right-hand Properties panel,
  a zoom/dimensions bar, and a **horizontal filmstrip of thumbnails along the bottom**.
- **editor.png** — the canvas with one of each annotation.
- **capture_window.png** — the compact always-on-top capture panel (big Capture button + toggles).
- **settings_dialog.png** — tabbed General/Sharing/AI settings.
