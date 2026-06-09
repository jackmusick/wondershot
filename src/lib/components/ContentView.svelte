<script lang="ts">
  import { activeItem } from '$lib/stores';
  import EditorCanvas from '$lib/editor/EditorCanvas.svelte';
  import VideoPlayer from '$lib/video/VideoPlayer.svelte';
</script>

<div class="content-body" class:editor={$activeItem && $activeItem.kind !== 'video'} class:video={$activeItem?.kind === 'video'}>
  {#if $activeItem}
    <!-- Key on path so switching captures remounts the player/editor and
         reloads the new file (the editor builds its Konva stage in onMount and
         doesn't otherwise react to a path-prop change → looked frozen). -->
    {#key $activeItem.path}
      {#if $activeItem.kind === 'video'}
        <VideoPlayer path={$activeItem.path} />
      {:else}
        <EditorCanvas path={$activeItem.path} />
      {/if}
    {/key}
  {:else}
    <div class="placeholder">Select or take a capture</div>
  {/if}
</div>

<style>
  .content-body { flex: 1; display: flex; align-items: center; justify-content: center; overflow: auto; min-height: 0; background: var(--bg-app); }
  /* Editor fills the body instead of centering a shrink-wrapped child. */
  .content-body.editor,
  .content-body.video { align-items: stretch; justify-content: stretch; overflow: hidden; }
  .placeholder { color: var(--fg-secondary); font-size: var(--text-small); }
</style>
