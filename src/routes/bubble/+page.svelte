<script lang="ts">
  import { onMount, onDestroy } from 'svelte';

  const USE_MOCK = typeof (globalThis as any).__TAURI_INTERNALS__ === 'undefined';

  const MIN = 160;
  const MAX = 400;
  const STEP = 24;

  let size = $state(220);
  let hasCamera = $state(false);
  let videoEl: HTMLVideoElement;
  let stream: MediaStream | null = null;

  async function startCamera() {
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      hasCamera = false;
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: true });
      if (videoEl) {
        videoEl.srcObject = stream;
        await videoEl.play().catch(() => {});
      }
      hasCamera = true;
    } catch {
      // No camera or permission denied — fall back to placeholder.
      hasCamera = false;
    }
  }

  /** Resize the window (Tauri) or just the element (browser). */
  async function applySize(next: number) {
    size = Math.max(MIN, Math.min(MAX, next));
    if (USE_MOCK) return;
    try {
      const { getCurrentWindow, LogicalSize } = await import('@tauri-apps/api/window');
      await getCurrentWindow().setSize(new LogicalSize(size, size));
    } catch {
      // ignore — element already resized
    }
  }

  function onWheel(e: WheelEvent) {
    e.preventDefault();
    applySize(size + (e.deltaY < 0 ? STEP : -STEP));
  }

  /** Drag the window (Tauri); no-op in browser. */
  async function onPointerDown(e: PointerEvent) {
    if (e.button !== 0) return;
    if (USE_MOCK) return;
    try {
      const { getCurrentWindow } = await import('@tauri-apps/api/window');
      await getCurrentWindow().startDragging();
    } catch {
      // ignore
    }
  }

  onMount(startCamera);

  onDestroy(() => {
    stream?.getTracks().forEach((t) => t.stop());
  });
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="bubble"
  style="width:{size}px;height:{size}px"
  onwheel={onWheel}
  onpointerdown={onPointerDown}
>
  <!-- svelte-ignore a11y_media_has_caption -->
  <video bind:this={videoEl} class="cam" class:hidden={!hasCamera} autoplay playsinline muted></video>
  {#if !hasCamera}
    <div class="placeholder" aria-label="no camera">
      <svg viewBox="0 0 24 24" width="40" height="40" fill="none" stroke="currentColor" stroke-width="1.6">
        <path d="M2 7.5a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-9Z" />
        <path d="M15 10.5 21 7v10l-6-3.5" />
      </svg>
    </div>
  {/if}
</div>

<style>
  :global(html, body) {
    margin: 0;
    background: transparent;
    overflow: hidden;
  }
  .bubble {
    position: fixed;
    inset: 0;
    margin: auto;
    border-radius: 50%;
    overflow: hidden;
    box-sizing: border-box;
    border: 3px solid rgba(255, 255, 255, 0.86);
    background: var(--bg-elevated, #1e1e22);
    cursor: grab;
    user-select: none;
  }
  .bubble:active {
    cursor: grabbing;
  }
  .cam {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  .cam.hidden {
    display: none;
  }
  .placeholder {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--fg-secondary, #c8c8cd);
    background: var(--bg-elevated, #1e1e22);
  }
</style>
