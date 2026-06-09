<script lang="ts">
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import { loadLibrary } from '$lib/stores';
  import Filmstrip from '$lib/components/Filmstrip.svelte';
  import CaptureHeader from '$lib/components/CaptureHeader.svelte';
  import EditorCanvas from '$lib/editor/EditorCanvas.svelte';
  import EditorToolbar from '$lib/editor/EditorToolbar.svelte';
  import VideoPlayer from '$lib/video/VideoPlayer.svelte';
  import Settings from '$lib/components/Settings.svelte';
  let screen = $derived(page.url.searchParams.get('screen') ?? 'shell');
  onMount(loadLibrary);
</script>

{#if screen === 'filmstrip'}
  <div style="background:var(--bg-content)"><Filmstrip /></div>
{:else if screen === 'header'}
  <div style="background:var(--bg-content)"><CaptureHeader /></div>
{:else if screen === 'editor'}
  <div style="height:100vh;display:flex;flex-direction:column;background:var(--bg-content)">
    <EditorToolbar />
    <div style="flex:1;display:flex;min-height:0">
      <EditorCanvas path="/fixtures/editor-base.png" />
    </div>
  </div>
{:else if screen === 'video'}
  <div style="height:100vh;display:flex;flex-direction:column;background:var(--bg-content)">
    <VideoPlayer path="/lib/Recording_20260608_112000.mp4" />
  </div>
{:else if screen === 'settings'}
  <div style="height:100vh;background:var(--bg-content)">
    <Settings open={true} />
  </div>
{:else}
  <a href="/">full shell at /</a>
{/if}
