<script lang="ts">
  import { recording, takeCapture, view, activeItem, settingsOpen } from '$lib/stores';
  import {
    startRecording,
    stopRecording,
    pauseRecording,
    resumeRecording
  } from '$lib/recorder/control';
  import EditorToolbar from '$lib/editor/EditorToolbar.svelte';
  const modes: { label: string; mode?: 'region' | 'fullscreen' | 'window' }[] = [
    { label: 'Region', mode: 'region' },
    { label: 'Full screen', mode: 'fullscreen' },
    { label: 'Window', mode: 'window' },
    { label: 'Scrolling' } // no backend in M2
  ];
  function fmt(ms: number) {
    const s = Math.floor(ms / 1000);
    return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
  }
</script>

<header class="header">
  <div class="modes">
    {#each modes as m}
      <button
        class="mode"
        disabled={!m.mode}
        onclick={() => m.mode && takeCapture(m.mode)}>{m.label}</button>
    {/each}
  </div>
  <button class="mode" onclick={() => settingsOpen.set(true)}>⚙ Settings</button>
  <div class="spacer"></div>
  {#if $recording.status === 'recording'}
    <div class="rec-controls">
      <button class="record active" onclick={() => stopRecording()} title="Stop recording">
        <span class="dot"></span>
        <span class="timer">{fmt($recording.elapsedMs)}</span>
      </button>
      {#if $recording.paused}
        <button class="rec-btn" onclick={() => resumeRecording()}>Resume</button>
      {:else}
        <button class="rec-btn" onclick={() => pauseRecording()}>Pause</button>
      {/if}
      <button class="rec-btn" onclick={() => stopRecording()}>Stop</button>
    </div>
  {:else}
    <button class="record" onclick={() => startRecording()}>● Record</button>
  {/if}
</header>
{#if $view === 'editor' && $activeItem}
  <EditorToolbar />
{/if}

<style>
  .header {
    height: 44px; display: flex; align-items: center; gap: 8px; padding: 0 10px;
    border-bottom: 1px solid var(--border); background: var(--bg-content); flex-shrink: 0;
  }
  .modes { display: flex; gap: 2px; }
  .mode {
    height: 28px; padding: 0 12px; border: none; background: transparent;
    color: var(--fg-primary); border-radius: var(--radius); font-size: var(--text-base); cursor: pointer;
  }
  .mode:hover:not(:disabled) { background: var(--bg-hover); }
  .mode:disabled { opacity: 0.4; cursor: default; }
  .spacer { flex: 1; }
  .rec-controls { display: inline-flex; align-items: center; gap: 6px; }
  .record {
    height: 28px; padding: 0 14px; border: none; border-radius: var(--radius);
    background: var(--accent); color: #fff; font-size: var(--text-base); cursor: pointer;
    display: inline-flex; align-items: center; gap: 8px;
  }
  .record:hover { filter: brightness(1.08); }
  .record.active { background: var(--danger); }
  .dot {
    width: 8px; height: 8px; border-radius: 50%; background: #fff;
    animation: rec-pulse 1.4s ease-in-out infinite;
  }
  @keyframes rec-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
  .rec-btn {
    height: 28px; padding: 0 12px; border: 1px solid var(--border); border-radius: var(--radius);
    background: var(--bg-content); color: var(--fg-primary); font-size: var(--text-base); cursor: pointer;
  }
  .rec-btn:hover { background: var(--bg-hover); }
  .timer { font-variant-numeric: tabular-nums; }
</style>
