# Wondershot M3 — Konva Editor (14 tools) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`). The 14 tools are built as a workflow pipeline: each tool = build → screenshot → vision-critique (reusing `workflows/ui-review.mjs`).

**Goal:** Replace the Python `QGraphicsScene` editor with a Svelte + Konva canvas reaching feature parity: all 14 annotation tools, selection + transform handles, undo/redo, zoom, the non-destructive base-stack (crop/cutout), output effects, and save/flatten — writing the EXACT `.wondershot` sidecar JSON the Python app reads (so libraries are interchangeable).

**Architecture:** A Konva `Stage` mounted in the content view (`view === 'editor'`). A tool framework dispatches pointer events per active tool to create Konva nodes. Each annotation is a typed model that (de)serializes to the Python item JSON. Undo/redo is a snapshot stack of the item model list. Destructive ops (crop/cutout) and base-image effects (pixelate/blur/rounded/fade) are computed in Rust (`wondershot-core`, reusing M2's `image` dep) via Tauri commands, because they need real pixel processing — the frontend sends a region + the base path and gets back a PNG/patch. Save flattens the Konva stage to a PNG (frontend `stage.toCanvas()` → bytes → Rust writes the library PNG) and writes the sidecar via the existing `save_sidecar` command.

**Tech Stack:** Konva 9 + svelte-konva (already deps), the existing Svelte 5 shell, `wondershot-core` (add an `imageops` module + `editor` serde models), Tauri commands.

**Parity oracle:** Python `wondershot/editor.py`, `items.py`, `imageops.py` + tests `tests/test_items_serialize.py`, `tests/test_editor.py`, `tests/test_editor_sidecar.py`. The serialized JSON for every tool MUST match `items.py:to_dict()` byte-for-byte (field names, order-independent, value types).

---

## The item serialization contract (ported from items.py — exact)

Every item shares transform fields, applied in order **origin → rotation → position**:
`"pos": [x,y]`, `"rotation": <deg float>`, `"origin": [ox,oy]`.

| Tool | Key | Shortcut | Draw | Serialized fields (besides transform) | Konva node |
|---|---|---|---|---|---|
| Select | — | `V` | click/drag/grips | — | Transformer |
| Arrow | `arrow` | `A` | drag p1→p2 | `p1:[x,y]`, `p2:[x,y]`, `color:"#RRGGBBAA"`, `width:int` | Arrow |
| Line | `line` | `L` | drag p1→p2 | `p1`, `p2`, `color`, `width` | Line |
| Rect | `rect` | `R` | drag bbox | `rect:[x,y,w,h]`, `color`, `width`, `fill?:"#RRGGBBAA"` | Rect |
| Ellipse | `ellipse` | `E` | drag bbox | `rect:[x,y,w,h]`, `color`, `width` | Ellipse |
| Freehand | `freehand` | `P` | drag paints points | `points:[[x,y]…]`, `color`, `width` | Line(points) |
| Highlight | `highlight` | `H` | drag bbox | `rect:[x,y,w,h]`, `color:"#RRGGBB"` (alpha 90 applied on load, stored opaque) | Rect (mult blend, opacity .35) |
| Text | `text` | `T` | click=auto / drag=box | `text`, `color`, `family`, `point_size:int`, `bold:bool`, `text_width:float (-1 auto)`, `align:"left\|center\|right"` | Text |
| Step | `step` | `N` | click stamps # | `number:int`, `color`, `radius:float (16)` | Group(Circle+Text) |
| Pixelate | `pixelate` | `X` | drag bbox | `rect:[x,y,w,h]`, `block:int (14)` | Image(patch from Rust) |
| Blur | `blur` | `B` | drag bbox | `rect:[x,y,w,h]`, `radius:int (12)` | Image(patch from Rust) |
| Crop | — | `C` | drag bbox | (destructive, no item) | — |
| Cutout-V | — | `U` | drag x-band | (destructive, no item) | — |
| Cutout-H | — | `Shift+U` | drag y-band | (destructive, no item) | — |

Notes: highlight stores `#RRGGBB` (no alpha) and re-applies alpha 90 on load; text is bold by default; step font = `radius*0.85` (<10) / `radius*0.7` (≥10), white text + 2px white border; step counter auto-increments, undo decrements, load sets `max(number)+1`.

Effects dict: `{ "rounded": bool, "corner_radius": int, "fade": bool, "fade_height": int }`.

---

## File Structure

```
crates/wondershot-core/
  src/imageops.rs            # crop, cut_out, pixelated_patch, blurred_patch, rounded_corners, bottom_fade
  src/editor.rs              # serde models for the 11 item types + EditorDoc <-> SidecarDoc items
src-tauri/src/commands.rs    # imageops commands: crop_base, cutout_base, pixelate_patch, blur_patch, apply_effects, flatten_save
src/lib/editor/
  model.ts                   # Item types + (de)serialize to the Python JSON
  tools.ts                   # tool registry, shortcuts, pointer-event dispatch
  history.ts                 # snapshot undo/redo
  EditorCanvas.svelte        # Konva Stage + layers + Transformer
  EditorToolbar.svelte       # 14 tools + color/stroke/font + zoom + effects
  tools/*.ts                 # per-tool create/update/serialize (one file per tool family)
src/lib/components/ContentView.svelte  # mount EditorCanvas when view==='editor'
```

---

## Task 1: Rust `editor` serde models + parity round-trip (TDD)

**Files:** `crates/wondershot-core/src/editor.rs`, add `pub mod editor;` to lib.rs. Oracle: `tests/test_items_serialize.py`.

Model the 11 item types as a serde enum that (de)serializes to the EXACT Python JSON (tag field `type`, transform fields flattened). This gives the Rust side a typed view and a round-trip test that locks the schema.

- [ ] **Step 1: failing tests** — for each tool, a literal JSON string from the Python `to_dict()` shape deserializes into the typed model and re-serializes to an equal `serde_json::Value`. Example (arrow + highlight + step):

```rust
#[cfg(test)]
mod tests {
    use super::*;
    fn roundtrip(json: &str) {
        let v: serde_json::Value = serde_json::from_str(json).unwrap();
        let item: Item = serde_json::from_value(v.clone()).unwrap();
        let back = serde_json::to_value(&item).unwrap();
        assert_eq!(v, back, "roundtrip mismatch");
    }
    #[test] fn arrow_roundtrip() {
        roundtrip(r#"{"type":"arrow","p1":[1.0,2.0],"p2":[3.0,4.0],"color":"#ff0000ff","width":4,"pos":[0.0,0.0],"rotation":0.0,"origin":[0.0,0.0]}"#);
    }
    #[test] fn highlight_roundtrip() {
        roundtrip(r#"{"type":"highlight","rect":[0.0,0.0,60.0,20.0],"color":"#ffe000","pos":[0.0,0.0],"rotation":0.0,"origin":[0.0,0.0]}"#);
    }
    #[test] fn step_roundtrip() {
        roundtrip(r#"{"type":"step","number":3,"color":"#3b82f6ff","radius":16.0,"pos":[5.0,5.0],"rotation":0.0,"origin":[0.0,0.0]}"#);
    }
    // … one per tool: line, rect (with+without fill), ellipse, freehand, text, pixelate, blur
}
```

- [ ] **Step 2: run, expect FAIL.**
- [ ] **Step 3: implement `editor.rs`** — a `#[serde(tag = "type")]` enum `Item` with a variant per tool, each `#[serde(flatten)] transform: Transform` where `Transform { pos: [f64;2], rotation: f64, origin: [f64;2] }`, optional `fill` via `#[serde(skip_serializing_if = "Option::is_none")]`. Use `f64` for all geometry. Provide `EditorDoc { items: Vec<Item>, effects: Effects }` mapping to/from `sidecar::SidecarDoc.items` (Vec<Value>).
- [ ] **Step 4: run, expect PASS** (one test per tool variant).
- [ ] **Step 5: commit** — `M3: Rust editor serde models with item JSON parity`

---

## Task 2: Rust `imageops` (TDD) + Tauri commands

**Files:** `crates/wondershot-core/src/imageops.rs` (+ `pub mod`), `src-tauri/src/commands.rs`. Oracle: `wondershot/imageops.py`.

Implement, with unit tests on small in-memory images (using the `image` crate, already a dep):
- `crop(img, x, y, w, h) -> img`
- `cut_out(img, a, b, horizontal: bool) -> img` (remove the band [a,b], join the halves)
- `pixelated_patch(img, rect, block) -> img` (downscale by block then nearest-upscale)
- `blurred_patch(img, rect, radius) -> img` (gaussian blur the padded region, crop back)
- `rounded_corners(img, radius) -> img`, `bottom_fade(img, height) -> img`

- [ ] **Step 1: failing tests** — e.g. `cut_out` on a 10×4 image removing columns 3..6 yields width 7; `crop` yields exact sub-dimensions; `pixelated_patch` returns the rect size and is constant within a block; `rounded_corners` makes the corner pixel transparent. Write concrete asserts.
- [ ] **Step 2–4: implement to green** (use `image::imageops` for resize/blur; manual alpha for rounded/fade).
- [ ] **Step 5: Tauri commands** wrapping these for the frontend: `crop_base(path, rect) -> new base path (pushes base stack)`, `cutout_base(path, a, b, horizontal)`, `pixelate_patch(path, rect, block) -> png bytes (base64)`, `blur_patch(path, rect, radius) -> png bytes`, `flatten_save(path, png_bytes)` (write the flattened library PNG), plus `apply_effects(path, effects)`. Register in lib.rs.
- [ ] **Step 6: commit** — `M3: Rust imageops (crop/cutout/pixelate/blur/effects) + commands`

---

## Task 3: Editor model + history (frontend, TDD with Vitest)

**Files:** `src/lib/editor/model.ts`, `src/lib/editor/history.ts`.

- [ ] **Step 1: failing tests** — `serializeItem`/`deserializeItem` round-trip each tool to the Python JSON shape (mirror the Rust test JSON); `History.push/undo/redo` snapshots an item-list and restores it; transform order origin→rotation→position preserved.
- [ ] **Step 2–4: implement** — a discriminated-union `Item` TS type matching the contract table; `serializeItem(item): object` producing the exact JSON; `deserializeItem(json): Item`; `History` as a snapshot stack with a `clean` index for the dirty indicator.
- [ ] **Step 5: commit** — `M3: editor model (item serialize) + snapshot history`

---

## Task 4: EditorCanvas — Konva Stage, base image, zoom, select/transform

**Files:** `src/lib/editor/EditorCanvas.svelte`, `src/lib/editor/tools.ts`, `src/lib/components/ContentView.svelte`.

- [ ] Mount a Konva `Stage` with layers: base image (bottom), annotations, overlay (Transformer/grips). Load the active item's base via `assetSrc(path)`.
- [ ] Implement the tool registry + shortcut map (V/A/L/R/E/P/H/T/N/X/B/C/U/Shift+U) and pointer-event dispatch (pointerdown/move/up) to the active tool.
- [ ] Select tool: click selects, Konva `Transformer` for resize/rotate, drag to move, Delete removes; writes back to the model + history on transform-end.
- [ ] Zoom: fit-on-load (never upscale past 100%), Ctrl+wheel zoom [0.05,16], Ctrl+0 actual, Ctrl+9 fit.
- [ ] Mount EditorCanvas in ContentView when `view === 'editor'`; selecting a library item opens it.
- [ ] Screenshot harness: add `?screen=editor` to `src/routes/screen/+page.svelte` mounting EditorCanvas on a fixture image with one of each shape, for the UI-review loop.
- [ ] **Commit** — `M3: EditorCanvas — Konva stage, base image, zoom, select+transform`

---

## Task 5..N: the 14 tools (workflow pipeline — one task per tool family)

Each tool is built with the SAME template (below), as a pipeline item `build → screenshot(?screen=editor with that tool exercised) → vision-critique`. Group structurally-identical tools into one task: (5) arrow+line, (6) rect+ellipse+highlight, (7) freehand, (8) text, (9) step, (10) pixelate+blur (Rust patch), (11) crop, (12) cutout V+H.

**Per-tool template (TDD):**
- [ ] **Step 1:** Vitest test — drawing the tool (simulate pointerdown→move→up at given coords) produces an `Item` whose `serializeItem` equals the expected Python JSON for those coords; and the Konva node has the expected geometry.
- [ ] **Step 2:** run, expect FAIL.
- [ ] **Step 3:** implement `src/lib/editor/tools/<family>.ts` — `onDown/onMove/onUp` creating + updating the Konva node and the model item; register in the tool registry. For pixelate/blur, call the Rust `pixelate_patch`/`blur_patch` command and set the returned PNG as a Konva `Image`. For crop/cutout, call `crop_base`/`cutout_base`, swap the base, push to history, and record the base-stack increment. For step, wire the auto-increment counter (undo decrements). For text, inline-edit via an HTML `<textarea>` overlay, bold default, click=auto / drag=box.
- [ ] **Step 4:** run, expect PASS.
- [ ] **Step 5:** screenshot `?screen=editor` exercising the tool; run `workflows/ui-review.mjs` `kind:'component'` on it; fix blockers.
- [ ] **Step 6:** commit — `M3: <family> tool(s)`.

The expected JSON per tool is the contract table above; the colors/widths come from the toolbar state (Task 13). Highlight stores `#RRGGBB` + applies alpha 90 on render. Step font/border per the notes. Pixelate/blur store `block`/`radius`.

---

## Task 13: EditorToolbar — tools, color/stroke/font, zoom, effects

**Files:** `src/lib/editor/EditorToolbar.svelte` (the header's annotation-tool mode, per M1's CaptureHeader swap).
- [ ] 14 tool buttons (active-state inset accent bar), color swatch (picker), stroke width (1–32), font size (6–96) + align (text), zoom controls, effects: rounded (radius 2–64) + bottom fade (height 8–512) checkboxes/spins. Wire to the canvas tool state + `apply_effects` preview.
- [ ] Screenshot + UI-review the toolbar. Commit — `M3: editor toolbar (tools, style, zoom, effects)`.

---

## Task 14: Save / flatten + sidecar (integration, TDD where possible)

**Files:** `src/lib/editor/*` + `save_sidecar`/`flatten_save` commands.
- [ ] On save: flatten the stage (`stage.toCanvas()` at base resolution → PNG bytes → `flatten_save(path, bytes)` writes the library PNG); write the sidecar via `save_sidecar(path, { version:1, bases, items: items.map(serializeItem), effects })`. Mark history clean.
- [ ] On open: `load_sidecar(path)` → rebuild items via `deserializeItem`; restore step counter to `max(number)+1`; pixelate/blur re-request patches from Rust.
- [ ] Round-trip test (Vitest + a Rust integration check): save a doc with one of each item, reload, assert the item list serializes identically — the parity guarantee.
- [ ] **Commit** — `M3: save/flatten + sidecar round-trip (library interchange with Python)`.

---

## Task 15: M3 exit verification

- [ ] `cargo test --workspace` + `npm run test` green (editor model + imageops + tools).
- [ ] `npm run build` clean; `npm run test:ui -- capture` (+ an editor shot) regenerate.
- [ ] UI-review loop over the editor shots (toolbar + each tool family) returns 0 blockers.
- [ ] Manual note (display run): open a capture, draw each tool, undo/redo, crop, save, reopen — items persist; verify a sidecar written by Python (if available) opens in the new editor and vice versa.
- [ ] Tag — `git tag m3-editor && git commit --allow-empty -m "M3 complete: Konva editor (14 tools) green"`.

---

## Self-Review notes (author)

- **Spec coverage:** all 14 tools (contract table + Tasks 5–12) ✓; transform order ✓ (T1/T3); undo/redo ✓ (T3); zoom/select/transform ✓ (T4); destructive crop/cutout + base stack ✓ (T2/T11/T12); pixelate/blur via Rust pixels ✓ (T2/T10); effects ✓ (T2/T13); save/flatten/sidecar parity ✓ (T14); oracle tests ported ✓ (T1/T2/T3 + per-tool).
- **Why Rust for pixels:** pixelate/blur/crop/cutout/effects need real image processing on the base; doing it in Rust (reusing M2's `image` dep) keeps one source of truth and matches `imageops.py` outputs. Konva renders vector annotations; raster ops round-trip through Tauri commands.
- **Decomposition:** the 14 tools are grouped by shared mechanics into ~8 tasks to avoid copy-paste while keeping each independently testable + screenshot-critiqued. Each still has its own failing test asserting the exact serialized JSON.
- **Known risks:** (1) Konva `Transformer` rotation/origin must reproduce the Python origin→rotation→pos order so saved geometry matches on reopen (locked by T3's exactness test); (2) text inline-editing UX (HTML overlay over canvas) is the fiddliest tool; (3) flatten resolution must equal the base image pixel size, not the zoomed view.
```
