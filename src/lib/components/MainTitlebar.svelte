<script lang="ts">
  import { currentPlatform, USE_MOCK } from '$lib/platform';
  import { onMount } from 'svelte';

  let visible = $state(false);

  onMount(() => {
    void currentPlatform().then((platform) => (visible = platform === 'linux'));
  });

  async function windowHandle() {
    return (await import('@tauri-apps/api/window')).getCurrentWindow();
  }

  async function drag(event: PointerEvent) {
    if (USE_MOCK || event.button !== 0) return;
    const target = event.target as Element | null;
    if (target?.closest('button')) return;
    try { await (await windowHandle()).startDragging(); } catch {}
  }

  async function minimize() {
    if (!USE_MOCK) await (await windowHandle()).minimize();
  }

  async function maximize() {
    if (!USE_MOCK) await (await windowHandle()).toggleMaximize();
  }

  async function close() {
    if (!USE_MOCK) await (await windowHandle()).close();
  }
</script>

{#if visible}
  <div
    class="titlebar"
    role="presentation"
    onpointerdown={drag}
    ondblclick={maximize}
  >
    <span class="title">Wondershot</span>
    <div class="controls" aria-label="Window controls">
      <button title="Minimize" aria-label="Minimize" onclick={minimize}>
        <svg viewBox="0 0 12 12"><path d="M2 8.5h8" /></svg>
      </button>
      <button title="Maximize or restore" aria-label="Maximize or restore" onclick={maximize}>
        <svg viewBox="0 0 12 12"><rect x="2.5" y="2.5" width="7" height="7" rx=".5" /></svg>
      </button>
      <button class="close" title="Close" aria-label="Close" onclick={close}>
        <svg viewBox="0 0 12 12"><path d="m2.5 2.5 7 7m0-7-7 7" /></svg>
      </button>
    </div>
  </div>
{/if}

<style>
  .titlebar {
    height: 32px; display: flex; align-items: center; flex-shrink: 0;
    background: var(--bg-elevated); border-bottom: 1px solid var(--border);
    user-select: none;
  }
  .title { padding-left: 12px; font-size: var(--text-small); color: var(--fg-secondary); }
  .controls { margin-left: auto; align-self: stretch; display: flex; }
  button {
    width: 46px; height: 100%; display: grid; place-items: center; padding: 0;
    border: 0; border-radius: 0; color: var(--fg-secondary); background: transparent;
    cursor: default; transition: background-color 90ms ease, color 90ms ease;
  }
  button:hover { color: var(--fg-primary); background: rgba(255, 255, 255, 0.12); }
  button:active { background: rgba(255, 255, 255, 0.18); }
  button.close:hover { color: #fff; background: #c42b1c; }
  button.close:active { background: #a52116; }
  svg { width: 12px; height: 12px; fill: none; stroke: currentColor; stroke-width: 1.15; }
</style>
