<script lang="ts">
  let { name }: { name: 'trim' | 'cut' | 'save' | 'blur' | 'screenshot' | 'undo' | 'redo' | 'gif' | 'close' | 'delete' | 'apply' } = $props();
</script>

<svg viewBox="0 0 16 16" aria-hidden="true" focusable="false">
  {#if name === 'blur'}
    <circle cx="8" cy="8" r="5.5" stroke-dasharray="2 2" />
  {:else if name === 'undo'}
    <path d="M6 3L2.5 6.5 6 10M2.5 6.5H10a3.5 3.5 0 0 1 0 7H7" />
  {:else if name === 'redo'}
    <path d="M10 3l3.5 3.5L10 10M13.5 6.5H6a3.5 3.5 0 0 0 0 7h3" />
  {:else if name === 'screenshot'}
    <path d="M2 4.5h3l1-2h4l1 2h3v9H2z" /><circle cx="8" cy="9" r="2.5" />
  {:else if name === 'trim'}
    <path d="M4 2v12M12 2v12M1.5 4H4m8 0h2.5M1.5 12H4m8 0h2.5M6 8h4" />
  {:else if name === 'cut'}
    <circle cx="3.5" cy="4" r="2" /><circle cx="3.5" cy="12" r="2" /><path d="M5 5.5L14 13M5 10.5L14 3" />
  {:else if name === 'save'}
    <path d="M2 2h10l2 2v10H2zM5 2v4h6V2M5 14V9h6v5" />
  {:else if name === 'gif'}
    <rect x="2" y="2" width="12" height="12" rx="1" /><path d="M5 2v12M11 2v12M2 5h3m-3 6h3m6-6h3m-3 6h3M7 6l3 2-3 2z" />
  {:else if name === 'delete'}
    <path d="M2 4h12M6 4V2h4v2M4 4l1 10h6l1-10M7 7v4m2-4v4" />
  {:else if name === 'apply'}
    <path d="M3 8l3.5 3.5L13 4.5" />
  {:else}
    <path d="M3 3l10 10M13 3L3 13" />
  {/if}
</svg>

<style>
  svg { width:18px; height:18px; fill:none; stroke:currentColor; stroke-width:1.5; stroke-linecap:round; stroke-linejoin:round; flex-shrink:0; }
</style>
