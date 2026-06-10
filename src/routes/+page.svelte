<script lang="ts">
  import { onMount } from 'svelte';
  import { get } from 'svelte/store';
  import { loadLibrary, takeCapture, openEditorByPath, importPaths } from '$lib/stores';
  import { ipcListen, ipcEmit, ipcInvoke } from '$lib/ipc';
  import { initRecordingEvents, startRecording } from '$lib/recorder/control';
  import { activeItem, captures } from '$lib/stores';
  import CaptureHeader from '$lib/components/CaptureHeader.svelte';
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
        // Copy-after-capture: honor the setting (also driven from the CapturePanel
        // toggle). The capture://done event fires for every capture path
        // (panel, CLI, global hotkey), so this is the single place to do it.
        try {
          const s = (await ipcInvoke<Record<string, unknown>>('get_settings')) ?? {};
          if (s.copy_after_capture !== false && path) {
            await ipcInvoke('copy_image', { path });
          }
        } catch (e) {
          console.error('copy-after-capture failed', e);
        }
      }));
      // Live folder watching: the backend debounce-emits this when a media file
      // lands in / leaves a watched dir (Spectacle hotkey, external drop).
      uns.push(await ipcListen('library://changed', () => void loadLibrary()));
      // CLI / global-hotkey forwarding (parity with the Python --capture model).
      uns.push(await ipcListen('cli://capture', () => takeCapture('region')));
      uns.push(await ipcListen('cli://fullscreen', () => takeCapture('fullscreen')));
      uns.push(await ipcListen<string>('cli://edit', (p) => openEditorByPath(p)));
      uns.push(await ipcListen<string[]>('cli://import', (fs) => importPaths(fs)));
      // The framed capture window forwards its actions here so the result lands
      // in this window's library + editor.
      uns.push(await ipcListen<{ kind: 'capture' | 'record'; mode?: 'region' | 'fullscreen' | 'window' }>(
        'capture-cmd',
        (p) => {
          if (p.kind === 'record') void startRecording();
          else void takeCapture(p.mode ?? 'region');
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
    if (next && next.id !== cur?.id) activeItem.set(next);
  }

  async function onKeyDown(e: KeyboardEvent) {
    if (isTyping()) return;
    // Ctrl/Cmd+C → copy the current image to the clipboard.
    if ((e.ctrlKey || e.metaKey) && (e.key === 'c' || e.key === 'C')) {
      const cur = get(activeItem);
      if (cur && cur.kind !== 'video') {
        e.preventDefault();
        try {
          await ipcInvoke('copy_image', { path: cur.path });
        } catch (err) {
          console.error('copy failed', err);
        }
      }
      return;
    }
    if (e.key === 'ArrowLeft') { e.preventDefault(); step(-1); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); step(1); }
  }
</script>

<svelte:window on:keydown={onKeyDown} />

<div class="shell">
  <CaptureHeader />
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
</style>
