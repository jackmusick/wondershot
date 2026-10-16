<script lang="ts">
  import { onMount } from 'svelte';
  import { recording, recordingError, activeItem, settingsOpen, chooseImport, importBusy } from '$lib/stores';
  import { ipcInvoke } from '$lib/ipc';
  import { openCapturePicker } from '$lib/capture/openCapture';
  import {
    stopRecording,
    pauseRecording,
    resumeRecording
  } from '$lib/recorder/control';
  import OverflowToolbar from './OverflowToolbar.svelte';
  import { videoToolbar } from './toolbarState';
  import EditorToolbar from '$lib/editor/EditorToolbar.svelte';

  const USE_MOCK = typeof (globalThis as any).__TAURI_INTERNALS__ === 'undefined';
  let canPauseRecording = $state(true);
  let isMac = $state(true);

  onMount(async () => {
    isMac = navigator.platform.toLowerCase().includes('mac');
    if (USE_MOCK) return;
    try {
      const caps = await ipcInvoke<{ pause?: boolean }>('recorder_capabilities');
      canPauseRecording = caps.pause !== false;
    } catch {
      canPauseRecording = true;
    }
  });

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

  // Share: upload the active capture via the default provider (Settings →
  // Sharing) and copy the time-limited link. The result line shows inline
  // for a few seconds, like the Qt status bar.
  let shareBusy = $state(false);
  let shareMsg = $state('');
  let shareErr = $state(false);
  async function shareActive() {
    const item = $activeItem;
    if (!item || shareBusy) return;
    shareBusy = true;
    shareErr = false;
    shareMsg = 'Uploading…';
    try {
      const res = await ipcInvoke<{ url: string; provider: string; copied: boolean }>(
        'share_capture',
        { path: item.path }
      );
      shareMsg = res.copied
        ? `Link copied (${res.provider})`
        : `Shared via ${res.provider}: ${res.url}`;
    } catch (e) {
      shareErr = true;
      shareMsg = e instanceof Error ? e.message : String(e);
    } finally {
      shareBusy = false;
      const shown = shareMsg;
      setTimeout(() => {
        if (shareMsg === shown) shareMsg = '';
      }, 8000);
    }
  }
</script>

<header class="header" aria-label="Main Toolbar">
  <button class="hbtn" title="Capture a region or hover a window" onclick={openCapturePicker}>
    <svg viewBox="0 0 16 16"><path d="M2 5.5A1.5 1.5 0 0 1 3.5 4h1l1-1.5h3L9.5 4h3A1.5 1.5 0 0 1 14 5.5V12a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 2 12z"/><circle cx="8" cy="8.5" r="2.5"/></svg>
    <span>Capture</span>
  </button>

  <button class="hbtn" title="Import images or videos (⌘O / Ctrl+O)" disabled={$importBusy} onclick={chooseImport}>
    <svg viewBox="0 0 16 16"><path d="M2 6V3h5l2 2h5v8H2zM8 7v4M6 9l2 2 2-2"/></svg>
    <span>{$importBusy ? 'Importing…' : 'Import'}</span>
  </button>

  {#if $recording.status === 'recording'}
    <div class="rec-controls">
      <button class="hbtn rec" onclick={() => stopRecording()} title="Stop recording">
        <span class="dot"></span><span class="timer">{fmt($recording.elapsedMs)}</span>
      </button>
      {#if canPauseRecording}
        {#if $recording.paused}
          <button class="hbtn" onclick={() => resumeRecording()}>Resume</button>
        {:else}
          <button class="hbtn" onclick={() => pauseRecording()}>Pause</button>
        {/if}
      {/if}
      <button class="hbtn" onclick={() => stopRecording()}>Stop</button>
    </div>
  {/if}

  <button class="hbtn" class:active={cameraOn} title="Toggle the camera bubble" onclick={toggleCamera}>
    <svg viewBox="0 0 16 16"><rect x="1.5" y="4" width="9" height="8" rx="1.5"/><path d="M10.5 7l4-2.5v7L10.5 9z"/></svg>
    <span>Camera</span>
  </button>

  {#if !isMac}
  <button class="hbtn" title="Settings" onclick={() => settingsOpen.set(true)}>
    <svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="2.2"/><path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M12.6 3.4l-1.4 1.4M4.8 11.2l-1.4 1.4"/></svg>
    <span>Settings</span>
  </button>
  {/if}

  <span class="sep"></span>
  {#if $activeItem?.kind === 'video' && $videoToolbar}
    <OverflowToolbar embedded label="Video Editing Tools">{@render $videoToolbar()}</OverflowToolbar>
  {:else if $activeItem}
    <EditorToolbar embedded />
  {:else}
    <div class="spacer"></div>
  {/if}
  {#if shareMsg}
    <span class="sharemsg" class:err={shareErr} title={shareMsg}>{shareMsg}</span>
  {/if}
  <button
    class="hbtn"
    disabled={!$activeItem || shareBusy}
    title="Upload via the default provider (Settings → Sharing) and copy the link"
    onclick={shareActive}
  >
    <svg viewBox="0 0 16 16"><path d="M3 9v4h10V9M8 11V2M5 5l3-3 3 3"/></svg>
    <span>{shareBusy ? 'Sharing…' : 'Share'}</span>
  </button>
</header>
{#if $recordingError}
  <div class="record-error" role="alert">Recording failed: {$recordingError}</div>
{/if}

<style>
  .record-error { padding: 8px 14px; color: var(--danger, #ff5555); background: var(--bg-content); }
  .header {
    height: 60px; display: flex; align-items: center; gap: 4px; padding: 0 10px;
    border-bottom: 1px solid var(--border); background: var(--bg-content); flex-shrink: 0;
  }
  .hbtn {
    display: inline-flex; flex-direction:column; justify-content:center; align-items: center; gap: 3px; min-width:46px; height:50px; padding:0 6px; flex-shrink:0;
    border: none; background: transparent; color: var(--fg-primary);
    border-radius: var(--radius); font-size: var(--text-base); cursor: pointer; white-space: nowrap;
  }
  .hbtn > span { font-size:10px; line-height:1; }
  .sep { width:1px; height:22px; background:var(--border-strong); margin:0 4px; flex-shrink:0; }
  .hbtn:hover:not(:disabled) { background: var(--bg-hover); }
  .hbtn:disabled { opacity: 0.4; cursor: default; }
  .hbtn.active { background: var(--bg-selected); }
  .hbtn svg {
    width: 17px; height: 17px; fill: none; stroke: currentColor;
    stroke-width: 1.4; stroke-linecap: round; stroke-linejoin: round; flex-shrink: 0;
  }
  .spacer { flex: 1; }
  .sharemsg {
    font-size: var(--text-small);
    color: var(--fg-secondary);
    max-width: 200px; min-width:0; flex-shrink:1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    padding: 0 6px;
  }
  .sharemsg.err { color: var(--danger, #ff5555); }
  .rec-controls { display: inline-flex; align-items: center; gap: 4px; }
  .rec .dot { width: 8px; height: 8px; border-radius: 50%; background: var(--danger); margin-right: 6px;
    animation: rec-pulse 1.4s ease-in-out infinite; }
  .rec .timer { font-variant-numeric: tabular-nums; }
  @keyframes rec-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
</style>
