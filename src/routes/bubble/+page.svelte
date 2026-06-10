<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { ipcInvoke, ipcListen } from '$lib/ipc';

  const USE_MOCK = typeof (globalThis as any).__TAURI_INTERNALS__ === 'undefined';

  const MIN = 160;
  const MAX = 400;
  const STEP = 24;

  let size = $state(220);
  let hasCamera = $state(false);
  let videoEl: HTMLVideoElement;
  let stream: MediaStream | null = null;
  let unwatch: (() => void) | undefined;

  /** The configured camera as a webview deviceId (empty = system default).
   *  Settings stores the device LABEL (stable across restarts + shared with
   *  the Python app's conf), so resolve label → deviceId here. Exact label
   *  match first, then prefix (Qt and the webview render slightly different
   *  suffixes for the same camera). */
  async function configuredCamera(): Promise<string> {
    try {
      const s = (await ipcInvoke<Record<string, unknown>>('get_settings')) ?? {};
      const label = String(s.camera_device ?? '');
      if (!label) return '';
      const devs = (await navigator.mediaDevices.enumerateDevices()).filter(
        (d) => d.kind === 'videoinput'
      );
      const hit =
        devs.find((d) => d.label === label) ??
        devs.find((d) => d.label.startsWith(label) || label.startsWith(d.label)) ??
        devs.find((d) => d.deviceId === label); // pre-label-era saved deviceId
      return hit?.deviceId ?? '';
    } catch {
      return '';
    }
  }

  function stopStream() {
    stream?.getTracks().forEach((t) => t.stop());
    stream = null;
  }

  async function startCamera(deviceId?: string) {
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      hasCamera = false;
      return;
    }
    stopStream();
    const id = deviceId ?? (await configuredCamera());
    const video: MediaTrackConstraints | boolean = id ? { deviceId: { exact: id } } : true;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video });
      if (videoEl) {
        videoEl.srcObject = stream;
        await videoEl.play().catch(() => {});
      }
      hasCamera = true;
    } catch {
      // Requested device gone? Fall back to the default camera before giving up.
      if (id) {
        try {
          stream = await navigator.mediaDevices.getUserMedia({ video: true });
          if (videoEl) { videoEl.srcObject = stream; await videoEl.play().catch(() => {}); }
          hasCamera = true;
          return;
        } catch { /* fall through */ }
      }
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

  onMount(async () => {
    await startCamera();
    // Re-init when the user picks a different camera in Settings.
    unwatch = await ipcListen<string>('camera://changed', () => {
      // Payload is the saved LABEL; re-resolve to a deviceId via settings.
      void startCamera();
    });
  });

  onDestroy(() => {
    unwatch?.();
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
