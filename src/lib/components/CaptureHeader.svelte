<script lang="ts">
  import { recording, takeCapture, view, activeItem } from '$lib/stores';
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

{#if $view === 'editor' && $activeItem}
  <EditorToolbar />
{:else}
<header class="header">
  <div class="modes">
    {#each modes as m}
      <button
        class="mode"
        disabled={!m.mode}
        onclick={() => m.mode && takeCapture(m.mode)}>{m.label}</button>
    {/each}
  </div>
  <div class="spacer"></div>
  <button class="record" class:active={$recording.status === 'recording'}>
    ● Record
    {#if $recording.status === 'recording'}
      <span class="timer">{fmt($recording.elapsedMs)}</span>
    {/if}
  </button>
</header>
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
  .record {
    height: 28px; padding: 0 14px; border: none; border-radius: var(--radius);
    background: var(--accent); color: #fff; font-size: var(--text-base); cursor: default;
    display: inline-flex; align-items: center; gap: 8px;
  }
  .record:hover { filter: brightness(1.08); }
  .record.active { background: var(--danger); }
  .timer { font-variant-numeric: tabular-nums; }
</style>
