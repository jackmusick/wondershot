<script lang="ts">
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import { loadLibrary } from '$lib/stores';
  import LibrarySidebar from '$lib/components/LibrarySidebar.svelte';
  import CaptureHeader from '$lib/components/CaptureHeader.svelte';
  let screen = $derived(page.url.searchParams.get('screen') ?? 'shell');
  onMount(loadLibrary);
</script>

{#if screen === 'sidebar'}
  <div style="height:100vh;display:flex"><LibrarySidebar /></div>
{:else if screen === 'header'}
  <div style="background:var(--bg-content)"><CaptureHeader /></div>
{:else}
  <a href="/">full shell at /</a>
{/if}
