<script lang="ts">
  import { onMount } from 'svelte';
  import { ipcInvoke } from '$lib/ipc';
  import { settingsOpen } from '$lib/stores';

  let { open = false }: { open?: boolean } = $props();
  // `open` prop forces the modal open (harness/refshots); otherwise the store drives it.
  let visible = $derived(open || $settingsOpen);

  type Tab = 'general' | 'capture' | 'recording' | 'output';
  let tab = $state<Tab>('general');

  type SettingsData = Record<string, unknown>;
  let s = $state<SettingsData>({});
  let loaded = $state(false);

  async function loadSettings() {
    const data = (await ipcInvoke<SettingsData>('get_settings')) ?? {};
    // extra_dirs is an array on the wire; edit it as a semicolon-joined string.
    const dirs = Array.isArray(data.extra_dirs) ? (data.extra_dirs as string[]) : [];
    s = { ...data, extra_dirs_text: dirs.join(';') };
    loaded = true;
  }

  onMount(() => {
    if (open) loadSettings();
  });

  // When opened via the store (gear), (re)load the form.
  let wasOpen = false;
  $effect(() => {
    if (visible && !wasOpen) loadSettings();
    wasOpen = visible;
  });

  function close() {
    settingsOpen.set(false);
  }

  async function save() {
    const snap = { ...$state.snapshot(s) } as SettingsData;
    // Map the edited semicolon string back to an extra_dirs array.
    const text = String(snap.extra_dirs_text ?? '');
    snap.extra_dirs = text
      .split(';')
      .map((x) => x.trim())
      .filter((x) => x.length > 0);
    delete snap.extra_dirs_text;
    await ipcInvoke('set_settings', { values: snap });
    close();
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') close();
  }

  // Typed accessors keep bind:value happy with the loose record.
  function num(k: string): number {
    return Number(s[k] ?? 0);
  }
  function setNum(k: string, v: number) {
    s[k] = v;
  }
</script>

<svelte:window on:keydown={onKey} />

{#if visible && loaded}
  <div class="overlay" role="dialog" aria-modal="true" aria-label="Settings">
    <button class="backdrop" aria-label="Close settings" onclick={close}></button>
    <div class="panel" data-settings-ready="true">
      <div class="head">
        <h2>Settings</h2>
      </div>

      <div class="tabs" role="tablist">
        <button class="tab" class:active={tab === 'general'} role="tab" onclick={() => (tab = 'general')}>General</button>
        <button class="tab" class:active={tab === 'capture'} role="tab" onclick={() => (tab = 'capture')}>Capture</button>
        <button class="tab" class:active={tab === 'recording'} role="tab" onclick={() => (tab = 'recording')}>Recording</button>
        <button class="tab" class:active={tab === 'output'} role="tab" onclick={() => (tab = 'output')}>Output</button>
      </div>

      <div class="body">
        {#if tab === 'general'}
          <label class="field">
            <span>Library folder</span>
            <input type="text" bind:value={s.library_dir} />
            <small>Where screenshots and recordings are saved.</small>
          </label>
          <label class="field">
            <span>Extra folders</span>
            <input type="text" bind:value={s.extra_dirs_text} placeholder="/path/one;/path/two" />
            <small>Semicolon-separated extra folders to show in the library.</small>
          </label>
          <label class="check"><input type="checkbox" bind:checked={s.copy_after_capture} /> Copy to clipboard after capture</label>
          <label class="check"><input type="checkbox" bind:checked={s.show_gallery_after_capture} /> Show gallery after capture</label>
          <label class="check"><input type="checkbox" bind:checked={s.pin_on_top} /> Pin window on top</label>
          <label class="check"><input type="checkbox" bind:checked={s.quick_bar_enabled} /> Enable quick bar</label>
          <label class="field row">
            <span>Quick bar timeout (s)</span>
            <input type="number" min="2" max="60" value={num('quick_bar_timeout')} oninput={(e) => setNum('quick_bar_timeout', e.currentTarget.valueAsNumber)} />
          </label>
          <label class="field">
            <span>Capture hotkey</span>
            <input type="text" bind:value={s.hotkey_capture} />
            <small>On Linux, bind this manually in KDE settings — shown here for reference.</small>
          </label>
        {:else if tab === 'capture'}
          <label class="field row">
            <span>Backend</span>
            <select bind:value={s.backend}>
              <option value="auto">Auto</option>
              <option value="spectacle">Spectacle</option>
              <option value="portal">Portal</option>
            </select>
          </label>
          <label class="check"><input type="checkbox" bind:checked={s.capture_cursor} /> Capture cursor</label>
          <label class="field row">
            <span>Capture delay (s)</span>
            <input type="number" min="0" max="10" value={num('capture_delay')} oninput={(e) => setNum('capture_delay', e.currentTarget.valueAsNumber)} />
          </label>
        {:else if tab === 'recording'}
          <label class="check"><input type="checkbox" bind:checked={s.mic_enabled} /> Record microphone</label>
          <label class="field">
            <span>Microphone device</span>
            <input type="text" bind:value={s.mic_device} placeholder="Default" />
          </label>
          <label class="check"><input type="checkbox" bind:checked={s.noise_suppression} /> Noise suppression</label>
          <label class="field row">
            <span>Countdown (s, 0 = off)</span>
            <input type="number" min="0" max="10" value={num('record_countdown')} oninput={(e) => setNum('record_countdown', e.currentTarget.valueAsNumber)} />
          </label>
          <label class="field">
            <span>Camera device</span>
            <input type="text" bind:value={s.camera_device} placeholder="None" />
          </label>
          <label class="check"><input type="checkbox" bind:checked={s.record_cursor_halo} disabled /> Cursor halo <small class="inline">(coming soon)</small></label>
          <label class="field row">
            <span>Video blur strength</span>
            <input type="number" min="1" max="60" value={num('video_blur_strength')} oninput={(e) => setNum('video_blur_strength', e.currentTarget.valueAsNumber)} />
          </label>
          <label class="field row">
            <span>GIF fps</span>
            <input type="number" min="4" max="30" value={num('gif_fps')} oninput={(e) => setNum('gif_fps', e.currentTarget.valueAsNumber)} />
          </label>
          <label class="field row">
            <span>GIF max width</span>
            <input type="number" min="160" max="1920" value={num('gif_max_width')} oninput={(e) => setNum('gif_max_width', e.currentTarget.valueAsNumber)} />
          </label>
        {:else if tab === 'output'}
          <label class="check"><input type="checkbox" bind:checked={s.effect_rounded} /> Rounded corners</label>
          <label class="field row">
            <span>Corner radius</span>
            <input type="number" min="2" max="64" value={num('effect_corner_radius')} oninput={(e) => setNum('effect_corner_radius', e.currentTarget.valueAsNumber)} />
          </label>
          <label class="check"><input type="checkbox" bind:checked={s.effect_fade} /> Fade edges</label>
          <label class="field row">
            <span>Fade height</span>
            <input type="number" min="8" max="512" value={num('effect_fade_height')} oninput={(e) => setNum('effect_fade_height', e.currentTarget.valueAsNumber)} />
          </label>
          <div class="divider"></div>
          <label class="field row">
            <span>Editor stroke width</span>
            <input type="number" min="1" max="32" value={num('stroke_width')} oninput={(e) => setNum('stroke_width', e.currentTarget.valueAsNumber)} />
          </label>
          <label class="field row">
            <span>Editor font size</span>
            <input type="number" min="6" max="96" value={num('font_size')} oninput={(e) => setNum('font_size', e.currentTarget.valueAsNumber)} />
          </label>
          <label class="field row">
            <span>Tool color</span>
            <input type="color" bind:value={s.tool_color} />
          </label>
        {/if}
      </div>

      <div class="foot">
        <button class="btn ghost" onclick={close}>Cancel</button>
        <button class="btn primary" onclick={save}>Save</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .overlay {
    position: fixed;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 100;
  }
  .backdrop {
    position: absolute;
    inset: 0;
    border: none;
    padding: 0;
    background: rgba(0, 0, 0, 0.3);
    cursor: default;
  }
  .panel {
    position: relative;
    width: 480px;
    max-height: 80vh;
    display: flex;
    flex-direction: column;
    background: var(--bg-elevated);
    border: 1px solid var(--border-strong);
    border-radius: 10px;
    box-shadow: 0 16px 44px rgba(0, 0, 0, 0.45);
    padding: 16px;
    color: var(--fg-primary);
    font-family: var(--font-ui);
    font-size: var(--text-base);
  }
  .head h2 {
    margin: 0 0 12px;
    font-size: 15px;
    font-weight: 600;
  }
  .tabs {
    display: flex;
    gap: 2px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 12px;
  }
  .tab {
    border: none;
    background: transparent;
    color: var(--fg-secondary);
    padding: 6px 10px;
    border-radius: var(--radius) var(--radius) 0 0;
    cursor: default;
    font-size: var(--text-base);
  }
  .tab:hover {
    background: var(--bg-hover);
    color: var(--fg-primary);
  }
  .tab.active {
    color: var(--fg-primary);
    box-shadow: inset 0 -2px 0 var(--accent);
  }
  .body {
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 2px 2px 4px;
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .field span {
    color: var(--fg-secondary);
    font-size: var(--text-small);
  }
  .field.row {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
  }
  .field.row input {
    width: 100px;
  }
  small {
    color: var(--fg-secondary);
    font-size: var(--text-small);
  }
  small.inline {
    margin-left: 4px;
  }
  input[type='text'],
  input[type='number'],
  select {
    height: 28px;
    background: var(--bg-field);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    color: var(--fg-primary);
    padding: 0 8px;
    font-size: var(--text-base);
    font-family: var(--font-ui);
  }
  input[type='color'] {
    height: 28px;
    width: 48px;
    padding: 0 2px;
    background: var(--bg-field);
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }
  .check {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--fg-primary);
  }
  .check input[disabled] {
    opacity: 0.5;
  }
  .divider {
    height: 1px;
    background: var(--border);
    margin: 4px 0;
  }
  .foot {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin-top: 14px;
  }
  .btn {
    height: 28px;
    padding: 0 14px;
    border-radius: var(--radius);
    border: 1px solid transparent;
    cursor: default;
    font-size: var(--text-base);
    font-family: var(--font-ui);
  }
  .btn.primary {
    background: var(--accent);
    color: #fff;
  }
  .btn.primary:hover {
    background: var(--accent-strong);
  }
  .btn.ghost {
    background: transparent;
    border-color: var(--border);
    color: var(--fg-primary);
  }
  .btn.ghost:hover {
    background: var(--bg-hover);
  }
</style>
