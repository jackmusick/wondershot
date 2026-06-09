<script lang="ts">
  import { onMount } from 'svelte';
  import type Konva from 'konva';
  import { assetSrc } from '$lib/ipc';
  import { activeTool, toolForKey, type ToolId } from './tools';

  let { path }: { path: string } = $props();

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

  /** Extension point — tools plug in here (M3 T5+). */
  function dispatchToolEvent(
    _phase: 'down' | 'move' | 'up',
    _pos: { x: number; y: number },
    _tool: ToolId,
  ) {
    // no-op for now; later tasks implement drawing per active tool
  }

  /** Pointer position in stage (image) coordinates. */
  function stagePointer(): { x: number; y: number } | null {
    if (!stage) return null;
    const p = stage.getPointerPosition();
    if (!p) return null;
    const scale = stage.scaleX();
    return { x: (p.x - stage.x()) / scale, y: (p.y - stage.y()) / scale };
  }

  function select(node: Konva.Node | null) {
    if (!transformer) return;
    transformer.nodes(node ? [node] : []);
    overlayLayer.batchDraw();
  }

  function deleteSelected() {
    const nodes = transformer.nodes();
    if (nodes.length) {
      nodes.forEach((n) => n.destroy());
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
      const pos = stagePointer();
      if (pos) dispatchToolEvent('down', pos, currentTool);
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
      ro.disconnect();
      container.removeEventListener('wheel', onWheel);
      window.removeEventListener('keydown', onKeyDown);
      unsubTool();
      stage?.destroy();
      stage = null;
    };
  }
</script>

<div class="editor-canvas" bind:this={container}></div>

<style>
  .editor-canvas {
    flex: 1;
    width: 100%;
    height: 100%;
    min-height: 0;
    background: var(--bg-content);
    overflow: hidden;
  }
</style>
