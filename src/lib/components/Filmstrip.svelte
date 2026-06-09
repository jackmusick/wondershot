<script lang="ts">
  import { captures, activeItem, view } from '$lib/stores';
  import type { Capture } from '$lib/types';

  let now = $state(Date.now());

  function open(c: Capture) {
    activeItem.set(c);
    view.set(c.kind === 'video' ? 'video' : 'editor');
  }

  // "Today" / "Yesterday" / M/D for the card's date band (bottom-left).
  function dateLabel(ms: number): string {
    const d = new Date(ms);
    const startOf = (t: number) => { const x = new Date(t); x.setHours(0, 0, 0, 0); return x.getTime(); };
    const today = startOf(now);
    const day = startOf(ms);
    if (day === today) return 'Today';
    if (day === today - 86400000) return 'Yesterday';
    return `${d.getMonth() + 1}/${d.getDate()}`;
  }

  // h:MM AM/PM (bottom-right), matching the Qt delegate.
  function timeLabel(ms: number): string {
    const d = new Date(ms);
    let h = d.getHours();
    const m = String(d.getMinutes()).padStart(2, '0');
    const ap = h >= 12 ? 'PM' : 'AM';
    h = h % 12 || 12;
    return `${h}:${m}${ap}`;
  }
</script>

<div class="filmstrip">
  {#each $captures as c (c.id)}
    <button
      class="card"
      class:selected={$activeItem?.id === c.id}
      onclick={() => open(c)}
      title={c.title}
    >
      <img class="thumb" src={c.thumbnail} alt={c.title} />
      {#if c.kind === 'video'}<span class="play">▶</span>{/if}
      <span class="band">
        <span class="date">{dateLabel(c.createdAt)}</span>
        <span class="time">{timeLabel(c.createdAt)}</span>
      </span>
    </button>
  {/each}
  {#if $captures.length === 0}
    <div class="empty">No captures yet</div>
  {/if}
</div>

<style>
  .filmstrip {
    display: flex;
    flex-direction: row;
    gap: 10px;
    align-items: center;
    height: 150px;
    flex-shrink: 0;
    padding: 10px 12px;
    background: var(--bg-app, #0d0d0f);
    border-top: 1px solid var(--border, #2a2a2e);
    overflow-x: auto;
    overflow-y: hidden;
  }
  .card {
    position: relative;
    flex: 0 0 auto;
    width: 188px;
    height: 116px;
    padding: 0;
    border: 1px solid var(--border, #2a2a2e);
    border-radius: var(--radius, 6px);
    background: var(--bg-field, #1c1c20);
    overflow: hidden;
    cursor: default;
  }
  .card:hover { border-color: var(--fg-secondary, #6b6b72); }
  .card.selected { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
  .thumb { width: 100%; height: 100%; object-fit: cover; display: block; }
  .play {
    position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
    font-size: 28px; color: #fff; text-shadow: 0 1px 4px rgba(0,0,0,0.6); pointer-events: none;
  }
  .band {
    position: absolute; left: 0; right: 0; bottom: 0;
    display: flex; justify-content: space-between;
    padding: 3px 6px;
    font-size: var(--text-small, 11.5px); color: #fff;
    background: linear-gradient(to top, rgba(0,0,0,0.7), rgba(0,0,0,0));
  }
  .empty { color: var(--fg-secondary); font-size: var(--text-small); padding: 0 8px; }
</style>
