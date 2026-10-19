<script lang="ts">
  import { onMount } from 'svelte';
  import { emit } from '@tauri-apps/api/event';
  import { getCurrentWindow } from '@tauri-apps/api/window';
  import { ipcEmit, ipcInvoke, ipcListen } from '$lib/ipc';

  type Monitor = {
    id: number;
    x: number;
    y: number;
    width: number;
    height: number;
  };
  type WindowRect = Monitor & { title: string; windowId?: number };
  type Frame = { width: number; height: number; monitors?: Monitor[]; windows?: WindowRect[]; pngB64: string };
  type Point = { x: number; y: number };
  type ViewRect = { left: number; top: number; width: number; height: number };

  let frame = $state<Frame | null>(null);
  let error = $state('');
  let imgEl = $state<HTMLImageElement | undefined>();
  let dragStart = $state<Point | null>(null);
  let dragNow = $state<Point | null>(null);
  let hoverWindow = $state<WindowRect | null>(null);
  let selectedRect = $state<[number, number, number, number] | null>(null);
  let selectedTitle = $state('');
  let selectedWindowId = $state<number | null>(null);
  let viewRect = $state<ViewRect | null>(null);
  let mode = $state<'capture' | 'rect' | 'screen-capture' | 'screen-rect' | 'window-capture' | 'window-rect'>('capture');

  let box = $derived.by(() => {
    if (!dragStart || !dragNow) return null;
    const x = Math.min(dragStart.x, dragNow.x);
    const y = Math.min(dragStart.y, dragNow.y);
    const w = Math.abs(dragStart.x - dragNow.x);
    const h = Math.abs(dragStart.y - dragNow.y);
    return { x, y, w, h };
  });

  function imagePoint(e: PointerEvent): Point | null {
    if (!imgEl || !frame || !viewRect) return null;
    const r = viewRect;
    const x = Math.max(0, Math.min(frame.width, ((e.clientX - r.left) / r.width) * frame.width));
    const y = Math.max(0, Math.min(frame.height, ((e.clientY - r.top) / r.height) * frame.height));
    return { x, y };
  }

  function updateViewRect() {
    if (!imgEl) return;
    const r = imgEl.getBoundingClientRect();
    viewRect = { left: r.left, top: r.top, width: r.width, height: r.height };
  }

  async function markPainted() {
    updateViewRect();
    await ipcEmit('region://painted');
  }

  function selectionMode() {
    return mode === 'capture' || mode === 'rect';
  }

  function windowAt(point: Point | null): WindowRect | null {
    if (!point || !frame) return null;
    return (
      (frame.windows ?? []).find(
        (w) =>
          point.x >= w.x &&
          point.x <= w.x + w.width &&
          point.y >= w.y &&
          point.y <= w.y + w.height
      ) ?? null
    );
  }

  async function cancel() {
    await emit('region://cancel');
    await getCurrentWindow().close();
  }

  async function loadFrame() {
    error = '';
    frame = null;
    const permission = await ipcInvoke<{ required: boolean; granted: boolean }>('screen_capture_permission_status');
    if (permission.required && !permission.granted) {
      await cancel();
      return;
    }
    try {
      frame = await ipcInvoke<Frame>('native_capture_frame_b64');
      requestAnimationFrame(updateViewRect);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    }
  }

  function rectForWindow(window: WindowRect): [number, number, number, number] {
    return [
      Math.round(window.x),
      Math.round(window.y),
      Math.round(window.width),
      Math.round(window.height)
    ];
  }

  function rectForMonitor(monitor: Monitor): [number, number, number, number] {
    return [
      Math.round(monitor.x),
      Math.round(monitor.y),
      Math.round(monitor.width),
      Math.round(monitor.height)
    ];
  }

  function selectRect(rect: [number, number, number, number], title = '', windowId: number | null = null) {
    selectedRect = rect;
    selectedTitle = title;
    selectedWindowId = windowId;
    hoverWindow = null;
  }

  async function captureRect(rect: [number, number, number, number] | null = selectedRect) {
    if (!rect) return;
    try {
      const path = selectedWindowId
        ? await ipcInvoke<string>('save_native_capture_window', { windowId: selectedWindowId })
        : frame
        ? await ipcInvoke<string>('save_native_capture_frame_crop', { rect, pngB64: frame.pngB64 })
        : await ipcInvoke<string>('save_native_capture_crop', { rect });
      await emit('region://done', path);
      await getCurrentWindow().close();
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    }
  }

  async function recordRect(rect: [number, number, number, number] | null = selectedRect) {
    if (!rect) return;
    await emit('region://record-rect', rect);
    await getCurrentWindow().close();
  }

  async function captureFullScreen() {
    if (!frame) return;
    await captureRect([0, 0, frame.width, frame.height]);
  }

  async function finish(e: PointerEvent) {
    if (mode === 'screen-capture' || mode === 'screen-rect' || mode === 'window-capture' || mode === 'window-rect') return;
    const p = imagePoint(e);
    if (!p || !dragStart) return cancel();
    dragNow = p;
    const b = box;
    const targetWindow = hoverWindow;
    dragStart = null;
    dragNow = null;
    if (!b || b.w < 4 || b.h < 4) {
      if (selectionMode() && targetWindow) {
        if (mode === 'rect') {
          await chooseWindow(targetWindow);
        } else {
          selectRect(rectForWindow(targetWindow), targetWindow.title, targetWindow.windowId ?? null);
        }
        return;
      }
      if (frame && selectionMode()) {
        const rect: [number, number, number, number] = [0, 0, frame.width, frame.height];
        if (mode === 'rect') {
          await emit('region://rect', rect);
          await getCurrentWindow().close();
        } else {
          selectRect(rect, 'Full screen');
        }
        return;
      }
      return cancel();
    }
    const rect: [number, number, number, number] = [
      Math.round(b.x),
      Math.round(b.y),
      Math.round(b.w),
      Math.round(b.h)
    ];
    try {
      if (mode === 'rect') {
        await emit('region://rect', rect);
        await getCurrentWindow().close();
        return;
      }
      selectRect(rect);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    }
  }

  async function chooseMonitor(monitor: Monitor) {
    const rect = rectForMonitor(monitor);
    try {
      if (mode === 'screen-rect') {
        await emit('region://rect', rect);
        await getCurrentWindow().close();
        return;
      }
      selectRect(rect, `Screen ${monitor.id + 1}`);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    }
  }

  async function chooseWindow(window: WindowRect) {
    const rect = rectForWindow(window);
    try {
      if (mode === 'window-rect') {
        await emit('region://rect', rect);
        await getCurrentWindow().close();
        return;
      }
      selectRect(rect, window.title, window.windowId ?? null);
    } catch (err) {
      error = err instanceof Error ? err.message : String(err);
    }
  }

  onMount(() => {
    let unFrame: (() => void) | undefined;
    void (async () => {
      try {
        unFrame = await ipcListen<Frame>('region://frame', (payload) => {
          error = '';
          frame = payload;
          requestAnimationFrame(updateViewRect);
        });
      const rawMode = new URL(globalThis.location.href).searchParams.get('mode');
      mode =
        rawMode === 'rect' || rawMode === 'screen-capture' || rawMode === 'screen-rect' || rawMode === 'window-capture' || rawMode === 'window-rect'
          ? rawMode
          : 'capture';
      await ipcEmit('region://ready');
      setTimeout(() => {
        if (!frame) void loadFrame();
      }, 750);
      } catch (err) {
        error = err instanceof Error ? err.message : String(err);
      }
    })();
    return () => unFrame?.();
  });
</script>

<svelte:window
  on:keydown={(e) => {
    if (e.key === 'Escape') void cancel();
  }}
  on:resize={updateViewRect}
/>

<div
  class="picker"
  role="application"
  aria-label="Select capture region"
  onpointerdown={(e) => {
    if (mode === 'screen-capture' || mode === 'screen-rect' || mode === 'window-capture' || mode === 'window-rect') return;
    const p = imagePoint(e);
    if (!p) return;
    selectedRect = null;
    selectedTitle = '';
    hoverWindow = windowAt(p);
    dragStart = p;
    dragNow = p;
  }}
  onpointermove={(e) => {
    const p = imagePoint(e);
    if (selectionMode()) hoverWindow = windowAt(p);
    if (mode === 'screen-capture' || mode === 'screen-rect' || mode === 'window-capture' || mode === 'window-rect') return;
    if (dragStart) dragNow = p;
  }}
  onpointerup={finish}
>
  {#if frame}
    <img bind:this={imgEl} src={`data:image/png;base64,${frame.pngB64}`} alt="" draggable="false" onload={markPainted} />
    <div class="dim"></div>
    {#if (mode === 'screen-capture' || mode === 'screen-rect') && viewRect}
      {@const r = viewRect}
      {#each frame.monitors ?? [] as monitor (monitor.id)}
        <button
          class="monitor"
          style="
            left:{r.left + (monitor.x / frame.width) * r.width}px;
            top:{r.top + (monitor.y / frame.height) * r.height}px;
            width:{(monitor.width / frame.width) * r.width}px;
            height:{(monitor.height / frame.height) * r.height}px"
          onclick={() => chooseMonitor(monitor)}
        >
          Screen {monitor.id + 1}
        </button>
      {/each}
    {/if}
    {#if (mode === 'window-capture' || mode === 'window-rect') && viewRect}
      {@const r = viewRect}
      {#each frame.windows ?? [] as window (window.id)}
        <button
          class="target window"
          style="
            left:{r.left + (window.x / frame.width) * r.width}px;
            top:{r.top + (window.y / frame.height) * r.height}px;
            width:{(window.width / frame.width) * r.width}px;
            height:{(window.height / frame.height) * r.height}px"
          title={window.title}
          onclick={() => chooseWindow(window)}
        >
          <span>{window.title}</span>
        </button>
      {/each}
      {#if (frame.windows ?? []).length === 0}
        <div class="message">No selectable windows found</div>
      {/if}
    {/if}
    {#if selectionMode() && hoverWindow && viewRect && !box && !selectedRect}
      {@const r = viewRect}
      <div
        class="target hover-window"
        style="
          left:{r.left + (hoverWindow.x / frame.width) * r.width}px;
          top:{r.top + (hoverWindow.y / frame.height) * r.height}px;
          width:{(hoverWindow.width / frame.width) * r.width}px;
          height:{(hoverWindow.height / frame.height) * r.height}px"
      >
        <span>{hoverWindow.title}</span>
      </div>
    {/if}
    {#if selectedRect && viewRect}
      {@const r = viewRect}
      {@const sr = { x: selectedRect[0], y: selectedRect[1], w: selectedRect[2], h: selectedRect[3] }}
      <div
        class="sel final"
        style="
          left:{r.left + (sr.x / frame.width) * r.width}px;
          top:{r.top + (sr.y / frame.height) * r.height}px;
          width:{(sr.w / frame.width) * r.width}px;
          height:{(sr.h / frame.height) * r.height}px"
      ></div>
      <div
        class="actions"
        role="toolbar"
        tabindex="-1"
        aria-label="Capture actions"
        onpointerdown={(e) => e.stopPropagation()}
        onpointerup={(e) => e.stopPropagation()}
        style="
          left:{Math.max(16, Math.min(globalThis.innerWidth - 356, r.left + (sr.x / frame.width) * r.width))}px;
          top:{Math.max(16, Math.min(globalThis.innerHeight - 56, r.top + ((sr.y + sr.h) / frame.height) * r.height + 12))}px"
      >
        {#if selectedTitle}<span class="chosen" title={selectedTitle}>{selectedTitle}</span>{/if}
        <button class="tool primary" title="Capture" aria-label="Capture" onclick={() => captureRect()}>
          <svg viewBox="0 0 24 24"><path d="M4 8.5A2.5 2.5 0 0 1 6.5 6h1.8l1.2-1.7h5L15.7 6h1.8A2.5 2.5 0 0 1 20 8.5v8A2.5 2.5 0 0 1 17.5 19h-11A2.5 2.5 0 0 1 4 16.5z"/><circle cx="12" cy="12.5" r="3.3"/></svg>
        </button>
        <button class="tool record" title="Record" aria-label="Record" onclick={() => recordRect()}>
          <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="6"/></svg>
        </button>
        <button class="tool screen" title="Full screen" aria-label="Full screen" onclick={captureFullScreen}>
          <svg viewBox="0 0 24 24"><path d="M8 3H5a2 2 0 0 0-2 2v3M16 3h3a2 2 0 0 1 2 2v3M8 21H5a2 2 0 0 1-2-2v-3M16 21h3a2 2 0 0 0 2-2v-3"/></svg>
        </button>
        <button class="tool quiet" title="Cancel" aria-label="Cancel" onclick={cancel}>
          <svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>
        </button>
      </div>
    {/if}
    {#if box && viewRect}
      {@const r = viewRect}
      <div
        class="sel"
        style="
          left:{r.left + (box.x / frame.width) * r.width}px;
          top:{r.top + (box.y / frame.height) * r.height}px;
          width:{(box.w / frame.width) * r.width}px;
          height:{(box.h / frame.height) * r.height}px"
      ></div>
    {/if}
  {:else}
    <div class="message">{error || 'Preparing capture...'}</div>
  {/if}
  {#if error}<div class="error">{error}</div>{/if}
</div>

<style>
  :global(html, body) {
    margin: 0;
    overflow: hidden;
    background: #050506;
    cursor: crosshair;
    user-select: none;
  }
  .picker {
    position: fixed;
    inset: 0;
    display: grid;
    place-items: center;
  }
  img {
    width: 100vw;
    height: 100vh;
    object-fit: contain;
    display: block;
  }
  .dim {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.22);
    pointer-events: none;
  }
  .sel {
    position: fixed;
    box-sizing: border-box;
    border: 2px solid var(--bf-primary);
    background: color-mix(in srgb, var(--bf-primary) 16%, transparent);
    box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.42);
    pointer-events: none;
  }
  .sel.final {
    border-color: var(--bf-primary);
    background: rgba(125, 211, 252, 0.12);
    box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.48), 0 0 0 1px rgba(255, 255, 255, 0.35);
  }
  .target,
  .monitor {
    position: fixed;
    box-sizing: border-box;
    display: grid;
    place-items: center;
    border: 2px solid var(--bf-primary);
    background: color-mix(in srgb, var(--bf-primary) 12%, transparent);
    color: #f5f5f7;
    font: 700 18px system-ui, sans-serif;
    text-shadow: 0 1px 6px rgba(0, 0, 0, 0.75);
    cursor: pointer;
  }
  .target:hover,
  .monitor:hover {
    background: color-mix(in srgb, var(--bf-primary) 24%, transparent);
    box-shadow: inset 0 0 0 2px rgba(255, 255, 255, 0.32);
  }
  .window {
    overflow: hidden;
    padding: 6px;
    font-size: 13px;
  }
  .window span,
  .hover-window span {
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .hover-window {
    pointer-events: none;
    overflow: hidden;
    padding: 6px;
    font-size: 13px;
    background: color-mix(in srgb, var(--bf-primary) 24%, transparent);
    box-shadow: inset 0 0 0 2px rgba(255, 255, 255, 0.32), 0 0 0 9999px rgba(0, 0, 0, 0.22);
  }
  .actions {
    position: fixed;
    z-index: 4;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    max-width: calc(100vw - 32px);
    padding: 7px;
    border-radius: 8px;
    background: var(--bf-paper);
    border: 1px solid var(--bf-line);
    box-shadow: var(--bf-shadow-float);
    backdrop-filter: blur(10px);
  }
  .tool {
    width: 44px;
    height: 44px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: 0 0 auto;
    border: 1px solid var(--bf-line);
    border-radius: 6px;
    color: var(--bf-ink);
    background: var(--bf-cool);
    cursor: pointer;
  }
  .tool:hover {
    background: var(--bf-surface-raised);
    border-color: rgba(255, 255, 255, 0.2);
  }
  .tool:active {
    transform: translateY(1px);
  }
  .tool.primary {
    background: var(--bf-primary);
    color: var(--bf-primary-foreground);
    border-color: rgba(255, 255, 255, 0.16);
  }
  .tool.primary:hover {
    background: var(--bf-primary-hover);
  }
  .tool.record {
    color: var(--bf-danger);
  }
  .tool.quiet {
    color: var(--bf-muted);
  }
  .tool svg {
    width: 23px;
    height: 23px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.8;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  .record svg {
    fill: currentColor;
    stroke: none;
    width: 18px;
    height: 18px;
  }
  .chosen {
    max-width: 150px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    color: #f5f5f7;
    font: 600 12px system-ui, sans-serif;
    padding: 0 4px;
  }
  .message,
  .error {
    position: fixed;
    color: #f5f5f7;
    font: 13px system-ui, sans-serif;
    background: rgba(20, 20, 24, 0.86);
    border: 1px solid rgba(255, 255, 255, 0.18);
    padding: 10px 12px;
    border-radius: 6px;
  }
  .error {
    bottom: 18px;
  }
</style>
