<script lang="ts">
  import { onMount } from 'svelte';
  import { loadLibrary } from '$lib/stores';
  import LibrarySidebar from '$lib/components/LibrarySidebar.svelte';
  import CaptureHeader from '$lib/components/CaptureHeader.svelte';
  import ContentView from '$lib/components/ContentView.svelte';
  onMount(loadLibrary);
</script>

<div class="shell">
  <LibrarySidebar />
  <main class="content">
    <CaptureHeader />
    <ContentView />
  </main>
</div>

<style>
  .shell { display: flex; height: 100vh; }
  .content { flex: 1; display: flex; flex-direction: column; background: var(--bg-content); min-width: 0; }
</style>
