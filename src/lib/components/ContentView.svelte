<script lang="ts">
  import { activeItem } from '$lib/stores';
  import EditorCanvas from '$lib/editor/EditorCanvas.svelte';
  import VideoPlayer from '$lib/video/VideoPlayer.svelte';
</script>

<div class="content-body" class:editor={$activeItem && $activeItem.kind !== 'video'} class:video={$activeItem?.kind === 'video'}>
  {#if $activeItem}
    {#if $activeItem.kind === 'video'}
      <VideoPlayer path={$activeItem.path} />
    {:else}
      <EditorCanvas path={$activeItem.path} />
    {/if}
  {:else}
    <div class="placeholder">Select or take a capture</div>
  {/if}
</div>

<style>
  .content-body { flex: 1; display: flex; align-items: center; justify-content: center; overflow: auto; min-height: 0; background: var(--bg-app); }
  /* Editor fills the body instead of centering a shrink-wrapped child. */
  .content-body.editor,
  .content-body.video { align-items: stretch; justify-content: stretch; overflow: hidden; }
  .preview { max-width: 90%; max-height: 90%; border-radius: var(--radius); box-shadow: 0 8px 24px rgba(0,0,0,0.4); }
  .placeholder { color: var(--fg-secondary); font-size: var(--text-small); }
</style>
