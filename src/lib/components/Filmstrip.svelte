<script lang="ts">
  import { captures, activeItem, view, trashItem, pinned, togglePin } from '$lib/stores';
  import { ipcInvoke } from '$lib/ipc';
  import type { Capture } from '$lib/types';

  const USE_MOCK = typeof (globalThis as any).__TAURI_INTERNALS__ === 'undefined';

  let now = $state(Date.now());

  /** Native file drag-out: hand the OS the real file so a file manager copies
   * the contents (not a link). Replaces the webview's default uri-list drag. */
  async function onDragStart(e: DragEvent, c: Capture) {
    e.preventDefault();
    if (USE_MOCK) return;
    try {
      const { startDrag } = await import('@crabnebula/tauri-plugin-drag');
      await startDrag({ item: [c.path], icon: c.path, mode: 'copy' });
    } catch (err) {
      console.error('drag-out failed', err);
    }
  }

  // Pinned cards float to the front of the strip (in pin order), then the rest
  // in their natural (newest-first) order.
  let ordered = $derived.by(() => {
    const pins = $pinned;
    const isPinned = (c: Capture) => pins.includes(c.path);
    const pinnedCards = pins
      .map((p) => $captures.find((c) => c.path === p))
      .filter((c): c is Capture => !!c);
    const rest = $captures.filter((c) => !isPinned(c));
    return [...pinnedCards, ...rest];
  });

  // Right-click context menu state.
  let menu = $state<{ x: number; y: number; cap: Capture } | null>(null);

  function open(c: Capture) {
    activeItem.set(c);
    view.set(c.kind === 'video' ? 'video' : 'editor');
  }

  function del(e: MouseEvent, c: Capture) {
    e.stopPropagation();
    void trashItem(c);
  }

  function pinClick(e: MouseEvent, c: Capture) {
    e.stopPropagation();
    void togglePin(c);
  }

  function openMenu(e: MouseEvent, c: Capture) {
    e.preventDefault();
    menu = { x: e.clientX, y: e.clientY, cap: c };
  }

  function closeMenu() {
    menu = null;
  }

  async function act(kind: 'copy' | 'saveAs' | 'folder' | 'pin' | 'delete') {
    const c = menu?.cap;
    closeMenu();
    if (!c) return;
    try {
      if (kind === 'copy') await ipcInvoke('copy_image', { path: c.path });
      else if (kind === 'saveAs') await ipcInvoke('save_image_as', { path: c.path });
      else if (kind === 'folder') await ipcInvoke('show_in_folder', { path: c.path });
      else if (kind === 'pin') await togglePin(c);
      else if (kind === 'delete') await trashItem(c);
    } catch (err) {
      console.error(`${kind} failed`, err);
    }
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

<svelte:window onclick={closeMenu} />

<div class="filmstrip">
  {#each ordered as c (c.id)}
    <button
      class="card"
      class:selected={$activeItem?.id === c.id}
      class:pinned={$pinned.includes(c.path)}
      onclick={() => open(c)}
      oncontextmenu={(e) => openMenu(e, c)}
      title={c.title}
    >
      {#if c.thumbnail}
        <img class="thumb" src={c.thumbnail} alt={c.title} draggable="true" ondragstart={(e) => onDragStart(e, c)} />
      {:else}
        <!-- No poster available (e.g. ffmpeg missing): dark card, play badge only. -->
        <span class="thumb fallback" role="img" aria-label={c.title} draggable="true" ondragstart={(e) => onDragStart(e, c)}></span>
      {/if}
      {#if c.kind === 'video'}<span class="play">▶</span>{/if}
      <span class="pin" class:on={$pinned.includes(c.path)} role="button" tabindex="-1"
        title={$pinned.includes(c.path) ? 'Unpin' : 'Pin'}
        onclick={(e) => pinClick(e, c)} onkeydown={() => {}}>
        <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
          <path d="M9.5 1.5 14.5 6.5 12 7.5 11 11 8 8 4.5 11.5 4 12l.5-3.5L5.5 5 8.5 4z" />
        </svg>
      </span>
      <span class="del" role="button" tabindex="-1" title="Move to trash"
        onclick={(e) => del(e, c)} onkeydown={() => {}}>×</span>
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

{#if menu}
  <div class="menu" style="left:{menu.x}px; top:{menu.y}px" role="menu">
    <button role="menuitem" onclick={() => act('copy')}>Copy image</button>
    <button role="menuitem" onclick={() => act('saveAs')}>Save as…</button>
    <button role="menuitem" onclick={() => act('folder')}>Show in folder</button>
    <button role="menuitem" onclick={() => act('pin')}>{$pinned.includes(menu.cap.path) ? 'Unpin' : 'Pin'}</button>
    <div class="msep"></div>
    <button role="menuitem" class="danger" onclick={() => act('delete')}>Move to trash</button>
  </div>
{/if}

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
  .card.pinned { border-color: var(--accent); }
  .thumb { width: 100%; height: 100%; object-fit: cover; display: block; }
  .thumb.fallback { background: var(--bg-sidebar, #222); }
  .play {
    position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
    font-size: 28px; color: #fff; text-shadow: 0 1px 4px rgba(0,0,0,0.6); pointer-events: none;
  }
  .pin {
    position: absolute; top: 4px; left: 4px; width: 20px; height: 20px;
    display: none; align-items: center; justify-content: center;
    border-radius: 50%; background: rgba(0,0,0,0.6); color: #fff; cursor: pointer;
  }
  .pin svg { fill: currentColor; stroke: currentColor; stroke-width: 0.5; }
  .card:hover .pin { display: flex; }
  .pin.on { display: flex; background: var(--accent); color: #fff; }
  .pin:hover { background: var(--accent-strong, var(--accent)); }
  .del {
    position: absolute; top: 4px; right: 4px; width: 20px; height: 20px;
    display: none; align-items: center; justify-content: center;
    border-radius: 50%; background: rgba(0,0,0,0.6); color: #fff; font-size: 15px; line-height: 1;
    cursor: pointer;
  }
  .card:hover .del { display: flex; }
  .del:hover { background: var(--danger); }
  .band {
    position: absolute; left: 0; right: 0; bottom: 0;
    display: flex; justify-content: space-between;
    padding: 3px 6px;
    font-size: var(--text-small, 11.5px); color: #fff;
    background: linear-gradient(to top, rgba(0,0,0,0.7), rgba(0,0,0,0));
  }
  .empty { color: var(--fg-secondary); font-size: var(--text-small); padding: 0 8px; }

  .menu {
    position: fixed; z-index: 200; min-width: 168px;
    background: var(--bg-elevated); border: 1px solid var(--border-strong);
    border-radius: 8px; box-shadow: 0 12px 32px rgba(0,0,0,0.45); padding: 4px;
    display: flex; flex-direction: column;
  }
  .menu button {
    text-align: left; border: none; background: transparent; color: var(--fg-primary);
    padding: 7px 10px; border-radius: var(--radius); cursor: default; font-size: var(--text-base);
    font-family: var(--font-ui);
  }
  .menu button:hover { background: var(--bg-hover); }
  .menu button.danger:hover { background: var(--danger); color: #fff; }
  .msep { height: 1px; background: var(--border); margin: 4px 6px; }
</style>
