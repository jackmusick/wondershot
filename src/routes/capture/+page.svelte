<script lang="ts">
  // Frameless, secondary capture window with a custom titlebar — the native
  // titlebar's min/close buttons don't function for Tauri secondary windows on
  // this Wayland/KWin setup, so we draw our own and wire them to the window API
  // directly. Capture/record actions are forwarded to the main window (which
  // owns the library + editor) over the `capture-cmd` event.
  import { onMount } from 'svelte';
  import { ipcInvoke, ipcEmit } from '$lib/ipc';

  const USE_MOCK = typeof (globalThis as any).__TAURI_INTERNALS__ === 'undefined';

  let copyAfter = $state(true);
  let preview = $state(true);
  let cursor = $state(false);
  let delay = $state(0);

  async function load() {
    const s = (await ipcInvoke<Record<string, unknown>>('get_settings')) ?? {};
    copyAfter = s.copy_after_capture !== false;
    preview = s.show_gallery_after_capture !== false;
    cursor = s.capture_cursor === true;
    delay = Number(s.capture_delay ?? 0);
  }

  function persist() {
    void ipcInvoke('set_settings', {
      values: {
        copy_after_capture: copyAfter,
        show_gallery_after_capture: preview,
        capture_cursor: cursor,
        capture_delay: delay,
      },
    });
  }

  async function win() {
    const { getCurrentWindow } = await import('@tauri-apps/api/window');
    return getCurrentWindow();
  }
  async function minimizeSelf() { if (!USE_MOCK) try { await (await win()).minimize(); } catch {} }
  async function hideSelf() { if (!USE_MOCK) try { await (await win()).hide(); } catch {} }
  async function closeSelf() { if (!USE_MOCK) try { await (await win()).close(); } catch {} }

  async function run(kind: 'capture' | 'record', mode?: 'region' | 'fullscreen' | 'window') {
    persist();
    await hideSelf();
    void ipcEmit('capture-cmd', { kind, mode });
  }

  onMount(load);
</script>

<div class="titlebar" data-tauri-drag-region>
  <span class="ttitle" data-tauri-drag-region>Capture</span>
  <span class="tbtns">
    <button class="twin" title="Minimize" onclick={minimizeSelf} aria-label="Minimize">
      <svg viewBox="0 0 12 12" width="11" height="11"><path d="M2 6h8" /></svg>
    </button>
    <button class="twin close" title="Close" onclick={closeSelf} aria-label="Close">
      <svg viewBox="0 0 12 12" width="11" height="11"><path d="M2.5 2.5l7 7M9.5 2.5l-7 7" /></svg>
    </button>
  </span>
</div>

<div class="body">
  <div class="opts">
    <label class="check"><input type="checkbox" bind:checked={preview} /> Preview in editor</label>
    <label class="check"><input type="checkbox" bind:checked={copyAfter} /> Copy to clipboard</label>
    <label class="check"><input type="checkbox" bind:checked={cursor} /> Capture cursor</label>
    <label class="delay">
      Delay
      <input type="number" min="0" max="10" bind:value={delay} /> s
    </label>
  </div>
  <button class="capture" onclick={() => run('capture', 'region')} title="Drag a region (Spectacle)">
    Capture
  </button>
  <div class="actions">
    <button class="act" onclick={() => run('capture', 'fullscreen')}>Full screen</button>
    <button class="act" onclick={() => run('capture', 'window')}>Window</button>
    <button class="act" onclick={() => run('record')}>Record</button>
  </div>
</div>

<style>
  :global(html, body) { margin: 0; background: var(--bg-elevated, #1e1e22); overflow: hidden; }
  .titlebar {
    height: 30px; display: flex; align-items: center; justify-content: space-between;
    padding: 0 4px 0 12px; background: var(--bg-content, #161618);
    border-bottom: 1px solid var(--border, #2a2a2e); user-select: none;
  }
  .ttitle { font-size: var(--text-small, 11.5px); color: var(--fg-secondary, #b6b6bd); font-weight: 600; }
  .tbtns { display: flex; gap: 2px; }
  .twin {
    width: 28px; height: 24px; display: inline-flex; align-items: center; justify-content: center;
    border: none; background: transparent; color: var(--fg-secondary, #b6b6bd); cursor: pointer;
    border-radius: var(--radius, 6px);
  }
  .twin svg { fill: none; stroke: currentColor; stroke-width: 1.4; stroke-linecap: round; }
  .twin:hover { background: var(--bg-hover, #26262c); color: var(--fg-primary, #f0f0f3); }
  .twin.close:hover { background: var(--danger, #e3242b); color: #fff; }

  .body {
    box-sizing: border-box; height: calc(100vh - 30px);
    display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 14px;
    padding: 16px 18px; background: var(--bg-elevated, #1e1e22);
    color: var(--fg-primary, #f0f0f3); font-size: var(--text-base, 13px);
    font-family: var(--font-ui, system-ui);
  }
  .opts { display: flex; flex-direction: column; gap: 7px; }
  .check { display: flex; align-items: center; gap: 8px; }
  .check input { accent-color: var(--accent, #3b82f6); }
  .delay { display: flex; align-items: center; gap: 6px; color: var(--fg-secondary, #b6b6bd); font-size: var(--text-small, 11.5px); }
  .delay input { width: 52px; height: 26px; background: var(--bg-field, #14141a); border: 1px solid var(--border, #2a2a2e); border-radius: var(--radius, 6px); color: var(--fg-primary, #f0f0f3); padding: 0 6px; }
  .capture {
    grid-row: span 1; width: 96px; height: 96px; border-radius: 50%;
    border: none; background: var(--danger, #e3242b); color: #fff; font-size: 16px; font-weight: 700;
    cursor: pointer; box-shadow: 0 4px 14px rgba(0,0,0,0.35);
  }
  .capture:hover { filter: brightness(1.06); }
  .actions { grid-column: 1 / -1; display: flex; gap: 8px; justify-content: flex-start; }
  .act {
    height: 30px; padding: 0 14px; border-radius: var(--radius, 6px);
    border: 1px solid var(--border, #2a2a2e); background: var(--bg-field, #14141a);
    color: var(--fg-primary, #f0f0f3); cursor: pointer; font-size: var(--text-base, 13px);
    font-family: var(--font-ui, system-ui);
  }
  .act:hover { background: var(--bg-hover, #26262c); border-color: var(--fg-secondary, #6b6b72); }
</style>
