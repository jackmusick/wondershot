<script lang="ts">
  import { onMount } from 'svelte';
  import type Konva from 'konva';
  import { assetSrc, ipcInvoke } from '$lib/ipc';
  import { activeTool, toolForKey, type ToolId } from './tools';
  import type { Item, Vec2 } from './model';
  import { History } from './history';
  import { drawStyle, type DrawStyle } from './style';
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
  import type { TextItem } from './model';

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
  }

  // --- Annotation model + undo/redo history ---
  let items: Item[] = $state([]);
  const history = new History<Item[]>([]);

  /** Current draw style (color/width), kept in sync from the store. */
  let currentStyle: DrawStyle = { color: '#ff3b30ff', width: 4 };
  const unsubStyle = drawStyle.subscribe((s) => (currentStyle = s));

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
        history.push([...items]);
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
    history.push([...items]);
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

  function undo() {
    const snap = history.undo();
    if (snap === null) return;
    items = [...snap];
    rebuildAnnotations();
  }

  function redo() {
    const snap = history.redo();
    if (snap === null) return;
    items = [...snap];
    rebuildAnnotations();
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
    const placeholder: TextItem = textItem('', pos, { color: currentStyle.color }) ?? {
      type: 'text',
      text: '',
      color: currentStyle.color,
      family: 'sans-serif',
      point_size: 24,
      bold: true,
      text_width: -1,
      align: 'left',
      pos: [pos[0], pos[1]],
      rotation: 0,
      origin: [0, 0],
    };
    const node = makeTextNode(drawCtx(KonvaMod), placeholder);
    annotationsLayer.add(node);
    annotationsLayer.batchDraw();
    openTextEditor(node, (text) => {
      const item = textItem(text, pos, { color: currentStyle.color });
      if (!item) {
        node.destroy();
        annotationsLayer.batchDraw();
        return;
      }
      node.text(item.text);
      tagNode(node, item);
      items = [...items, item];
      history.push([...items]);
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
    history.push([...items]);
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
        history.push([...items]);
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
      history.push([...items]);
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
        history.push([...items]);
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
      if (pos) dispatchToolEvent('move', pos, currentTool);
    });
    stage.on('pointerup', () => {
      if (currentTool === 'select') return;
      const pos = stagePointer();
      if (pos) dispatchToolEvent('up', pos, currentTool);
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

        // Demo annotation so selection + transformer are screenshot-able.
        const demo = new Konva.Rect({
          x: imgW * 0.18,
          y: imgH * 0.28,
          width: imgW * 0.32,
          height: imgH * 0.34,
          stroke: '#ff5a4d',
          strokeWidth: 4,
          draggable: true,
        });
        annotationsLayer.add(demo);
        annotationsLayer.batchDraw();
        select(demo);

        fitToView();

        if (!destroyed && !cancelled) ready = true;
      };
      imageObj.src = src;
    })();

    // --- Keep the stage sized to the container ---
    const ro = new ResizeObserver(() => {
      if (!stage) return;
      stage.width(container.clientWidth);
      stage.height(container.clientHeight);
      stage.batchDraw();
    });
    ro.observe(container);

    return () => {
      cancelled = true;
      editTeardown?.();
      ro.disconnect();
      container.removeEventListener('wheel', onWheel);
      window.removeEventListener('keydown', onKeyDown);
      unsubTool();
      unsubStyle();
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
    background: var(--bg-content);
    overflow: hidden;
  }
</style>
