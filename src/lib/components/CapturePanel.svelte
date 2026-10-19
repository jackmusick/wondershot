<script lang="ts">
  // Compact "Snagit-style" capture panel: a few capture defaults + a big
  // selection button, plus full screen and recording actions.
  import { capturePanelOpen, takeCapture } from '$lib/stores';
  import { ipcInvoke } from '$lib/ipc';
  import {
    openScreenCaptureSettings,
    requestScreenCapturePermission,
    screenCaptureBlocked,
    screenCapturePermissionStatus,
    type ScreenCapturePermission
  } from '$lib/capture/permissions';
  import { startRecording } from '$lib/recorder/control';

  let copyAfter = $state(true);
  let preview = $state(true);
  let cursor = $state(false);
  let delay = $state(0);
  let loaded = $state(false);
  let permission = $state<ScreenCapturePermission | null>(null);
  let permissionBusy = $state(false);
  let permissionMsg = $state('');
  let permissionErr = $state('');
  let lastPersisted = '';

  function snapshot() {
    return JSON.stringify({ copy_after_capture: copyAfter, show_gallery_after_capture: preview, capture_cursor: cursor, capture_delay: delay });
  }

  async function load() {
    const s = (await ipcInvoke<Record<string, unknown>>('get_settings')) ?? {};
    copyAfter = s.copy_after_capture !== false;
    preview = s.show_gallery_after_capture !== false;
    cursor = s.capture_cursor === true;
    delay = Number(s.capture_delay ?? 0);
    await refreshPermission();
    lastPersisted = snapshot();
    loaded = true;
  }

  $effect(() => {
    if ($capturePanelOpen && !loaded) load();
  });

  async function persist() {
    const next = snapshot();
    if (next === lastPersisted) return;
    await ipcInvoke('set_settings', {
      values: {
        copy_after_capture: copyAfter,
        show_gallery_after_capture: preview,
        capture_cursor: cursor,
        capture_delay: delay,
      },
    });
    lastPersisted = next;
  }

  function close() {
    capturePanelOpen.set(false);
  }

  async function refreshPermission() {
    permissionErr = '';
    permissionMsg = '';
    try {
      permission = await screenCapturePermissionStatus();
    } catch (err) {
      permissionErr = err instanceof Error ? err.message : String(err);
    }
  }

  async function requestPermission() {
    permissionBusy = true;
    permissionErr = '';
    permissionMsg = '';
    try {
      permission = await requestScreenCapturePermission();
      permissionMsg = permission.granted
        ? 'Screen Recording permission is enabled.'
        : 'If macOS has already denied access, enable Wondershot in System Settings and try again.';
    } catch (err) {
      permissionErr = err instanceof Error ? err.message : String(err);
    } finally {
      permissionBusy = false;
    }
  }

  async function openPermissionSettings() {
    permissionBusy = true;
    permissionErr = '';
    permissionMsg = '';
    try {
      await openScreenCaptureSettings();
      permissionMsg = 'Wondershot should now appear in Screen Recording. Enable it, then click Try Again.';
    } catch (err) {
      permissionErr = err instanceof Error ? err.message : String(err);
    } finally {
      permissionBusy = false;
    }
  }

  async function capture(mode: 'region' | 'fullscreen' | 'window') {
    await persist();
    await refreshPermission();
    if (screenCaptureBlocked(permission)) return;
    close();
    await takeCapture(mode);
  }

  async function record(mode: 'screen' | 'region' = 'screen') {
    await persist();
    close();
    await startRecording(mode);
  }
</script>

{#if $capturePanelOpen}
  <div class="overlay">
    <button class="backdrop" aria-label="Close capture panel" onclick={close}></button>
    <div class="panel" role="dialog" aria-label="Capture">
      <div class="opts">
        {#if screenCaptureBlocked(permission)}
          <div class="permission">
            <strong>Screen Recording permission required</strong>
            <span>Wondershot needs macOS Screen Recording permission before the capture overlay opens.</span>
            {#if permissionMsg}<span class="perm-msg">{permissionMsg}</span>{/if}
            {#if permissionErr}<span class="perm-err">{permissionErr}</span>{/if}
            <div class="perm-actions">
              <button disabled={permissionBusy} onclick={requestPermission}>Request Permission</button>
              <button disabled={permissionBusy} onclick={openPermissionSettings}>Open Settings</button>
              <button disabled={permissionBusy} onclick={refreshPermission}>Try Again</button>
            </div>
          </div>
        {:else}
          <label class="check"><input type="checkbox" bind:checked={preview} /> Preview in editor</label>
          <label class="check"><input type="checkbox" bind:checked={copyAfter} /> Copy to clipboard</label>
          <label class="check"><input type="checkbox" bind:checked={cursor} /> Capture cursor</label>
          <label class="delay">
            Delay
            <input type="number" min="0" max="10" bind:value={delay} /> s
          </label>
        {/if}
      </div>
      <button class="capture" disabled={screenCaptureBlocked(permission)} onclick={() => capture('region')} title="Select a region or hover a window">
        Capture
      </button>
      <div class="links">
        <button class="link" disabled={screenCaptureBlocked(permission)} onclick={() => capture('fullscreen')}>Full screen</button>
        <button class="link" disabled={screenCaptureBlocked(permission)} onclick={() => capture('window')}>Window</button>
        <button class="link" onclick={() => record()}>Record</button>
        <button class="link" onclick={() => record('region')}>Record Region</button>
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
    border-radius: var(--bf-radius-feature); box-shadow: var(--bf-shadow-modal); padding: 16px 18px;
    color: var(--fg-primary); font-size: var(--text-base);
  }
  .opts { display: flex; flex-direction: column; gap: 7px; }
  .permission { display: grid; gap: 7px; max-width: 360px; }
  .permission strong { font-size: var(--text-base); }
  .permission span { color: var(--fg-secondary); font-size: var(--text-small); line-height: 1.35; }
  .permission .perm-msg { color: var(--accent-strong); }
  .permission .perm-err { color: var(--danger); }
  .perm-actions { display: flex; flex-wrap: wrap; gap: 8px; padding-top: 3px; }
  .perm-actions button {
    height: var(--bf-control-height); border: 1px solid var(--border); border-radius: var(--radius);
    background: var(--bg-field); color: var(--fg-primary); padding: 0 10px; cursor: pointer;
    font-size: var(--text-small);
  }
  .perm-actions button:hover:not(:disabled) { background: var(--bg-hover); }
  .check { display: flex; align-items: center; gap: 8px; }
  .check input { accent-color: var(--accent); }
  .delay { display: flex; align-items: center; gap: 6px; color: var(--fg-secondary); font-size: var(--text-small); }
  .delay input { width: 52px; height: var(--bf-control-height); background: var(--bg-field); border: 1px solid var(--border); border-radius: var(--radius); color: var(--fg-primary); padding: 0 6px; }
  .capture {
    grid-row: span 1; width: 104px; height: 80px; border-radius: var(--bf-radius-control);
    border: none; background: var(--bf-primary); color: var(--bf-primary-foreground); font-size: 16px; font-weight: 700;
    cursor: pointer; box-shadow: none;
  }
  .capture:hover { filter: brightness(1.06); }
  .capture:disabled { opacity: 0.45; cursor: default; filter: none; }
  .links { grid-column: 1 / -1; display: flex; gap: 14px; justify-content: flex-start; }
  .link { border: none; background: transparent; color: var(--accent-strong); cursor: pointer; font-size: var(--text-base); padding: 0; }
  .link:hover { text-decoration: underline; }
  .link:disabled { opacity: 0.45; cursor: default; text-decoration: none; }
</style>
