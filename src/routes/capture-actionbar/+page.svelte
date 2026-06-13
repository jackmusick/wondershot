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
</script>

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
    background: #141417;
    font-family: var(--font-ui, Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif);
  }

  .bar {
    height: 58px;
    width: 296px;
    box-sizing: border-box;
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 7px;
    color: #f7f7f8;
    background: #141417;
    border: 1px solid rgba(255, 255, 255, 0.12);
    border-radius: 8px;
    box-shadow: 0 16px 38px rgba(0, 0, 0, 0.38), 0 2px 8px rgba(0, 0, 0, 0.35);
  }

  .tool {
    width: 44px;
    height: 44px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    flex: 0 0 auto;
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 6px;
    color: #f7f7f8;
    background: rgba(255, 255, 255, 0.07);
    cursor: pointer;
  }

  .tool:hover {
    background: rgba(255, 255, 255, 0.14);
    border-color: rgba(255, 255, 255, 0.2);
  }

  .tool:active {
    transform: translateY(1px);
  }

  .tool.primary {
    background: #2f7df6;
    border-color: rgba(255, 255, 255, 0.16);
  }

  .tool.primary:hover {
    background: #438bff;
  }

  .tool.record {
    color: #ff4d5d;
  }

  .tool.quiet {
    color: rgba(255, 255, 255, 0.74);
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
    color: rgba(255, 255, 255, 0.82);
    background: rgba(255, 255, 255, 0.06);
    border: 1px solid rgba(255, 255, 255, 0.08);
    border-radius: 6px;
    font-size: 13px;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }

  .size span {
    padding: 0 7px;
    color: rgba(255, 255, 255, 0.42);
  }
</style>
