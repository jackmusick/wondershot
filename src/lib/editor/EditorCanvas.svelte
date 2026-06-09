<script lang="ts">
  import { onMount } from 'svelte';
  import type Konva from 'konva';
  import { assetSrc, ipcInvoke } from '$lib/ipc';
  import { activeTool, toolForKey, type ToolId } from './tools';
  import type { Item, Vec2 } from './model';
  import { History } from './history';
  import { drawStyle, textStyle, type DrawStyle, type TextStyle } from './style';
  import { zoomApi, saveApi, bgApi, viewInfo } from './zoom';
  import { drawTools, type DrawCtx } from './tools/index';
  import { WS_NODE_NAME, nodeToItemRef, tagNode } from './tools/arrowLine';
  // Side-effect import: registers the rect/ellipse/highlight box-shape tools
  // into `drawTools`. Box tools are NOT in DRAG_ONLY_TYPES, so they get the
  // full resize/rotate Transformer.
  import './tools/boxShapes';
  // Side-effect import: registers the freehand (pen) tool into `drawTools`.
  // Freehand is a DRAG_ONLY_TYPE, like arrow/line.
  import './tools/freehand';
  // Side-effect import: registers the text tool. Text placement + inline
  // editing is driven by EditorCanvas (the textarea overlay below), since the
  // tool can't own DOM. Text is NOT in DRAG_ONLY_TYPES — it gets the box
  // Transformer, and fromNode bakes the scale into point_size.
  import './tools/text';
  import { textItem, makeTextNode } from './tools/text';
  // Side-effect import: registers the step (numbered badge) tool. Step is
  // click-placed by EditorCanvas (which derives the next number from items[]),
  // like text. Step is NOT in DRAG_ONLY_TYPES — it gets the box Transformer, and
  // fromNode bakes the scale into `radius`.
  import './tools/step';
  import { stepItem, nextStepNumber } from './tools/step';
  // Side-effect import: registers the pixelate + blur tools. These draw a box
  // and display a Rust-computed processed patch of the base image (async fill
  // via ctx.patch below). NOT in DRAG_ONLY_TYPES — they get the box Transformer.
  import './tools/redact';
  // Destructive base-image ops (crop, cutout V/H). These don't add items —
  // they flatten the canvas, transform the base, clear annotations, and are
  // undoable via the base-aware history snapshot below.
  import {
    cropCanvas,
    cutoutVCanvas,
    cutoutHCanvas,
    type Rect4,
  } from './tools/destructive';
  import type { TextItem } from './model';
  import { serializeItem, deserializeItem } from './model';
  import { effects, type Effects } from './effects';
  import { get } from 'svelte/store';

  let { path }: { path: string } = $props();

  let ready = $state(false);
  let container: HTMLDivElement;
  let stage: Konva.Stage | null = null;
  let baseLayer: Konva.Layer;
  let annotationsLayer: Konva.Layer;
  let overlayLayer: Konva.Layer;
  let transformer: Konva.Transformer;
  let imageNode: Konva.Image | null = null;

  const MIN_SCALE = 0.05;
  const MAX_SCALE = 16;

  /** The image's natural pixel size — the stage's internal coordinate space. */
  let imgW = 0;
  let imgH = 0;

  /** Compute the fit-to-view scale (never upscaling past 1.0). */
  function fitScale(): number {
    if (!container || !imgW || !imgH) return 1;
    return Math.min(1, container.clientWidth / imgW, container.clientHeight / imgH);
  }

  /** Apply a scale and center the image within the container. */
  function applyScale(scale: number) {
    if (!stage) return;
    stage.scale({ x: scale, y: scale });
    const cw = container.clientWidth;
    const ch = container.clientHeight;
    stage.position({ x: (cw - imgW * scale) / 2, y: (ch - imgH * scale) / 2 });
    stage.batchDraw();
    viewInfo.set({ width: imgW, height: imgH, zoom: scale });
  }

  function fitToView() {
    applyScale(fitScale());
  }

  function actualSize() {
    applyScale(1);
  }

  /** Zoom about the pointer, clamped to [MIN_SCALE, MAX_SCALE]. */
  function zoomAt(pointer: { x: number; y: number }, factor: number) {
    if (!stage) return;
    const oldScale = stage.scaleX();
    let newScale = oldScale * factor;
    newScale = Math.max(MIN_SCALE, Math.min(MAX_SCALE, newScale));
    if (newScale === oldScale) return;
    const mousePointTo = {
      x: (pointer.x - stage.x()) / oldScale,
      y: (pointer.y - stage.y()) / oldScale,
    };
    stage.scale({ x: newScale, y: newScale });
    stage.position({
      x: pointer.x - mousePointTo.x * newScale,
      y: pointer.y - mousePointTo.y * newScale,
    });
    stage.batchDraw();
    viewInfo.set({ width: imgW, height: imgH, zoom: newScale });
  }

  // --- Annotation model + undo/redo history ---
  // The editor's undoable state is BOTH the base image and the items[].
  // Destructive ops (crop/cutout) change the base, so the history snapshots
  // both. `baseSrc` is a data URL (or the original image src) of the current
  // base image; `currentBaseSrc` tracks it and is folded into every push.
  interface EditorSnapshot {
    baseSrc: string;
    items: Item[];
  }
  let items: Item[] = $state([]);
  let currentBaseSrc = '';
  const history = new History<EditorSnapshot>({ baseSrc: '', items: [] });

  /**
   * Pre-op flattened images (data URLs), one per destructive op, in order.
   * T14 (save) persists these as the sidecar base stack. Exposed as a
   * component variable so the save path can read it.
   */
  let basePushes: string[] = $state([]);
  export function getBasePushes(): string[] {
    return basePushes;
  }

  /** Push the current base+items state onto the history stack. */
  function pushHistory() {
    history.push({ baseSrc: currentBaseSrc, items: [...items] });
    scheduleAutosave();
  }

  // Autosave: the Qt editor had no Save button — edits persist automatically.
  // Debounced so a burst of edits writes once; save() updates both the flattened
  // library PNG (thumbnail/display) and the editable sidecar (base.0 + items).
  let autosaveTimer: ReturnType<typeof setTimeout> | null = null;
  function scheduleAutosave() {
    if (autosaveTimer) clearTimeout(autosaveTimer);
    autosaveTimer = setTimeout(() => {
      autosaveTimer = null;
      if (!destroyed) void save();
    }, 600);
  }

  /** Current draw style (color/width), kept in sync from the store. */
  let currentStyle: DrawStyle = { color: '#ff3b30ff', width: 4 };
  const unsubStyle = drawStyle.subscribe((s) => (currentStyle = s));

  /** Current text defaults (font size / align), kept in sync from the store. */
  let currentTextStyle: TextStyle = { point_size: 24, align: 'left' };
  const unsubTextStyle = textStyle.subscribe((s) => (currentTextStyle = s));

  /**
   * Fetch a Rust-computed processed patch (pixelate/blur) for a region of the
   * base image and return it as a `data:image/png;base64,…` URL. The backend
   * returns the bare base64 body; we add the prefix. Returns null on any error
   * (or in the mock) so the redact tool keeps its gray placeholder.
   */
  async function fetchPatch(
    kind: 'pixelate' | 'blur',
    rect: [number, number, number, number],
    param: number,
  ): Promise<string | null> {
    try {
      const cmd = kind === 'pixelate' ? 'pixelate_patch' : 'blur_patch';
      const args =
        kind === 'pixelate' ? { path, rect, block: param } : { path, rect, radius: param };
      const b64 = await ipcInvoke<string>(cmd, args);
      if (!b64) return null;
      return `data:image/png;base64,${b64}`;
    } catch {
      return null;
    }
  }

  /** Build the DrawCtx handed to every tool. */
  function drawCtx(Konva: typeof import('konva').default): DrawCtx {
    return { layer: annotationsLayer, Konva, style: currentStyle, patch: fetchPatch };
  }

  let KonvaMod: typeof import('konva').default | null = null;

  /**
   * Route pointer phases to the active drawing tool. begin on down, update on
   * move, finish on up. A non-null finish appends the Item to the model and
   * pushes a history snapshot; the finished Konva node stays on the
   * annotations layer (now selectable by the select tool). Every later tool
   * reuses this same dispatch — it keys purely off `drawTools[tool]`.
   */
  function dispatchToolEvent(
    phase: 'down' | 'move' | 'up',
    pos: { x: number; y: number },
    tool: ToolId,
  ) {
    if (!KonvaMod) return;
    const dt = drawTools[tool];
    if (!dt) return;
    const ctx = drawCtx(KonvaMod);
    if (phase === 'down') {
      dt.begin(ctx, pos.x, pos.y);
    } else if (phase === 'move') {
      dt.update(ctx, pos.x, pos.y);
    } else {
      const item = dt.finish(ctx, pos.x, pos.y);
      if (item) {
        items = [...items, item];
        pushHistory();
      }
    }
  }

  /**
   * Persist a transformed Konva node back into the `items` model + history.
   * Looks up the node's tagged item, asks its tool to read geometry back via
   * `fromNode` (which bakes Transformer scale and resets the node), replaces the
   * item in `items[]`, pushes a history snapshot, and re-tags the node so a
   * subsequent drag/transform compounds from the new baseline. No-op if the
   * node isn't tagged or its tool can't be resolved.
   */
  function persistNode(node: Konva.Node) {
    if (!KonvaMod) return;
    const prev = nodeToItemRef(node);
    if (!prev) return;
    const dt = drawTools[prev.type];
    if (!dt) return;
    const idx = items.indexOf(prev);
    if (idx === -1) return;
    const ctx = drawCtx(KonvaMod);
    const updated = dt.fromNode(ctx, node, prev);
    tagNode(node, updated);
    const next = [...items];
    next[idx] = updated;
    items = next;
    pushHistory();
    annotationsLayer.batchDraw();
    overlayLayer.batchDraw();
  }

  /**
   * Rebuild the annotations layer from the current `items` model. Destroys all
   * tool-created nodes (tagged with WS_NODE_NAME) and re-`render`s each item
   * via its tool module. Used after undo/redo. The transformer's selection is
   * cleared since the nodes it pointed at no longer exist.
   */
  function rebuildAnnotations() {
    if (!KonvaMod || !annotationsLayer) return;
    transformer.nodes([]);
    annotationsLayer.find(`.${WS_NODE_NAME}`).forEach((n) => n.destroy());
    const ctx = drawCtx(KonvaMod);
    for (const item of items) {
      const dt = drawTools[item.type];
      if (dt) dt.render(ctx, item);
    }
    annotationsLayer.batchDraw();
    overlayLayer.batchDraw();
  }

  /**
   * Set the base Konva.Image to `src`, loading it if it differs from the
   * currently-displayed base. Updates imgW/imgH and re-fits the view only when
   * the natural dimensions change (so an undo that doesn't resize the base
   * leaves zoom/pan untouched). `onReady` fires after the new image is in place.
   */
  function setBaseImage(src: string, onReady?: () => void) {
    if (!KonvaMod || !stage) return;
    currentBaseSrc = src;
    if (!src) {
      onReady?.();
      return;
    }
    // No-op fast path: the displayed base already matches.
    if (imageNode && imageNode.image() && (imageNode.image() as HTMLImageElement).src === src) {
      onReady?.();
      return;
    }
    const img = new Image();
    img.onload = () => {
      if (!stage || !KonvaMod) return;
      const dimsChanged = img.naturalWidth !== imgW || img.naturalHeight !== imgH;
      imgW = img.naturalWidth;
      imgH = img.naturalHeight;
      if (imageNode) imageNode.destroy();
      imageNode = new KonvaMod.Image({ image: img, x: 0, y: 0, width: imgW, height: imgH });
      baseLayer.add(imageNode);
      baseLayer.batchDraw();
      if (dimsChanged) fitToView();
      onReady?.();
    };
    img.src = src;
  }

  /** Restore an editor snapshot: base image + items + annotation nodes. */
  function restoreSnapshot(snap: EditorSnapshot) {
    items = [...snap.items];
    setBaseImage(snap.baseSrc, () => rebuildAnnotations());
  }

  /**
   * Flatten the base + annotations into a single PNG at the BASE image's
   * natural pixel resolution (NOT the zoomed view). Temporarily resets the
   * stage to scale 1 / position 0, hides the overlay (transformer handles),
   * exports the base+annotation region [0,0,imgW,imgH] at pixelRatio 1, then
   * restores the prior scale/position. Returns a data URL whose dimensions
   * equal (imgW, imgH).
   */
  function flattenStage(): string {
    if (!stage) return currentBaseSrc;
    const prevScale = stage.scaleX();
    const prevPos = stage.position();
    const overlayVisible = overlayLayer.visible();
    overlayLayer.visible(false);
    stage.scale({ x: 1, y: 1 });
    stage.position({ x: 0, y: 0 });
    stage.batchDraw();
    const url = stage.toDataURL({
      x: 0,
      y: 0,
      width: imgW,
      height: imgH,
      pixelRatio: 1,
    });
    // Restore the view exactly as it was.
    stage.scale({ x: prevScale, y: prevScale });
    stage.position(prevPos);
    overlayLayer.visible(overlayVisible);
    stage.batchDraw();
    return url;
  }

  /** Strip the `data:image/png;base64,` prefix, leaving the bare base64 body
   *  the Rust commands expect. A no-prefix string is returned unchanged. */
  function bareBase64(dataUrl: string): string {
    const comma = dataUrl.indexOf(',');
    return comma === -1 ? dataUrl : dataUrl.slice(comma + 1);
  }

  /**
   * Save (T14 parity guarantee). Writes three artifacts so the Python app reads
   * the same `.wondershot` sidecar and the editor reopens losslessly:
   *   1. the FLATTENED library PNG (annotations baked in) via `flatten_save`;
   *   2. the sidecar JSON {version, bases, items, effects} via `save_sidecar`;
   *   3. `base.0` = the current editable base via `write_base`, so reopen shows
   *      base + editable annotations (NOT the flattened image).
   * For M3 `bases:1` and only `base.0` is written — the multi-base re-edit stack
   * (getBasePushes) is DEFERRED. Marks history clean so the dirty indicator clears.
   */
  export async function save(): Promise<void> {
    const flat = flattenStage();
    await ipcInvoke('flatten_save', { path, pngB64: bareBase64(flat) });
    const doc = {
      version: 1,
      bases: 1,
      items: items.map(serializeItem),
      effects: get(effects),
    };
    await ipcInvoke('save_sidecar', { path, doc });
    if (currentBaseSrc) {
      await ipcInvoke('write_base', { path, n: 0, pngB64: bareBase64(currentBaseSrc) });
    }
    history.markClean();
  }

  /**
   * Open flow: read the sidecar for `path`. If a doc exists with bases>=1 and
   * base.0 loads successfully, restore items + effects + the editable base.
   * If bases is falsy OR base.0 is missing (null), mirror Python's fallback:
   * drop items and keep the flattened library PNG as-is (annotations are baked
   * in). No sidecar → no-op (the library PNG base, loaded on mount, stays as-is).
   * Re-seeds history clean to the restored state.
   */
  async function loadSidecar(): Promise<void> {
    let doc: any = null;
    try {
      doc = await ipcInvoke<any>('load_sidecar', { path });
    } catch {
      return;
    }
    if (!doc) return;

    if (doc.effects && typeof doc.effects === 'object') {
      effects.set(doc.effects as Effects);
    }

    let base64: string | null = null;
    try {
      base64 = await ipcInvoke<string | null>('read_base', { path, n: 0 });
    } catch {
      base64 = null;
    }

    // Guard: only restore items if BOTH bases is truthy AND base.0 loaded.
    // Mirrors Python (editor.py:516,519-520): missing/falsy bases or absent
    // base image → drop items, keep the flattened library PNG (annotations
    // already baked in). Normal path (base.0 present + bases>=1) unchanged.
    const shouldRestoreItems = doc.bases && base64 !== null;
    if (shouldRestoreItems) {
      items = (doc.items ?? [])
        .map((j: any) => deserializeItem(j))
        .filter((i: Item | null): i is Item => i !== null);
    }

    const apply = () => {
      rebuildAnnotations();
      history.reset({ baseSrc: currentBaseSrc, items: [...items] });
    };
    if (base64) {
      setBaseImage(`data:image/png;base64,${base64}`, apply);
    } else {
      apply();
    }
  }

  /**
   * Apply a destructive op: take the pre-op flattened image and a builder that
   * produces the new base canvas. Records the base push, swaps in the new base,
   * clears all annotations, re-fits the (resized) view, and pushes history.
   */
  function applyDestructive(buildNewBase: (flatImg: HTMLImageElement) => HTMLCanvasElement) {
    if (!stage || imgW === 0 || imgH === 0) return;
    const flat = flattenStage();
    const flatImg = new Image();
    flatImg.onload = () => {
      const newCanvas = buildNewBase(flatImg);
      const newSrc = newCanvas.toDataURL('image/png');
      // The pre-op flattened image is the base push for the sidecar stack.
      basePushes = [...basePushes, flat];
      // Clear annotations — they are baked into the flattened base.
      items = [];
      rebuildAnnotations();
      // Swap in the new base (dims change → setBaseImage re-fits).
      setBaseImage(newSrc, () => {
        rebuildAnnotations();
        pushHistory();
      });
    };
    flatImg.src = flat;
  }

  /**
   * AI background removal (M5 T3). Runs the u2net command on the ORIGINAL
   * library image (`path`), which returns a base64 PNG with the background made
   * transparent. Unlike the destructive ops, this swaps in the new base while
   * KEEPING annotations (mirrors Python editor.py bg_done): the current base is
   * recorded as a base push (so undo + the sidecar base stack work), then the
   * new alpha'd base is loaded and history is pushed. Throws if the model /
   * runtime is unavailable so the toolbar can surface the failure.
   */
  async function removeBackground(): Promise<void> {
    if (!stage || imgW === 0 || imgH === 0) return;
    const b64 = await ipcInvoke<string>('remove_background', { path });
    if (!b64) throw new Error('background removal returned no image');
    const newSrc = `data:image/png;base64,${b64}`;
    // Record the current base for the sidecar base stack (KEEP annotations).
    basePushes = [...basePushes, currentBaseSrc];
    setBaseImage(newSrc, () => {
      rebuildAnnotations();
      pushHistory();
    });
  }

  /** Crop the canvas to `rect` ([x, y, w, h]) in base-image coordinates. */
  function doCrop(rect: Rect4) {
    if (rect[2] <= 0 || rect[3] <= 0) return;
    applyDestructive((flatImg) => cropCanvas(flatImg, rect));
  }

  /** Remove a full-height vertical band [x1, x2) (join left + right). */
  function doCutoutV(x1: number, x2: number) {
    const a = Math.min(x1, x2);
    const b = Math.max(x1, x2);
    if (b - a <= 0) return;
    applyDestructive((flatImg) => cutoutVCanvas(flatImg, imgW, imgH, a, b));
  }

  /** Remove a full-width horizontal band [y1, y2) (join top + bottom). */
  function doCutoutH(y1: number, y2: number) {
    const a = Math.min(y1, y2);
    const b = Math.max(y1, y2);
    if (b - a <= 0) return;
    applyDestructive((flatImg) => cutoutHCanvas(flatImg, imgW, imgH, a, b));
  }

  // --- Destructive drag state + preview rectangle ---
  // crop drags a box; cutout-v drags an x-range (full-height band); cutout-h
  // drags a y-range (full-width band). A temporary Konva.Rect on the overlay
  // layer previews the region during the drag; it's removed on finish.
  let destStart: { x: number; y: number } | null = null;
  let destPreview: Konva.Rect | null = null;

  function clamp(v: number, lo: number, hi: number): number {
    return Math.max(lo, Math.min(hi, v));
  }

  /** Compute the destructive region [x, y, w, h] in base coords for the active
   *  tool, given the drag start and current pointer. */
  function destRect(cur: { x: number; y: number }, tool: ToolId): Rect4 {
    if (!destStart) return [0, 0, 0, 0];
    const sx = clamp(destStart.x, 0, imgW);
    const sy = clamp(destStart.y, 0, imgH);
    const cx = clamp(cur.x, 0, imgW);
    const cy = clamp(cur.y, 0, imgH);
    const x = Math.min(sx, cx);
    const y = Math.min(sy, cy);
    const w = Math.abs(cx - sx);
    const h = Math.abs(cy - sy);
    if (tool === 'cutout-v') return [x, 0, w, imgH]; // full-height band
    if (tool === 'cutout-h') return [0, y, imgW, h]; // full-width band
    return [x, y, w, h]; // crop box
  }

  function destBegin(pos: { x: number; y: number }, _tool: ToolId) {
    if (!KonvaMod) return;
    destStart = pos;
    destPreview = new KonvaMod.Rect({
      x: 0,
      y: 0,
      width: 0,
      height: 0,
      fill: 'rgba(0, 122, 255, 0.18)',
      stroke: '#007aff',
      strokeWidth: 1,
      listening: false,
      strokeScaleEnabled: false,
    });
    overlayLayer.add(destPreview);
    overlayLayer.batchDraw();
  }

  function destUpdate(pos: { x: number; y: number }, tool: ToolId) {
    if (!destStart || !destPreview) return;
    const [x, y, w, h] = destRect(pos, tool);
    destPreview.setAttrs({ x, y, width: w, height: h });
    overlayLayer.batchDraw();
  }

  function destFinish(pos: { x: number; y: number }, tool: ToolId) {
    if (!destStart) return;
    const [x, y, w, h] = destRect(pos, tool);
    destPreview?.destroy();
    destPreview = null;
    destStart = null;
    overlayLayer.batchDraw();
    if (tool === 'crop') doCrop([x, y, w, h]);
    else if (tool === 'cutout-v') doCutoutV(x, x + w);
    else if (tool === 'cutout-h') doCutoutH(y, y + h);
  }

  const DESTRUCTIVE_TOOLS = new Set<ToolId>(['crop', 'cutout-v', 'cutout-h']);

  function undo() {
    const snap = history.undo();
    if (snap === null) return;
    restoreSnapshot(snap);
  }

  function redo() {
    const snap = history.redo();
    if (snap === null) return;
    restoreSnapshot(snap);
  }

  /** Pointer position in stage (image) coordinates. */
  function stagePointer(): { x: number; y: number } | null {
    if (!stage) return null;
    const p = stage.getPointerPosition();
    if (!p) return null;
    const scale = stage.scaleX();
    return { x: (p.x - stage.x()) / scale, y: (p.y - stage.y()) / scale };
  }

  /** Item types edited by dragging the whole node, not a box transformer. */
  const DRAG_ONLY_TYPES = new Set(['arrow', 'line', 'freehand']);

  // --- Inline text editor (HTML <textarea> overlay) ---
  // A text annotation is edited via a real <textarea> positioned over the
  // canvas at the node's screen location. Only one editor is open at a time.
  // `editTeardown` removes the textarea + its listeners; it is called on
  // commit, on opening a new editor, and on destroy.
  let editTeardown: (() => void) | null = null;

  /** Screen (container-local) position of an image-space point, via the stage
   *  transform: screen = imagePos * scale + stagePosition. */
  function imageToScreen(p: Vec2): { x: number; y: number } {
    if (!stage) return { x: 0, y: 0 };
    const scale = stage.scaleX();
    return { x: p[0] * scale + stage.x(), y: p[1] * scale + stage.y() };
  }

  /**
   * Open the inline text editor over `node` (a Konva.Text on the annotations
   * layer). `onCommit(text)` receives the trimmed-or-raw working string when the
   * user commits (blur, Escape, or Enter without Shift); the caller decides
   * whether to keep, update, or discard the node based on emptiness.
   */
  function openTextEditor(node: Konva.Text, onCommit: (text: string) => void) {
    if (!stage) return;
    editTeardown?.(); // close any prior editor first

    const scale = stage.scaleX();
    const screen = imageToScreen([node.x(), node.y()]);
    node.hide();
    annotationsLayer.batchDraw();

    const ta = document.createElement('textarea');
    container.appendChild(ta);
    ta.value = node.text();
    ta.style.position = 'absolute';
    ta.style.left = `${screen.x}px`;
    ta.style.top = `${screen.y}px`;
    ta.style.margin = '0';
    ta.style.padding = '0';
    ta.style.border = 'none';
    ta.style.outline = 'none';
    ta.style.background = 'transparent';
    ta.style.overflow = 'hidden';
    ta.style.resize = 'none';
    ta.style.lineHeight = '1';
    ta.style.whiteSpace = 'pre';
    ta.style.fontSize = `${node.fontSize() * scale}px`;
    ta.style.fontFamily = node.fontFamily();
    ta.style.fontWeight = node.fontStyle().includes('bold') ? 'bold' : 'normal';
    ta.style.color = node.fill() as string;
    ta.style.transformOrigin = 'left top';
    ta.style.zIndex = '10';
    ta.style.minWidth = '1ch';

    let committed = false;
    const commit = () => {
      if (committed) return;
      committed = true;
      const text = ta.value;
      teardown();
      onCommit(text);
    };
    const teardown = () => {
      ta.removeEventListener('blur', commit);
      ta.removeEventListener('keydown', onKey);
      ta.remove();
      node.show();
      annotationsLayer.batchDraw();
      if (editTeardown === teardown) editTeardown = null;
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' || (e.key === 'Enter' && !e.shiftKey)) {
        e.preventDefault();
        commit();
      }
    };
    ta.addEventListener('blur', commit);
    ta.addEventListener('keydown', onKey);
    editTeardown = teardown;

    ta.focus();
    ta.select();
  }

  /**
   * Place a new text annotation at image-space `pos` and open the editor. On
   * commit: if the text is non-empty, build the item via textItem(), set it on
   * the node, tag it, append to items + history; if empty, destroy the node.
   */
  function placeText(pos: Vec2) {
    if (!KonvaMod) return;
    const textOpts = {
      color: currentStyle.color,
      point_size: currentTextStyle.point_size,
      align: currentTextStyle.align,
    };
    const placeholder: TextItem = textItem('', pos, textOpts) ?? {
      type: 'text',
      text: '',
      color: currentStyle.color,
      family: 'sans-serif',
      point_size: currentTextStyle.point_size,
      bold: true,
      text_width: -1,
      align: currentTextStyle.align,
      pos: [pos[0], pos[1]],
      rotation: 0,
      origin: [0, 0],
    };
    const node = makeTextNode(drawCtx(KonvaMod), placeholder);
    annotationsLayer.add(node);
    annotationsLayer.batchDraw();
    openTextEditor(node, (text) => {
      const item = textItem(text, pos, textOpts);
      if (!item) {
        node.destroy();
        annotationsLayer.batchDraw();
        return;
      }
      node.text(item.text);
      tagNode(node, item);
      items = [...items, item];
      pushHistory();
      annotationsLayer.batchDraw();
    });
  }

  /**
   * Stamp a new numbered badge at image-space `pos`. The number is DERIVED from
   * the current items[] (`nextStepNumber`) each time — no separate counter — so
   * undo/redo and load reuse/continue numbering automatically. Renders the badge
   * node, tags it, and appends to items + history.
   */
  function placeStep(pos: Vec2) {
    if (!KonvaMod) return;
    const n = nextStepNumber(items);
    const item = stepItem(n, pos, currentStyle.color);
    const node = drawTools.step?.render(drawCtx(KonvaMod), item);
    if (!node) return;
    tagNode(node, item);
    items = [...items, item];
    pushHistory();
    annotationsLayer.batchDraw();
  }

  /** Re-open the editor for an existing text node (double-click). On commit,
   *  update the tagged item in place (or remove it if emptied). */
  function editText(node: Konva.Text) {
    const prev = nodeToItemRef(node) as TextItem | undefined;
    if (!prev) return;
    openTextEditor(node, (text) => {
      const idx = items.indexOf(prev);
      const item = textItem(text, prev.pos, {
        color: prev.color,
        family: prev.family,
        point_size: prev.point_size,
        bold: prev.bold,
        text_width: prev.text_width,
        align: prev.align,
      });
      if (!item) {
        if (idx !== -1) items = items.filter((i) => i !== prev);
        node.destroy();
        transformer.nodes([]);
        annotationsLayer.batchDraw();
        overlayLayer.batchDraw();
        pushHistory();
        return;
      }
      node.text(item.text);
      tagNode(node, item);
      if (idx !== -1) {
        const next = [...items];
        next[idx] = item;
        items = next;
      }
      annotationsLayer.batchDraw();
      pushHistory();
    });
  }

  function select(node: Konva.Node | null) {
    if (!transformer) return;
    // Two-point items (arrow/line) are moved by dragging — they show no resize
    // or rotate handles, matching the Python editor. Other items get the full
    // box transformer. The node stays draggable either way.
    const item = node ? nodeToItemRef(node) : undefined;
    const dragOnly = !!item && DRAG_ONLY_TYPES.has(item.type);
    transformer.resizeEnabled(!dragOnly);
    transformer.rotateEnabled(!dragOnly);
    transformer.nodes(node ? [node] : []);
    overlayLayer.batchDraw();
  }

  function deleteSelected() {
    const nodes = transformer.nodes();
    if (nodes.length) {
      // Look up each selected node's item and remove from model if found.
      let changed = false;
      nodes.forEach((n) => {
        const ref = nodeToItemRef(n);
        if (ref) {
          items = items.filter((i) => i !== ref);
          changed = true;
        }
        n.destroy();
      });
      // If any items were removed, push a history snapshot.
      if (changed) {
        pushHistory();
      }
      transformer.nodes([]);
      annotationsLayer.batchDraw();
      overlayLayer.batchDraw();
    }
  }

  let currentTool: ToolId = 'select';
  const unsubTool = activeTool.subscribe((t) => (currentTool = t));

  function isEditableTarget(t: EventTarget | null): boolean {
    const el = t as HTMLElement | null;
    if (!el) return false;
    const tag = el.tagName;
    return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable;
  }

  function onKeyDown(e: KeyboardEvent) {
    if (isEditableTarget(e.target)) return;
    if (e.key === 'Delete' || e.key === 'Backspace') {
      deleteSelected();
      e.preventDefault();
      return;
    }
    if (e.ctrlKey || e.metaKey) {
      const k = e.key.toLowerCase();
      if (k === 's') { e.preventDefault(); void save(); return; }
      if (k === 'z' && e.shiftKey) { redo(); e.preventDefault(); return; }
      if (k === 'z') { undo(); e.preventDefault(); return; }
      if (k === 'y') { redo(); e.preventDefault(); return; }
      if (e.key === '0') { actualSize(); e.preventDefault(); return; }
      if (e.key === '9') { fitToView(); e.preventDefault(); return; }
      return;
    }
    const tool = toolForKey(e.key, e.shiftKey);
    if (tool) {
      activeTool.set(tool);
      e.preventDefault();
    }
  }

  let destroyed = false;
  let cleanup: (() => void) | null = null;

  onMount(() => {
    // Konva is imported dynamically so it never loads during SSR — its
    // top-level module resolves to a Node build that requires the optional
    // `canvas` package, which we don't ship.
    import('konva').then(({ default: Konva }) => {
      if (destroyed) return;
      cleanup = build(Konva);
    });
    return () => {
      destroyed = true;
      cleanup?.();
    };
  });

  function build(Konva: typeof import('konva').default): () => void {
    KonvaMod = Konva;
    stage = new Konva.Stage({
      container,
      width: container.clientWidth,
      height: container.clientHeight,
    });
    baseLayer = new Konva.Layer();
    annotationsLayer = new Konva.Layer();
    overlayLayer = new Konva.Layer();
    stage.add(baseLayer);
    stage.add(annotationsLayer);
    stage.add(overlayLayer);

    transformer = new Konva.Transformer({
      rotateEnabled: true,
      ignoreStroke: true,
    });
    overlayLayer.add(transformer);

    // --- Pointer handling: select tool vs. drawing tools ---
    stage.on('pointerdown', (e) => {
      if (currentTool === 'select') {
        if (e.target === stage || e.target === imageNode) {
          select(null);
          return;
        }
        // only annotation-layer nodes are selectable
        if (e.target.getLayer() === annotationsLayer) {
          select(e.target);
        }
        return;
      }
      // Text is click-placed with an inline editor, not dragged to size.
      if (currentTool === 'text') {
        // Clicking an existing text node re-opens its editor instead of placing
        // a new one stacked on top.
        if (e.target.getLayer() === annotationsLayer && e.target.getClassName() === 'Text') {
          editText(e.target as Konva.Text);
          return;
        }
        const tp = stagePointer();
        if (tp) placeText([tp.x, tp.y]);
        return;
      }
      // Step is click-placed (stamp the next badge), not dragged to size.
      if (currentTool === 'step') {
        const tp = stagePointer();
        if (tp) placeStep([tp.x, tp.y]);
        return;
      }
      // Destructive ops (crop/cutout) drag a box/band on the overlay layer.
      if (DESTRUCTIVE_TOOLS.has(currentTool)) {
        const tp = stagePointer();
        if (tp) destBegin(tp, currentTool);
        return;
      }
      const pos = stagePointer();
      if (pos) dispatchToolEvent('down', pos, currentTool);
    });
    // Double-clicking any text node re-opens its inline editor, regardless of
    // the active tool (e.g. while in select mode).
    stage.on('dblclick dbltap', (e) => {
      if (e.target.getLayer() === annotationsLayer && e.target.getClassName() === 'Text') {
        editText(e.target as Konva.Text);
      }
    });
    stage.on('pointermove', () => {
      if (currentTool === 'select') return;
      const pos = stagePointer();
      if (!pos) return;
      if (DESTRUCTIVE_TOOLS.has(currentTool)) {
        destUpdate(pos, currentTool);
        return;
      }
      dispatchToolEvent('move', pos, currentTool);
    });
    stage.on('pointerup', () => {
      if (currentTool === 'select') return;
      const pos = stagePointer();
      if (!pos) return;
      if (DESTRUCTIVE_TOOLS.has(currentTool)) {
        destFinish(pos, currentTool);
        return;
      }
      dispatchToolEvent('up', pos, currentTool);
    });

    // --- Persist transforms back to the model + history ---
    // Delegated on the annotations layer so it also covers nodes recreated by
    // rebuildAnnotations(). A `dragend` fires when the user finishes moving a
    // node; `transformend` when a box-transform (resize/rotate) completes.
    annotationsLayer.on('dragend', (e) => {
      if (e.target.hasName(WS_NODE_NAME)) persistNode(e.target);
    });
    transformer.on('transformend', () => {
      transformer.nodes().forEach((n) => {
        if (n.hasName(WS_NODE_NAME)) persistNode(n);
      });
    });

    // --- Zoom: Ctrl+wheel about the pointer ---
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return; // plain wheel = no-op for now
      e.preventDefault();
      const pointer = stage!.getPointerPosition();
      if (!pointer) return;
      const factor = e.deltaY < 0 ? 1.1 : 1 / 1.1;
      zoomAt(pointer, factor);
    };
    container.addEventListener('wheel', onWheel, { passive: false });

    // Expose zoom controls to the toolbar. zoomIn/zoomOut step about the
    // container center (mirroring the Ctrl+wheel factor); actual/fit reuse the
    // existing helpers.
    function zoomCenter(factor: number) {
      if (!stage) return;
      zoomAt({ x: container.clientWidth / 2, y: container.clientHeight / 2 }, factor);
    }
    zoomApi.set({
      zoomIn: () => zoomCenter(1.1),
      zoomOut: () => zoomCenter(1 / 1.1),
      zoomActual: actualSize,
      zoomFit: fitToView,
    });
    saveApi.set(save);

    // Background-removal bridge: probe the model once on mount; the toolbar
    // disables the button when the model is absent. Failures default to false.
    (async () => {
      let available = false;
      try {
        available = await ipcInvoke<boolean>('bg_model_available');
      } catch {
        available = false;
      }
      bgApi.set({ removeBackground, available });
    })();

    window.addEventListener('keydown', onKeyDown);

    // --- Load the base image ---
    let cancelled = false;
    (async () => {
      const src = await assetSrc(path);
      const imageObj = new Image();
      imageObj.onload = () => {
        if (cancelled || !stage) return;
        imgW = imageObj.naturalWidth;
        imgH = imageObj.naturalHeight;
        imageNode = new Konva.Image({ image: imageObj, x: 0, y: 0, width: imgW, height: imgH });
        baseLayer.add(imageNode);
        baseLayer.batchDraw();

        // Seed the base-aware history with the loaded base as the initial
        // snapshot, so undo can restore the original (pre-destructive) base.
        currentBaseSrc = src;
        history.reset({ baseSrc: src, items: [] });

        fitToView();

        if (!destroyed && !cancelled) ready = true;

        // Restore any saved sidecar (items + effects + editable base.0) on top
        // of the freshly-loaded library PNG. No sidecar → this is a no-op.
        void loadSidecar();
      };
      imageObj.src = src;
    })();

    // --- Keep the stage sized to the container AND re-center the image ---
    // Resizing only the stage canvas left the image pinned at its old offset
    // (looked frozen). Re-apply the current scale, which recenters; if the user
    // hasn't zoomed (still at fit), re-fit so the image grows/shrinks with the
    // window like the Qt editor.
    let lastW = container.clientWidth;
    let lastH = container.clientHeight;
    const ro = new ResizeObserver(() => {
      if (!stage) return;
      const w = container.clientWidth;
      const h = container.clientHeight;
      if (w === lastW && h === lastH) return;
      lastW = w;
      lastH = h;
      stage.width(w);
      stage.height(h);
      // Re-fit so the image expands/shrinks and stays centered with the window.
      fitToView();
    });
    ro.observe(container);

    // Test hook (dev / mock-IPC only): lets Playwright drive the canvas with
    // real mouse events and assert Konva state (items, current selection, the
    // transformer's handles, zoom) without a DOM representation of the scene.
    if (import.meta.env.DEV || import.meta.env.VITE_MOCK_IPC) {
      (window as unknown as { __wsEditor?: unknown }).__wsEditor = {
        stage,
        transformer,
        itemCount: () => items.length,
        items: () => items.map((i) => ({ ...i })),
        selectionCount: () => transformer.nodes().length,
        selectionHasHandles: () =>
          transformer.nodes().length > 0 && transformer.resizeEnabled(),
        // Actual rendered handles: Konva names the resize anchors and the
        // 'rotater'. If these aren't present/visible the user sees no corners.
        renderedAnchors: () =>
          transformer.isVisible()
            ? transformer.find('.rotater, .top-left, .top-right, .bottom-left, .bottom-right')
                .filter((n: any) => n.isVisible() && n.width() > 0).length
            : 0,
        scale: () => stage.scaleX(),
        ready: () => ready,
      };
    }

    return () => {
      cancelled = true;
      // Flush a pending autosave before the stage is destroyed (flattenStage is
      // synchronous, so the bake captures the live stage; the write completes
      // after unmount). Prevents losing an edit made just before switching.
      if (autosaveTimer) {
        clearTimeout(autosaveTimer);
        autosaveTimer = null;
        void save();
      }
      editTeardown?.();
      ro.disconnect();
      container.removeEventListener('wheel', onWheel);
      window.removeEventListener('keydown', onKeyDown);
      zoomApi.set(null);
      saveApi.set(null);
      bgApi.set(null);
      viewInfo.set(null);
      unsubTool();
      unsubStyle();
      unsubTextStyle();
      stage?.destroy();
      stage = null;
    };
  }
</script>

<div class="editor-canvas" bind:this={container} data-editor-ready={ready ? 'true' : 'false'}></div>

<style>
  .editor-canvas {
    position: relative;
    flex: 1;
    width: 100%;
    height: 100%;
    min-height: 0;
    background: var(--bg-app);
    overflow: hidden;
  }
</style>
