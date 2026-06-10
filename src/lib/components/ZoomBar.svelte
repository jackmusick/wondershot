<script lang="ts">
  // The little bar below the canvas (Qt parity): image resolution on the left,
  // zoom controls + the library count ("N shots") on the right. Reads
  // viewInfo + captures, drives zoomApi.
  import { zoomApi, viewInfo } from '$lib/editor/zoom';
  import { captures } from '$lib/stores';

  function zoom(fn: 'zoomIn' | 'zoomOut' | 'zoomActual' | 'zoomFit') {
    $zoomApi?.[fn]();
  }
  let pct = $derived($viewInfo ? Math.round($viewInfo.zoom * 100) : 100);
</script>

<div class="zoombar">
  <span class="dims">
    {#if $viewInfo}{$viewInfo.width} × {$viewInfo.height}{/if}
  </span>
  <div class="spacer"></div>
  <div class="zoom">
    <button class="zbtn" title="Zoom out" aria-label="Zoom out" onclick={() => zoom('zoomOut')}>−</button>
    <button class="ztext" title="Fit to view" onclick={() => zoom('zoomFit')}>Fit</button>
    <button class="ztext pct" title="Actual size (100%)" onclick={() => zoom('zoomActual')}>{pct}%</button>
    <button class="zbtn" title="Zoom in" aria-label="Zoom in" onclick={() => zoom('zoomIn')}>+</button>
  </div>
  <span class="shots">{$captures.length} {$captures.length === 1 ? 'shot' : 'shots'}</span>
</div>

<style>
  .zoombar {
    height: 30px;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 0 12px;
    background: var(--bg-content);
    border-top: 1px solid var(--border);
    flex-shrink: 0;
  }
  .dims { font-size: var(--text-small); color: var(--fg-secondary); font-variant-numeric: tabular-nums; }
  .spacer { flex: 1; }
  .zoom { display: flex; align-items: center; gap: 2px; }
  .zbtn,
  .ztext {
    height: 22px;
    border: 1px solid var(--border);
    background: var(--bg-field);
    color: var(--fg-primary);
    border-radius: var(--radius);
    cursor: pointer;
    font-size: var(--text-small);
  }
  .zbtn { width: 24px; font-size: 14px; line-height: 1; }
  .ztext { padding: 0 8px; }
  .pct { min-width: 46px; font-variant-numeric: tabular-nums; }
  .zbtn:hover,
  .ztext:hover { background: var(--bg-hover); }
  .shots {
    margin-left: 8px;
    font-size: var(--text-small);
    color: var(--fg-secondary);
    font-variant-numeric: tabular-nums;
  }
</style>
