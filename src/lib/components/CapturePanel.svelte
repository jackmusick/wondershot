<script lang="ts">
  // Compact "Snagit-style" capture panel (Qt CaptureWindow parity): a few capture
  // defaults + a big Capture button, plus Full screen / Record. Region capture
  // offloads to Spectacle's drag-selection (host Spectacle via flatpak-spawn in
  // the Flatpak), then the result lands in the editor.
  import { capturePanelOpen, takeCapture } from '$lib/stores';
  import { ipcInvoke } from '$lib/ipc';
  import { startRecording } from '$lib/recorder/control';

  let copyAfter = $state(true);
  let preview = $state(true);
  let cursor = $state(false);
  let delay = $state(0);
  let loaded = $state(false);

  async function load() {
    const s = (await ipcInvoke<Record<string, unknown>>('get_settings')) ?? {};
    copyAfter = s.copy_after_capture !== false;
    preview = s.show_gallery_after_capture !== false;
    cursor = s.capture_cursor === true;
    delay = Number(s.capture_delay ?? 0);
    loaded = true;
  }

  $effect(() => {
    if ($capturePanelOpen && !loaded) load();
  });

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

  function close() {
    capturePanelOpen.set(false);
  }

  function capture(mode: 'region' | 'fullscreen' | 'window') {
    persist();
    close();
    takeCapture(mode);
  }

  function record() {
    persist();
    close();
    startRecording();
  }
</script>

{#if $capturePanelOpen}
  <div class="overlay">
    <button class="backdrop" aria-label="Close capture panel" onclick={close}></button>
    <div class="panel" role="dialog" aria-label="Capture">
      <div class="opts">
        <label class="check"><input type="checkbox" bind:checked={preview} /> Preview in editor</label>
        <label class="check"><input type="checkbox" bind:checked={copyAfter} /> Copy to clipboard</label>
        <label class="check"><input type="checkbox" bind:checked={cursor} /> Capture cursor</label>
        <label class="delay">
          Delay
          <input type="number" min="0" max="10" bind:value={delay} /> s
        </label>
      </div>
      <button class="capture" onclick={() => capture('region')} title="Drag a region (Spectacle)">
        Capture
      </button>
      <div class="links">
        <button class="link" onclick={() => capture('fullscreen')}>Full screen</button>
        <button class="link" onclick={() => capture('window')}>Window</button>
        <button class="link" onclick={record}>Record</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .overlay { position: fixed; inset: 0; display: flex; align-items: flex-start; justify-content: center; z-index: 90; }
  .backdrop { position: absolute; inset: 0; border: none; padding: 0; background: rgba(0,0,0,0.25); cursor: default; }
  .panel {
    position: relative; margin-top: 64px;
    display: grid; grid-template-columns: 1fr auto; align-items: center; gap: 14px;
    background: var(--bg-elevated); border: 1px solid var(--border-strong);
    border-radius: 10px; box-shadow: 0 16px 44px rgba(0,0,0,0.45); padding: 16px 18px;
    color: var(--fg-primary); font-size: var(--text-base);
  }
  .opts { display: flex; flex-direction: column; gap: 7px; }
  .check { display: flex; align-items: center; gap: 8px; }
  .check input { accent-color: var(--accent); }
  .delay { display: flex; align-items: center; gap: 6px; color: var(--fg-secondary); font-size: var(--text-small); }
  .delay input { width: 52px; height: 26px; background: var(--bg-field); border: 1px solid var(--border); border-radius: var(--radius); color: var(--fg-primary); padding: 0 6px; }
  .capture {
    grid-row: span 1; width: 96px; height: 96px; border-radius: 50%;
    border: none; background: var(--danger); color: #fff; font-size: 16px; font-weight: 700;
    cursor: pointer; box-shadow: 0 4px 14px rgba(0,0,0,0.35);
  }
  .capture:hover { filter: brightness(1.06); }
  .links { grid-column: 1 / -1; display: flex; gap: 14px; justify-content: flex-start; }
  .link { border: none; background: transparent; color: var(--accent-strong); cursor: pointer; font-size: var(--text-base); padding: 0; }
  .link:hover { text-decoration: underline; }
</style>
