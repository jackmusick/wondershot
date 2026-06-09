<script lang="ts">
  import { onMount } from 'svelte';
  import { loadLibrary, takeCapture, openEditorByPath, importPaths } from '$lib/stores';
  import { ipcListen, ipcEmit } from '$lib/ipc';
  import { initRecordingEvents } from '$lib/recorder/control';
  import { activeItem } from '$lib/stores';
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
      uns.push(await ipcListen<string>('capture://done', async () => { await loadLibrary(); }));
      // CLI / global-hotkey forwarding (parity with the Python --capture model).
      uns.push(await ipcListen('cli://capture', () => takeCapture('region')));
      uns.push(await ipcListen('cli://fullscreen', () => takeCapture('fullscreen')));
      uns.push(await ipcListen<string>('cli://edit', (p) => openEditorByPath(p)));
      uns.push(await ipcListen<string[]>('cli://import', (fs) => importPaths(fs)));
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
</script>

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
