<script lang="ts">
  import { activeItem, view } from '$lib/stores';
</script>

<div class="content-body">
  {#if $activeItem}
    {#if $view === 'gallery'}
      <img class="preview" src={$activeItem.thumbnail} alt={$activeItem.title} />
    {:else}
      <div class="placeholder">{$view} view — built in a later milestone</div>
    {/if}
  {:else}
    <div class="placeholder">Select or take a capture</div>
  {/if}
</div>

<style>
  .content-body { flex: 1; display: flex; align-items: center; justify-content: center; overflow: auto; }
  .preview { max-width: 90%; max-height: 90%; border-radius: var(--radius); box-shadow: 0 8px 24px rgba(0,0,0,0.4); }
  .placeholder { color: var(--fg-secondary); font-size: var(--text-small); }
</style>
