<script lang="ts">
  import { onMount, onDestroy } from 'svelte';
  import { page } from '$app/state';
  import { tickDown } from '$lib/recorder/countdown';

  const USE_MOCK = typeof (globalThis as any).__TAURI_INTERNALS__ === 'undefined';

  let remaining = $state(parseSecs(page.url.searchParams.get('secs')));
  let settled = false;
  let timer: ReturnType<typeof setInterval> | undefined;

  function parseSecs(raw: string | null): number {
    const n = parseInt(raw ?? '', 10);
    return Number.isFinite(n) ? Math.max(1, n) : 3;
  }

  /** Emit a Tauri event (start/cancel). In mock/browser mode, just log. */
  async function signal(kind: 'done' | 'cancel') {
    if (settled) return;
    settled = true;
    if (timer) clearInterval(timer);
    if (USE_MOCK) {
      console.log(`[countdown] ${kind} (mock)`);
      return;
    }
    const { emit } = await import('@tauri-apps/api/event');
    await emit(`countdown://${kind}`);
    const { getCurrentWindow } = await import('@tauri-apps/api/window');
    await getCurrentWindow().close();
  }

  function start() {
    signal('done');
  }

  function cancel() {
    signal('cancel');
  }

  function tick() {
    const r = tickDown(remaining);
    remaining = r.remaining;
    if (r.done) start();
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') cancel();
  }

  onMount(() => {
    timer = setInterval(tick, 1000);
    window.addEventListener('keydown', onKey);
  });

  onDestroy(() => {
    if (timer) clearInterval(timer);
    if (typeof window !== 'undefined') window.removeEventListener('keydown', onKey);
  });
</script>

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div class="overlay" onclick={cancel}>
  <div class="count">{remaining}</div>
  <div class="hint">Esc to cancel</div>
</div>

<style>
  :global(html, body) {
    background: transparent;
  }
  .overlay {
    position: fixed;
    inset: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 12px;
    background: transparent;
    user-select: none;
    cursor: default;
  }
  .count {
    font-size: 64px;
    font-weight: 700;
    line-height: 1;
    color: var(--fg-primary, #ffffff);
    text-shadow: 0 2px 8px rgba(0, 0, 0, 0.5);
  }
  .hint {
    font-size: var(--text-small, 11.5px);
    color: var(--fg-secondary, rgba(255, 255, 255, 0.7));
    text-shadow: 0 1px 4px rgba(0, 0, 0, 0.5);
  }
</style>
