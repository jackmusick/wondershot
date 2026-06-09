<script lang="ts">
  import { recording, view, activeItem, settingsOpen, capturePanelOpen } from '$lib/stores';
  import { ipcInvoke } from '$lib/ipc';
  import {
    startRecording,
    stopRecording,
    pauseRecording,
    resumeRecording
  } from '$lib/recorder/control';
  import EditorToolbar from '$lib/editor/EditorToolbar.svelte';

  const USE_MOCK = typeof (globalThis as any).__TAURI_INTERNALS__ === 'undefined';

  /** Open the framed, always-on-top capture window (real mode), or the in-page
   * popover in browser dev where secondary windows don't exist. */
  async function openCapture() {
    if (USE_MOCK) {
      capturePanelOpen.set(true);
      return;
    }
    try {
      await ipcInvoke('show_capture_window');
    } catch (e) {
      console.error('open capture window failed', e);
    }
  }

  function fmt(ms: number) {
    const s = Math.floor(ms / 1000);
    return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
  }

  let cameraOn = $state(false);
  async function toggleCamera() {
    try {
      cameraOn = await ipcInvoke<boolean>('toggle_camera_bubble');
    } catch (e) {
      console.error('camera toggle failed', e);
    }
  }
</script>

<header class="header">
  <button class="hbtn" title="Capture (opens the capture window)" onclick={openCapture}>
    <svg viewBox="0 0 16 16"><path d="M2 5.5A1.5 1.5 0 0 1 3.5 4h1l1-1.5h3L9.5 4h3A1.5 1.5 0 0 1 14 5.5V12a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 2 12z"/><circle cx="8" cy="8.5" r="2.5"/></svg>
    Capture
  </button>

  {#if $recording.status === 'recording'}
    <div class="rec-controls">
      <button class="hbtn rec" onclick={() => stopRecording()} title="Stop recording">
        <span class="dot"></span><span class="timer">{fmt($recording.elapsedMs)}</span>
      </button>
      {#if $recording.paused}
        <button class="hbtn" onclick={() => resumeRecording()}>Resume</button>
      {:else}
        <button class="hbtn" onclick={() => pauseRecording()}>Pause</button>
      {/if}
      <button class="hbtn" onclick={() => stopRecording()}>Stop</button>
    </div>
  {:else}
    <button class="hbtn" title="Record the screen" onclick={() => startRecording()}>
      <svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="5" class="fill-red"/></svg>
      Record
    </button>
    <button class="hbtn" title="Record a region / window (choose in the picker)" onclick={() => startRecording()}>
      <svg viewBox="0 0 16 16"><rect x="2" y="2.5" width="12" height="11" rx="1.5" stroke-dasharray="2.5 2"/><circle cx="8" cy="8" r="3" class="fill-red"/></svg>
      Record Region
    </button>
  {/if}

  <button class="hbtn" class:active={cameraOn} title="Toggle the camera bubble" onclick={toggleCamera}>
    <svg viewBox="0 0 16 16"><rect x="1.5" y="4" width="9" height="8" rx="1.5"/><path d="M10.5 7l4-2.5v7L10.5 9z"/></svg>
    Camera
  </button>

  <button class="hbtn" title="Settings" onclick={() => settingsOpen.set(true)}>
    <svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="2.2"/><path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M12.6 3.4l-1.4 1.4M4.8 11.2l-1.4 1.4"/></svg>
    Settings
  </button>

  <div class="spacer"></div>
  <button class="hbtn" disabled={!$activeItem} title="Sharing targets aren't bundled in this build">
    <svg viewBox="0 0 16 16"><path d="M3 9v4h10V9M8 11V2M5 5l3-3 3 3"/></svg>
    Share
  </button>
</header>
{#if $view === 'editor' && $activeItem}
  <EditorToolbar />
{/if}

<style>
  .header {
    height: 46px; display: flex; align-items: center; gap: 4px; padding: 0 10px;
    border-bottom: 1px solid var(--border); background: var(--bg-content); flex-shrink: 0;
  }
  .hbtn {
    display: inline-flex; align-items: center; gap: 7px; height: 32px; padding: 0 12px;
    border: none; background: transparent; color: var(--fg-primary);
    border-radius: var(--radius); font-size: var(--text-base); cursor: pointer; white-space: nowrap;
  }
  .hbtn:hover:not(:disabled) { background: var(--bg-hover); }
  .hbtn:disabled { opacity: 0.4; cursor: default; }
  .hbtn.active { background: var(--bg-selected); }
  .hbtn svg {
    width: 17px; height: 17px; fill: none; stroke: currentColor;
    stroke-width: 1.4; stroke-linecap: round; stroke-linejoin: round; flex-shrink: 0;
  }
  .hbtn svg .fill-red { fill: var(--danger); stroke: none; }
  .spacer { flex: 1; }
  .rec-controls { display: inline-flex; align-items: center; gap: 4px; }
  .rec .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--danger); margin-right: 6px;
    animation: rec-pulse 1.4s ease-in-out infinite; }
  .rec .timer { font-variant-numeric: tabular-nums; }
  @keyframes rec-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
</style>
