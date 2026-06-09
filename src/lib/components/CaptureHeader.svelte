<script lang="ts">
  import { recording } from '$lib/stores';
  const modes = ['Region', 'Full screen', 'Window', 'Scrolling'];
  function fmt(ms: number) {
    const s = Math.floor(ms / 1000);
    return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
  }
</script>

<header class="header">
  <div class="modes">
    {#each modes as m}
      <button class="mode">{m}</button>
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

<style>
  .header {
    height: 44px; display: flex; align-items: center; gap: 8px; padding: 0 10px;
    border-bottom: 1px solid var(--border); background: var(--bg-content); flex-shrink: 0;
  }
  .modes { display: flex; gap: 2px; }
  .mode {
    height: 28px; padding: 0 12px; border: none; background: transparent;
    color: var(--fg-primary); border-radius: var(--radius); font-size: var(--text-base); cursor: default;
  }
  .mode:hover { background: var(--bg-hover); }
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
