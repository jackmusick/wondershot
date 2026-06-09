<script lang="ts">
  import '$lib/styles/tokens.css';
  import '$lib/styles/global.css';
  let { children } = $props();
</script>

<svelte:head>
  <script>
    document.documentElement.setAttribute('data-theme', 'dark');
  </script>
</svelte:head>

{@render children()}
