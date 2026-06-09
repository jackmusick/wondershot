<script lang="ts">
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import { loadLibrary } from '$lib/stores';
  import LibrarySidebar from '$lib/components/LibrarySidebar.svelte';
  import CaptureHeader from '$lib/components/CaptureHeader.svelte';
  import EditorCanvas from '$lib/editor/EditorCanvas.svelte';
  let screen = $derived(page.url.searchParams.get('screen') ?? 'shell');
  onMount(loadLibrary);
</script>

{#if screen === 'sidebar'}
  <div style="height:100vh;display:flex"><LibrarySidebar /></div>
{:else if screen === 'header'}
  <div style="background:var(--bg-content)"><CaptureHeader /></div>
{:else if screen === 'editor'}
  <div style="height:100vh;display:flex;background:var(--bg-content)">
    <EditorCanvas path="/fixtures/editor-base.png" />
  </div>
{:else}
  <a href="/">full shell at /</a>
{/if}
