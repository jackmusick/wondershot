<script lang="ts">
  import { captures, activeItem } from '$lib/stores';
  import { groupByDate } from '$lib/library';
  import type { Capture } from '$lib/types';
  let now = Date.now();
  let groups = $derived(groupByDate($captures, now));
  function select(c: Capture) { activeItem.set(c); }
</script>

<aside class="sidebar">
  <div class="list">
    {#each groups as g}
      <div class="group-label">{g.label}</div>
      {#each g.items as c}
        <button class="row" class:selected={$activeItem?.id === c.id} onclick={() => select(c)}>
          <img class="thumb" src={c.thumbnail} alt="" />
          <span class="title">{c.title}</span>
          <span class="kind">{c.kind === 'video' ? '▶' : ''}</span>
        </button>
      {/each}
    {/each}
  </div>
  <button class="settings">⚙ Settings</button>
</aside>

<style>
  .sidebar {
    width: 240px; flex-shrink: 0; display: flex; flex-direction: column;
    background: var(--bg-sidebar); padding: 8px; overflow-y: auto;
  }
  .list { flex: 1; display: flex; flex-direction: column; gap: 1px; }
  .group-label {
    font-size: var(--text-small); color: var(--fg-secondary);
    padding: 8px 8px 4px; text-transform: none;
  }
  .row {
    display: flex; align-items: center; gap: 8px; height: var(--row-height);
    padding: 0 8px; border: none; background: transparent; border-radius: var(--radius);
    color: var(--fg-primary); font-size: var(--text-base); cursor: default; text-align: left;
  }
  .row:hover { background: var(--bg-hover); }
  .row.selected { background: var(--bg-selected); box-shadow: inset 2px 0 0 var(--accent); }
  .thumb { width: 28px; height: 18px; object-fit: cover; border-radius: 3px; background: var(--bg-field); }
  .title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .kind { color: var(--fg-secondary); }
  .settings {
    height: 30px; border: none; background: transparent; color: var(--fg-secondary);
    text-align: left; padding: 0 8px; border-radius: var(--radius); cursor: default;
  }
  .settings:hover { background: var(--bg-hover); color: var(--fg-primary); }
</style>
