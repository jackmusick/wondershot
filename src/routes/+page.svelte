<script lang="ts">
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { loadLibrary, takeCapture, openEditorByPath, importPaths, trashItems, selectedCapturePaths } from '$lib/stores';
  import { ipcListen, ipcEmit, ipcInvoke } from '$lib/ipc';
  import { initRecordingEvents, startRecording, startRecordingRect } from '$lib/recorder/control';
  import { activeItem, captureError, captures } from '$lib/stores';
  import CaptureHeader from '$lib/components/CaptureHeader.svelte';
  import MainTitlebar from '$lib/components/MainTitlebar.svelte';
  import ContentView from '$lib/components/ContentView.svelte';
  import PropertiesPanel from '$lib/components/PropertiesPanel.svelte';
  import ZoomBar from '$lib/components/ZoomBar.svelte';
  import Filmstrip from '$lib/components/Filmstrip.svelte';
  import Settings from '$lib/components/Settings.svelte';
  import CapturePanel from '$lib/components/CapturePanel.svelte';
  onMount(() => {
    const uns: Array<() => void> = [];
    let unRecording: (() => void) | undefined;
    loadLibrary().then(async () => {
      uns.push(await ipcListen<string>('capture://done', async (path) => {
        await loadLibrary();
        const justTaken = get(captures).find((c) => c.path === path);
        if (justTaken) activeItem.set(justTaken);
        // Copy-after-capture: honor the setting (also driven from the CapturePanel
        // toggle). The capture://done event fires for every capture path
        // (panel, CLI, global hotkey), so this is the single place to do it.
        try {
          const s = (await ipcInvoke<Record<string, unknown>>('get_settings')) ?? {};
          if (s.copy_after_capture !== false && path) {
            await ipcInvoke('copy_image', { path });
          }
          if (s.auto_share_after_capture === true && path) {
            await ipcInvoke('share_capture', { path });
          }
        } catch (e) {
          console.error('post-capture action failed', e);
        }
      }));
      // Live folder watching: the backend debounce-emits this when a media file
      // lands in / leaves a watched dir (global hotkey, external drop).
      uns.push(await ipcListen('library://changed', () => void loadLibrary()));
      // CLI / global-hotkey forwarding: the backend starts direct region
      // capture on Linux and restores the main window when it completes.
      uns.push(await ipcListen('cli://capture', () => void ipcInvoke('show_capture_window')));
      uns.push(await ipcListen<string>('capture://failed', (error) => {
        const message = String(error);
        if (!/cancel(?:led|ed)?/i.test(message)) captureError.set(message);
      }));
      uns.push(await ipcListen('cli://fullscreen', () => takeCapture('fullscreen')));
      uns.push(await ipcListen<string>('cli://edit', (p) => openEditorByPath(p)));
      uns.push(await ipcListen<string[]>('cli://import', (fs) => importPaths(fs)));
      uns.push(await ipcListen<[number, number, number, number]>('region://record-rect', (rect) => {
        void startRecordingRect(rect);
      }));
      // The framed capture window forwards its actions here so the result lands
      // in this window's library + editor.
      uns.push(await ipcListen<{ kind: 'capture' | 'record'; mode?: 'region' | 'fullscreen' | 'window' | 'screen' }>(
        'capture-cmd',
        (p) => {
          if (p.kind === 'record') {
            void startRecording(p.mode === 'screen' ? 'display' : p.mode === 'region' ? 'region' : 'screen');
          }
          else void takeCapture(p.mode === 'screen' ? 'fullscreen' : p.mode ?? 'region');
        }
      ));
      // Signal the backend that cli:// listeners are attached; it then dispatches
      // any launch args it deferred.
      await ipcEmit('app://ready');
    });
    initRecordingEvents().then((un) => {
      unRecording = un;
    });
    return () => {
      uns.forEach((un) => un());
      unRecording?.();
    };
  });

  /** True when focus is in a text field / contenteditable (don't hijack keys). */
  function isTyping(): boolean {
    const el = document.activeElement as HTMLElement | null;
    if (!el) return false;
    const tag = el.tagName;
    return tag === 'INPUT' || tag === 'TEXTAREA' || el.isContentEditable;
  }

  /** Step the active selection through the filmstrip (parity with the Qt app's
   * left/right gallery navigation). */
  function step(delta: number) {
    const list = get(captures);
    if (list.length === 0) return;
    const cur = get(activeItem);
    const idx = cur ? list.findIndex((c) => c.id === cur.id) : -1;
    const next = list[Math.max(0, Math.min(list.length - 1, idx + delta))];
    if (next && next.id !== cur?.id) {
      activeItem.set(next);
      selectedCapturePaths.set([next.path]);
    }
  }

  async function onKeyDown(e: KeyboardEvent) {
    if (isTyping()) return;
    // Ctrl/Cmd+C → copy the current image to the clipboard.
    if ((e.ctrlKey || e.metaKey) && (e.key === 'c' || e.key === 'C')) {
      const cur = get(activeItem);
      const paths = get(selectedCapturePaths);
      const selected = get(captures).filter((item) => paths.includes(item.path));
      if (selected.length > 1 || selected[0]?.kind === 'video') {
        e.preventDefault();
        try {
          await ipcInvoke('copy_files', { paths: selected.map((item) => item.path) });
        } catch (err) {
          console.error('copy failed', err);
        }
      } else if (selected.length === 1 || (cur && cur.kind !== 'video')) {
        e.preventDefault();
        try {
          await ipcInvoke('copy_image', { path: selected[0]?.path ?? cur!.path });
        } catch (err) {
          console.error('copy failed', err);
        }
      }
      return;
    }
    if (e.key === 'Delete') {
      const paths = get(selectedCapturePaths);
      const selected = get(captures).filter((item) => paths.includes(item.path));
      if (selected.length > 0) {
        e.preventDefault();
        await trashItems(selected);
      }
      return;
    }
    if (e.key === 'ArrowLeft') { e.preventDefault(); step(-1); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); step(1); }
  }
</script>

<svelte:window on:keydown={onKeyDown} />

<div class="shell">
  <MainTitlebar />
  <CaptureHeader />
  {#if $captureError}
    <div class="capture-error" role="alert">
      <span>Capture failed: {$captureError}</span>
      <button aria-label="Dismiss capture error" onclick={() => captureError.set('')}>Close</button>
    </div>
  {/if}
  <div class="work">
    <ContentView />
    {#if $activeItem && $activeItem.kind !== 'video'}
      <PropertiesPanel />
    {/if}
  </div>
  {#if $activeItem && $activeItem.kind !== 'video'}
    <ZoomBar />
  {/if}
  <Filmstrip />
  <Settings />
  <CapturePanel />
</div>

<style>
  .shell { display: flex; flex-direction: column; height: 100vh; background: var(--bg-content); }
  .work { flex: 1; display: flex; min-height: 0; }
  .capture-error {
    display: flex; align-items: center; justify-content: space-between; gap: 16px;
    padding: 8px 12px; color: #fff; background: color-mix(in srgb, var(--danger) 78%, #111);
    border-bottom: 1px solid var(--danger); font-size: var(--text-small); flex-shrink: 0;
  }
  .capture-error button {
    border: 1px solid rgba(255,255,255,.45); border-radius: var(--radius); padding: 3px 9px;
    background: transparent; color: inherit; cursor: pointer;
  }
</style>
