<script lang="ts">
  import { activeItem, view } from '$lib/stores';
  import EditorCanvas from '$lib/editor/EditorCanvas.svelte';
</script>

<div class="content-body" class:editor={$activeItem && $view === 'editor'}>
  {#if $activeItem}
    {#if $view === 'gallery'}
      <img class="preview" src={$activeItem.thumbnail} alt={$activeItem.title} />
    {:else if $view === 'editor'}
      <EditorCanvas path={$activeItem.path} />
    {:else}
      <div class="placeholder">{$view} view — built in a later milestone</div>
    {/if}
  {:else}
    <div class="placeholder">Select or take a capture</div>
  {/if}
</div>

<style>
  .content-body { flex: 1; display: flex; align-items: center; justify-content: center; overflow: auto; min-height: 0; }
  /* Editor fills the body instead of centering a shrink-wrapped child. */
  .content-body.editor { align-items: stretch; justify-content: stretch; overflow: hidden; }
  .preview { max-width: 90%; max-height: 90%; border-radius: var(--radius); box-shadow: 0 8px 24px rgba(0,0,0,0.4); }
  .placeholder { color: var(--fg-secondary); font-size: var(--text-small); }
</style>
