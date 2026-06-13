<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { ipcInvoke, ipcListen } from '$lib/ipc';
  import { openCameraSource } from '$lib/media/camera';

  const USE_MOCK = typeof (globalThis as any).__TAURI_INTERNALS__ === 'undefined';

  const MIN = 160;
  const MAX = 400;
  const STEP = 24;

  let size = $state(220);
  let hasCamera = $state(false);
  /** MJPEG stream URL (backend gst → loopback server) — '' = stopped. The
   *  webview never touches getUserMedia: WebKitGTK's capture portal is
   *  unreliable in the Flatpak (launch crashes, silent black feeds); the
   *  backend reads the camera with GStreamer and serves multipart JPEG. */
  let camSrc = $state('');
  let videoEl: HTMLVideoElement | undefined;
  let webStream: MediaStream | undefined;
  let unwatch: (() => void) | undefined;

  function stopStream() {
    webStream?.getTracks().forEach((track) => track.stop());
    webStream = undefined;
    if (videoEl) videoEl.srcObject = null;
    camSrc = '';
    hasCamera = false;
  }

  async function startCamera() {
    try {
      const s = (await ipcInvoke<Record<string, unknown>>('get_settings')) ?? {};
      const label = String(s.camera_device ?? '');
      const source = await openCameraSource(label);
      stopStream();
      if (source.type === 'stream') {
        webStream = source.stream;
        if (videoEl) {
          videoEl.srcObject = webStream;
          await videoEl.play();
          hasCamera = true;
        }
        return;
      }
      if (source.type === 'url') {
        camSrc = source.src;
        return;
      }
      if (source.type === 'none') {
        hasCamera = false;
        return;
      }
    } catch {
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

  let unShown: (() => void) | undefined;
  let unHidden: (() => void) | undefined;
  let shown = false;

  onMount(async () => {
    // LAZY camera: this window exists (hidden) from app launch, but WebKit's
    // capture stack must not run until the bubble is actually shown — probing
    // devices at startup is a privacy smell AND aborts WebKitGTK's web
    // process on some Wayland/PipeWire setups (KDE/Fedora launch crash).
    // The backend emits bubble://shown / bubble://hidden from the toggle.
    unShown = await ipcListen('bubble://shown', () => {
      shown = true;
      void startCamera();
    });
    unHidden = await ipcListen('bubble://hidden', () => {
      shown = false;
      stopStream();
    });
    // Already visible (e.g. webview reloaded while shown)? Start right away.
    if (!USE_MOCK) {
      try {
        const { getCurrentWindow } = await import('@tauri-apps/api/window');
        if (await getCurrentWindow().isVisible()) {
          shown = true;
          void startCamera();
        }
      } catch {
        // ignore — stays lazy
      }
    }
    // Re-init when the user picks a different camera in Settings (only while
    // visible; a hidden bubble re-resolves on its next show instead).
    unwatch = await ipcListen<string>('camera://changed', () => {
      if (shown) void startCamera();
    });
  });

  onDestroy(() => {
    unwatch?.();
    unShown?.();
    unHidden?.();
    stopStream();
  });
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="bubble"
  style="width:{size}px;height:{size}px"
  onwheel={onWheel}
  onpointerdown={onPointerDown}
>
  {#if camSrc}
    <img
      class="cam"
      class:hidden={!hasCamera}
      src={camSrc}
      alt=""
      draggable="false"
      onload={() => (hasCamera = true)}
      onerror={() => (hasCamera = false)}
    />
  {/if}
  <video
    bind:this={videoEl}
    class="cam"
    class:hidden={!hasCamera || !!camSrc}
    autoplay
    muted
    playsinline
  ></video>
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
