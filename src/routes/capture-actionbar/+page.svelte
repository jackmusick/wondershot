<script lang="ts">
  import { onMount } from 'svelte';
  import { ipcEmit, ipcInvoke } from '$lib/ipc';

  let width = $state(0);
  let height = $state(0);

  onMount(() => {
    const params = new URLSearchParams(location.search);
    width = Number(params.get('w') ?? 0) || 0;
    height = Number(params.get('h') ?? 0) || 0;
    void ipcInvoke('debug_log', { message: `capture-actionbar mounted ${width}x${height}` });
  });

  async function action(kind: 'capture' | 'record' | 'cancel') {
    await ipcInvoke('debug_log', { message: `capture-actionbar action ${kind}` });
    await ipcEmit('capture-actionbar://action', kind);
  }

  function handleKeydown(event: KeyboardEvent) {
    if (event.key === 'Escape') void action('cancel');
  }
</script>

<svelte:window onkeydown={handleKeydown} />

<div class="bar">
  <button class="tool primary" title="Capture" aria-label="Capture" onclick={() => action('capture')}>
    <svg viewBox="0 0 24 24"><path d="M4 8.5A2.5 2.5 0 0 1 6.5 6h1.8l1.2-1.7h5L15.7 6h1.8A2.5 2.5 0 0 1 20 8.5v8A2.5 2.5 0 0 1 17.5 19h-11A2.5 2.5 0 0 1 4 16.5z"/><circle cx="12" cy="12.5" r="3.3"/></svg>
  </button>
  <button class="tool record" title="Record" aria-label="Record" onclick={() => action('record')}>
    <svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="6"/></svg>
  </button>
  <div class="size" title={`${width} x ${height}`}>{width} <span>x</span> {height}</div>
  <button class="tool quiet" title="Cancel" aria-label="Cancel" onclick={() => action('cancel')}>
    <svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>
  </button>
</div>

<style>
  :global(html, body) {
    margin: 0;
    overflow: hidden;
    background: transparent;
    font-family: var(--font-ui, Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif);
  }

  .bar {
    height: 58px;
    width: 284px;
    box-sizing: border-box;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 7px;
    color: var(--bf-ink);
    background: var(--bf-paper);
    border: 1px solid var(--bf-line);
    border-radius: 8px;
    box-shadow: var(--bf-shadow-float);
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

  svg {
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

  .size {
    height: 44px;
    min-width: 112px;
    box-sizing: border-box;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 0 12px;
    color: var(--bf-ink);
    background: var(--bf-cool);
    border: 1px solid var(--bf-line);
    border-radius: 6px;
    font-size: 13px;
    font-variant-numeric: tabular-nums;
    font-family: var(--font-mono);
    white-space: nowrap;
  }

  .size span {
    padding: 0 7px;
    color: var(--bf-muted);
  }
</style>
