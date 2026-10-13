<script lang="ts">
  import { onMount, tick, type Snippet } from 'svelte';
  let { children, label, embedded = false }: { children: Snippet; label: string; embedded?: boolean } = $props();
  let root: HTMLDivElement;
  let inline: HTMLDivElement;
  let popup: HTMLDivElement;
  let more = $state<HTMLButtonElement>();
  let lastFocused: HTMLElement | null = null;
  let overflow = $state(false);
  let open = $state(false);

  function layout() {
    if (!inline || !popup || !root) return;
    const items = [...inline.querySelectorAll<HTMLElement>('.tool, .sep')];
    const copies = [...popup.querySelectorAll<HTMLElement>('.tool, .sep')];
    const focused = document.activeElement === document.body ? lastFocused : document.activeElement;
    const popupFocus = copies.indexOf(focused as HTMLElement);
    const inlineFocus = items.indexOf(focused as HTMLElement);
    const moreFocused = focused === more;
    items.forEach(el => { el.removeAttribute('data-toolbar-hidden'); el.inert = false; el.removeAttribute('aria-hidden'); });
    const widths = items.map(el => {
      const css = getComputedStyle(el);
      return el.getBoundingClientRect().width + parseFloat(css.marginLeft || '0') + parseFloat(css.marginRight || '0') + 2;
    });
    const available = root.clientWidth;
    const total = widths.reduce((a,b) => a+b,0);
    overflow = total > available;
    let used = 0, cutoff = items.length;
    if (overflow) {
      cutoff = 0;
      for (let i=0;i<items.length;i++) {
        if (used + widths[i] > Math.max(0,available-36)) break;
        used += widths[i]; cutoff = i+1;
      }
      while (cutoff > 0 && items[cutoff-1].classList.contains('sep')) cutoff--;
    }
    items.forEach((el,i) => {
      if (i >= cutoff) { el.setAttribute('data-toolbar-hidden',''); el.inert = true; el.setAttribute('aria-hidden','true'); }
    });
    copies.forEach((el,i) => {
      const hidden = i < cutoff || el.classList.contains('sep');
      el.toggleAttribute('data-toolbar-hidden',hidden);
      el.inert = hidden;
    });
    if (!overflow) open = false;
    if (popupFocus >= 0 && popupFocus < cutoff) {
      open = false; void tick().then(() => items[popupFocus]?.focus());
    } else if (inlineFocus >= cutoff && inlineFocus >= 0) {
      void tick().then(() => more?.focus());
    } else if (moreFocused && !overflow) {
      void tick().then(() => [...items].reverse().find(el => el.tagName === 'BUTTON' && !(el as HTMLButtonElement).disabled)?.focus());
    }
  }
  async function toggle() {
    open = !open;
    if (open) {
      await tick();
      const selected = popup.querySelector<HTMLButtonElement>('button[aria-pressed="true"]:not([data-toolbar-hidden]):not(:disabled)');
      (selected ?? popup.querySelector<HTMLButtonElement>('button:not([data-toolbar-hidden]):not(:disabled)'))?.focus();
    }
  }
  function close(returnFocus = false) { open = false; if (returnFocus) more?.focus(); }
  function popupKey(e: KeyboardEvent) {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); close(true); return; }
    if (e.key === 'Tab') { close(); return; }
    if (!['ArrowDown','ArrowUp','ArrowLeft','ArrowRight','Home','End'].includes(e.key)) return;
    e.preventDefault(); e.stopPropagation();
    const buttons = [...popup.querySelectorAll<HTMLButtonElement>('button:not([data-toolbar-hidden]):not(:disabled)')];
    if (!buttons.length) return;
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const next = e.key === 'Home' ? 0 : e.key === 'End' ? buttons.length-1 : (index + (e.key === 'ArrowUp' || e.key === 'ArrowLeft' ? -1 : 1) + buttons.length) % buttons.length;
    buttons[next]?.focus();
  }
  function toolbarKey(e: KeyboardEvent) {
    if (popup.contains(e.target as Node)) return;
    if (e.key === 'ArrowDown' && e.target === more) { e.preventDefault(); e.stopPropagation(); if (!open) void toggle(); return; }
    if (!['ArrowLeft','ArrowRight','Home','End'].includes(e.key)) return;
    const buttons = [...inline.querySelectorAll<HTMLButtonElement>('button:not([data-toolbar-hidden]):not(:disabled)')];
    if (more) buttons.push(more);
    const index = buttons.indexOf(e.target as HTMLButtonElement);
    if (index < 0 || !buttons.length) return;
    e.preventDefault(); e.stopPropagation();
    const next = e.key === 'Home' ? 0 : e.key === 'End' ? buttons.length-1 : (index+(e.key === 'ArrowLeft' ? -1 : 1)+buttons.length)%buttons.length;
    buttons[next]?.focus();
  }
  onMount(() => {
    const resize = new ResizeObserver(layout); resize.observe(root);
    // Actions can appear/disappear or change their label as editing state changes.
    const mutation = new MutationObserver(() => queueMicrotask(layout));
    mutation.observe(inline,{childList:true,subtree:true,characterData:true});
    const outside = (e: PointerEvent) => { if (!root.contains(e.target as Node)) { lastFocused = null; close(); } };
    const focus = (e: FocusEvent) => { lastFocused = root.contains(e.target as Node) ? e.target as HTMLElement : null; };
    document.addEventListener('pointerdown',outside);
    document.addEventListener('focusin',focus);
    layout();
    return () => { resize.disconnect(); mutation.disconnect(); document.removeEventListener('pointerdown',outside); document.removeEventListener('focusin',focus); };
  });
</script>

<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
<div class="overflow-toolbar" class:embedded role="toolbar" tabindex="-1" aria-label={label} bind:this={root} onkeydown={toolbarKey}>
  <div class="inline" bind:this={inline}>{@render children()}</div>
  {#if overflow}
    <button class="more" aria-label="More Tools" aria-expanded={open} title="More Tools" onpointerdown={(e) => e.preventDefault()} onclick={toggle} bind:this={more}>
      <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M5 3l5 5-5 5" /></svg>
    </button>
  {/if}
  <!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
  <div class="popup" role="group" aria-label="More Tools" hidden={!open} bind:this={popup} onkeydown={popupKey} onclick={(e) => { if ((e.target as HTMLElement).closest('button')) close(true); }}>
    {@render children()}
  </div>
</div>

<style>
  .overflow-toolbar { position:relative; display:flex; align-items:center; gap:2px; min-width:0; width:100%; flex:0 0 60px; height:60px; }
  .embedded { flex:1; width:auto; }
  .inline { display:flex; align-items:center; gap:2px; min-width:0; overflow:hidden; }
  .more { flex-shrink:0; width:32px; height:50px; border:0; border-radius:var(--radius); background:transparent; color:var(--fg-secondary); cursor:pointer; }
  .more:hover { background:var(--bg-hover); color:var(--fg-primary); }
  .more svg { width:18px; height:18px; fill:none; stroke:currentColor; stroke-width:1.5; }
  .popup { position:absolute; top:58px; right:0; z-index:100; padding:6px; min-width:150px; max-height:min(70vh,480px); overflow-y:auto; border:1px solid var(--border-strong); border-radius:var(--radius); background:var(--bg-content); box-shadow:0 8px 24px #0006; display:flex; flex-direction:column; gap:2px; }
  .popup[hidden] { display:none; }
  :global([data-toolbar-hidden]) { display:none !important; }
  .popup :global(.tools) { display:contents; }
  .popup :global(.tool) { width:100%; height:34px; min-height:34px; flex-direction:row; justify-content:flex-start; gap:10px; border-bottom:0; text-align:left; }
  .popup :global(.tool span) { font-size:12px; }
</style>
