# Wondershot M8 — Layout Parity Rebuild — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`).
> **Oracle:** `tests-ui/ref/qt/{gallery,editor,capture_window,settings_dialog}.png` (real Qt app, rendered offscreen) — NOT wonderblob's shell. wonderblob supplies visual *tokens* only.

**Goal:** Rebuild the frontend information architecture to match the Qt app: an **editor-centric main window with a bottom filmstrip** (not a left-sidebar gallery browser), a compact capture panel, a right-hand Properties panel, and reachable tabbed Settings. The Rust backend + the editor/Konva pieces are reused as-is; this is a shell/layout refactor.

**Why this milestone exists:** the original rewrite anchored every UI check on wonderblob's design language and validated "parity" via `cargo test` (data round-trips) + mock-mode screenshots (which hid that previews 404 and that the layout was wrong). The result diverged from the Qt app's actual layout. M8 corrects the IA against the real oracle and fixes the review harness so this can't recur.

**Architecture:** `+page.svelte` becomes the editor-centric shell:
```
┌───────────────────────────────────────────────────────────┐
│ Capture · ●Record · Record region · ⚙Settings      Share   │  Header (always)
├───────────────────────────────────────────────────────────┤
│ Select Arrow Line Box Ellipse Pen Highlight Text Step …    │  Tool rail (when an item is open)
├──────────────────────────────────────────────┬────────────┤
│                                                │ Properties │
│                 Editor canvas                  │  Color     │  Right panel
│              (always present;                  │  Stroke    │
│           placeholder when empty)              │  Effects…  │
│                                                │            │
├──────────────────────────────────────────────┴────────────┤
│ 960×540                          − Fit + Fit · N shots      │  Zoom/dim bar
├───────────────────────────────────────────────────────────┤
│ [thumb] [thumb] [thumb] [thumb] [thumb]  →  (horizontal)    │  Filmstrip (bottom)
└───────────────────────────────────────────────────────────┘
```
The existing `EditorCanvas`, `EditorToolbar` (tools), library list, and `Settings` are re-composed; the toolbar's inline effect controls move into a right `PropertiesPanel`; `LibrarySidebar` becomes a horizontal `Filmstrip`.

**Tech Stack:** SvelteKit/Svelte 5, existing stores (`activeItem`, `captures`, `view`), Playwright shots, a UI-review workflow rebound to the Qt oracle.

---

## Behavioral contract (from the Qt references — match)

- **Main window is one surface**, editor always visible. Selecting a filmstrip thumb loads it into the editor (no separate "gallery view"). Empty state = placeholder image + "no shot selected".
- **Header (always visible):** left group `Capture` · `● Record` · `Record region` · `⚙ Settings`; right `Share`. (Record region = region-scoped recording; if no backend yet, render disabled with a tooltip — no silent omission.)
- **Tool rail (when an item is open):** Select, Arrow, Line, Box, Ellipse, Pen, Highlight, Text, Step, Pixelate, Blur, Crop, Cut | (vertical), Cut — (horizontal), | Undo, Redo, | AI Redact, AI Simplify, Remove BG. Icon + label per tool (Qt shows labels).
- **Properties panel (right):** Color, Stroke (number), Text size (number), Align (3 buttons), **Effects**: Rounded corners (checkbox) + Radius (number), Bottom fade (checkbox) + Fade height (number). Footnote "Applies to the selection and to new objects." Reuses the existing effect state (M3/M5).
- **Zoom/dim bar (below canvas):** `W×H` dimensions (left); `−` / Fit / `+` / Fit-reset and `N shots` (right).
- **Filmstrip (bottom):** horizontal, non-wrapping, fixed height (~CAROUSEL_HEIGHT), thumbnail cards each with a date band ("Today"/date bottom-left, time bottom-right). Selected card: blue ring + an (×) delete affordance on hover. Click loads into editor; horizontal scroll.
- **Capture panel (compact):** `Preview in editor` / `Copy to clipboard` / `Capture cursor` checkboxes, `Delay` field, a big **Capture** button, and `Full screen` / `Record` links. In Qt it's a separate always-on-top window; in Tauri, the header `Capture` opens it as a popover/panel (a frameless secondary window is a later refinement).
- **Settings dialog (reachable from header):** tabs General / Sharing / AI. General: Screenshot library (+Browse), Also watch (+Add), Capture hotkey (read-only + guidance), Capture backend (select), copy-after / show-after / quick-bar toggles, Bar timeout, Camera (select), Microphone (select), record-mic / noise-suppression toggles, Recording countdown, and a **Global capture hotkey** group (the `wondershot --capture` command + "Open KDE Shortcuts"). Sharing/AI tabs may be stubbed with "not in this build" if their backends are out of scope — but the **tabs must exist** (Qt parity), not silently dropped.

---

## File Structure

```
src/routes/+page.svelte                       # REBUILD: editor-centric shell (header/rail/canvas/properties/zoombar/filmstrip)
src/lib/components/AppHeader.svelte            # NEW (rename/replace CaptureHeader): Capture/Record/Record region/Settings + Share
src/lib/components/Filmstrip.svelte            # NEW (replace LibrarySidebar): horizontal thumbnail carousel + date band
src/lib/components/CapturePanel.svelte         # NEW: compact capture popover (toggles + big Capture + links)
src/lib/components/PropertiesPanel.svelte      # NEW: right panel (color/stroke/text/align/effects) — moved out of EditorToolbar
src/lib/editor/EditorToolbar.svelte            # TRIM: tools-only rail (labels); effects move to PropertiesPanel
src/lib/components/ZoomBar.svelte              # NEW: dims + zoom + N shots
src/lib/components/Settings.svelte             # EXTEND: General-tab fields to match Qt; reachable from header; Sharing/AI tab stubs
src/lib/components/ContentView.svelte          # SIMPLIFY: editor always (image), video player for videos, placeholder when empty
workflows/ui-review.mjs                        # REBIND default REF to tests-ui/ref/qt/*; compare layout against Qt, not wonderblob
tests-ui/capture.spec.ts                       # update screen shots to the new shell regions
```

---

## Task 1: Filmstrip + editor-centric shell skeleton

**Files:** `src/lib/components/Filmstrip.svelte` (new), `src/routes/+page.svelte`, `src/lib/components/ContentView.svelte`. Oracle: `gallery.png`.

- [ ] **Step 1: `Filmstrip.svelte`** — horizontal carousel from `captures`. Each card: thumbnail (`assetSrc`), a bottom date band ("Today"/`MM/DD` left, `h:MMam` right), selected ring when `activeItem.id === c.id`, an (×) on hover that calls the existing trash path. Clicking sets `activeItem` + `view='editor'`. Fixed height ~150px, `overflow-x: auto`, no wrap. Use tokens (`--bg-sidebar` track, `--bg-selected`, `--accent`).
- [ ] **Step 2: rebuild `+page.svelte`** to the vertical stack: `<AppHeader/>` → `<EditorToolbar/>` (only when `$activeItem`) → a row `{ <ContentView/> (flex:1) + <PropertiesPanel/> (when $activeItem image) }` → `<ZoomBar/>` (when $activeItem) → `<Filmstrip/>`. Keep the existing `onMount` listeners (capture://done, cli://*).
- [ ] **Step 3: simplify `ContentView`** — when `activeItem` is a video → `VideoPlayer`; when an image → `EditorCanvas` (always editor, drop the gallery-preview branch); when null → placeholder ("Select or take a capture").
- [ ] **Step 4: build + shot:** `npm run build`; `npm run test:ui` → regenerate `artifacts/ui/shell-dark.png`. Expected: editor canvas with a filmstrip along the bottom (no left sidebar).
- [ ] **Step 5: commit** — `M8: editor-centric shell with bottom filmstrip (replaces left-sidebar gallery)`.

---

## Task 2: AppHeader (Capture / Record / Record region / Settings / Share)

**Files:** `src/lib/components/AppHeader.svelte` (new, replacing CaptureHeader's non-editor branch), `+page.svelte`. Oracle: `gallery.png` top bar.

- [ ] **Step 1:** header with a left group — `Capture` (opens CapturePanel, Task 4), `● Record` (start/stop via existing recorder control), `Record region` (region record; disabled+tooltip if no backend), `⚙ Settings` (opens Settings) — and a right `Share` button (stub: opens a "share targets not in this build" note, since cloud sharing is out of scope but the control exists for parity). Show the recording timer/Pause/Stop state inline when `recording.status !== 'idle'` (reuse current logic).
- [ ] **Step 2:** wire `Settings` open from the header (`settingsOpen.set(true)`); remove the bottom-left gear (it moved here).
- [ ] **Step 3:** build + UI-review (Task 6 harness) the header against `gallery.png`.
- [ ] **Step 4: commit** — `M8: AppHeader — Capture/Record/Record region/Settings + Share (Qt parity)`.

---

## Task 3: Properties panel + tools-only rail

**Files:** `src/lib/components/PropertiesPanel.svelte` (new), `src/lib/editor/EditorToolbar.svelte` (trim to tools). Oracle: `gallery.png` right panel + tool rail.

- [ ] **Step 1:** move the color/stroke/text-size/align + effects (Rounded+Radius, Bottom fade+Fade height) controls out of `EditorToolbar` into `PropertiesPanel.svelte` (right column), bound to the same editor stores/state. Add the "Applies to the selection and to new objects" footnote.
- [ ] **Step 2:** `EditorToolbar` becomes the horizontal **tools** rail only, each tool icon **with its label** (Select/Arrow/…/Remove BG), grouped with separators as in the oracle. Keep Undo/Redo + AI Redact/AI Simplify/Remove BG.
- [ ] **Step 3:** build + shot `editor-dark.png`; UI-review against `editor.png`/`gallery.png`.
- [ ] **Step 4: commit** — `M8: right Properties panel + labeled tools-only rail (Qt parity)`.

---

## Task 4: Compact CapturePanel + ZoomBar

**Files:** `src/lib/components/CapturePanel.svelte` (new), `src/lib/components/ZoomBar.svelte` (new). Oracle: `capture_window.png`, `gallery.png` zoom bar.

- [ ] **Step 1: CapturePanel** popover (opened by header `Capture`): `Preview in editor` / `Copy to clipboard` / `Capture cursor` checkboxes (bound to settings), a `Delay` field, a prominent **Capture** button (calls `takeCapture('region')`), and `Full screen` / `Record` links. Close on capture.
- [ ] **Step 2: ZoomBar** below the canvas: `W×H` (from the active image's natural size), `−`/Fit/`+`/Fit-reset (wire to the editor zoom store — `src/lib/editor/zoom.ts`), and `N shots` (captures.length).
- [ ] **Step 3:** build + shots; UI-review.
- [ ] **Step 4: commit** — `M8: compact CapturePanel + ZoomBar (dims/zoom/N shots)`.

---

## Task 5: Settings parity (General tab fields + reachable + tabs)

**Files:** `src/lib/components/Settings.svelte`. Oracle: `settings_dialog.png`.

- [ ] **Step 1:** ensure tabs **General / Sharing / AI** exist. General fields to match the Qt General tab: Screenshot library (+Browse via dialog), Also watch (+Add), Capture hotkey (read-only + guidance), Capture backend (select: Auto/Spectacle/portal), copy-after / show-after / quick-bar toggles, Bar timeout, Camera (select), Microphone (select), record-mic / noise-suppression toggles, Recording countdown (select), and the **Global capture hotkey** group (`wondershot --capture` command text + an "Open KDE Shortcuts" button). Bind to `get_settings`/`set_settings` (existing). Sharing/AI: a short "not included in this build" panel (backends out of scope) — tabs present, not dropped.
- [ ] **Step 2:** confirm it opens from the header (Task 2) and persists (existing set_settings).
- [ ] **Step 3:** build + shot `settings-dark.png`; UI-review against `settings_dialog.png`.
- [ ] **Step 4: commit** — `M8: Settings General-tab parity + reachable from header + Sharing/AI tabs`.

---

## Task 6: Rebind the UI-review harness to the Qt oracle

**Files:** `workflows/ui-review.mjs`, `tests-ui/capture.spec.ts`.

- [ ] **Step 1:** change the workflow's `REF` from `tests-ui/ref/wonderblob-shell.png` to the matching `tests-ui/ref/qt/*.png` per shot (shell→gallery.png, editor→editor.png, settings→settings_dialog.png), and reword the critique prompt to score **layout/IA parity against the Qt reference** (filmstrip-at-bottom, editor-centric, right properties panel, header actions) in addition to the wonderblob token aesthetic. A shot that structurally diverges from its Qt reference is `pass=false`.
- [ ] **Step 2:** add a `capture` screen shot to `capture.spec.ts` (the CapturePanel) and ensure shell/editor/settings shots cover the new regions.
- [ ] **Step 3: commit** — `M8: rebind UI-review to the Qt oracle (layout parity, not just tokens)`.

---

## Task 7: M8 verification

- [ ] **Step 1:** `npm run test && npm run build && cargo build -p wondershot`. Expected: green.
- [ ] **Step 2:** regenerate all shots; run the (rebound) UI-review across shell/editor/capture/settings vs the Qt oracle; fix blockers.
- [ ] **Step 3 (real-app gate):** rebuild the Flatpak (or `cargo tauri build`) and launch — confirm the filmstrip, editor, header, properties, capture panel, settings, and **previews** (asset-protocol fix) all render correctly against the Qt app side by side.
- [ ] **Step 4:** update the parity checklist + roadmap (add M8); the `tauri-rewrite` → `main` merge stays held until the layout matches and the user signs off.

---

## Self-Review notes (author)

- **Root-cause fix:** the divergence came from a wonderblob-only oracle + mock-mode screenshots + cargo-test-as-parity. M8 fixes all three: real Qt reference shots (committed), the review rebound to them (T6), and a real-app launch gate (T7) instead of mock screenshots.
- **Reuse, not rewrite:** EditorCanvas/Konva, the recorder/video/settings commands, and the editor state are unchanged; M8 re-composes the shell and moves controls (effects → PropertiesPanel, library list → Filmstrip).
- **No silent drops:** Record region, Share, and Sharing/AI settings tabs are rendered (disabled/stubbed with a reason) rather than omitted, so the surface matches the Qt app even where a backend is out of scope.
- **Previews:** fixed already (assetProtocol scope) — T7 verifies it in the real app, the environment the bug actually manifests in.
