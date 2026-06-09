<script lang="ts">
  import { activeTool, SHORTCUTS, type ToolId } from './tools';
  import { bgApi } from './zoom';

  // Tool metadata: id, human label, and an inline-SVG path/glyph. Icons are
  // simple monochrome strokes drawn in a 16x16 box; where an icon would be
  // fussy we fall back to a short glyph. Shortcut is derived from SHORTCUTS so
  // the tooltip stays in sync with the keyboard map.
  type ToolDef = { id: ToolId; label: string };
  // Logical groups with separators between them.
  const GROUPS: ToolDef[][] = [
    [{ id: 'select', label: 'Select' }],
    [
      { id: 'arrow', label: 'Arrow' },
      { id: 'line', label: 'Line' },
      { id: 'rect', label: 'Box' },
      { id: 'ellipse', label: 'Ellipse' },
      { id: 'freehand', label: 'Pen' },
      { id: 'highlight', label: 'Highlight' },
    ],
    [
      { id: 'text', label: 'Text' },
      { id: 'step', label: 'Step' },
    ],
    [
      { id: 'pixelate', label: 'Pixelate' },
      { id: 'blur', label: 'Blur' },
    ],
    [
      { id: 'crop', label: 'Crop' },
      { id: 'cutout-v', label: 'Cut |' },
      { id: 'cutout-h', label: 'Cut —' },
    ],
  ];

  // AI actions (not editor tools): a sparkle group at the end of the rail.
  function aiNotReady(name: string) {
    // The AI client (ai_endpoint/ai_api_key from settings) isn't wired into the
    // Tauri backend yet; surface that rather than silently no-op.
    console.warn(`${name} is not implemented yet`);
    alert(`${name} is coming soon — the AI backend isn't wired up yet.`);
  }

  // Reverse-lookup the shortcut letter for a tool, for the tooltip.
  function shortcutFor(id: ToolId): string {
    const entry = Object.entries(SHORTCUTS).find(([, t]) => t === id);
    if (!entry) return '';
    return entry[0] === 'U' ? '⇧U' : entry[0].toUpperCase();
  }

  function tip(d: ToolDef): string {
    const s = shortcutFor(d.id);
    return s ? `${d.label} (${s})` : d.label;
  }

  function pick(id: ToolId) {
    activeTool.set(id);
  }

  // --- Remove BG: AI background removal (M5 T3) ---
  // The canvas registers a bgApi (removeBackground + model-available flag) on
  // mount. The button is disabled until a canvas is mounted AND the model is
  // installed. `bgBusy` guards against double-clicks during inference.
  let bgBusy = $state(false);
  let bgEnabled = $derived(!!$bgApi?.available && !bgBusy);
  let bgTip = $derived(
    !$bgApi
      ? 'Remove background'
      : $bgApi.available
        ? 'Remove background (AI)'
        : 'Background-removal model not installed'
  );
  async function removeBg() {
    if (!$bgApi?.available || bgBusy) return;
    bgBusy = true;
    try {
      await $bgApi.removeBackground();
    } catch (e) {
      console.error('remove background failed:', e);
    } finally {
      bgBusy = false;
    }
  }
</script>

<header class="toolbar">
  <!-- Tool buttons -->
  <div class="tools">
    {#each GROUPS as group, gi}
      {#if gi > 0}<span class="sep"></span>{/if}
      {#each group as t}
        <button
          class="tool"
          class:active={$activeTool === t.id}
          title={tip(t)}
          aria-label={t.label}
          aria-pressed={$activeTool === t.id}
          onclick={() => pick(t.id)}
        >
          {#if t.id === 'select'}
            <svg viewBox="0 0 16 16"><path d="M3 2l9 4-3.5 1.2L7 11z" /></svg>
          {:else if t.id === 'arrow'}
            <svg viewBox="0 0 16 16"><path d="M2 14L13 3M13 3H7M13 3v6" /></svg>
          {:else if t.id === 'line'}
            <svg viewBox="0 0 16 16"><path d="M2 14L14 2" /></svg>
          {:else if t.id === 'rect'}
            <svg viewBox="0 0 16 16"><rect x="2.5" y="3.5" width="11" height="9" rx="1" /></svg>
          {:else if t.id === 'ellipse'}
            <svg viewBox="0 0 16 16"><ellipse cx="8" cy="8" rx="6" ry="4.5" /></svg>
          {:else if t.id === 'freehand'}
            <svg viewBox="0 0 16 16"><path d="M2 12c2 0 2-7 4-7s2 9 4 9 2-6 4-6" /></svg>
          {:else if t.id === 'highlight'}
            <svg viewBox="0 0 16 16"><path d="M3 13h10M4 10l5-7 3 2-5 7H4z" /></svg>
          {:else if t.id === 'text'}
            <svg viewBox="0 0 16 16"><path d="M3 4h10M8 4v9M6 13h4" /></svg>
          {:else if t.id === 'step'}
            <svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="6" /><text x="8" y="11" class="glyph-num">1</text></svg>
          {:else if t.id === 'pixelate'}
            <svg viewBox="0 0 16 16" class="filled"><rect x="2" y="2" width="5" height="5" /><rect x="9" y="2" width="5" height="5" /><rect x="2" y="9" width="5" height="5" /><rect x="9" y="9" width="5" height="5" /></svg>
          {:else if t.id === 'blur'}
            <svg viewBox="0 0 16 16"><circle cx="8" cy="8" r="5.5" stroke-dasharray="2 2" /></svg>
          {:else if t.id === 'crop'}
            <svg viewBox="0 0 16 16"><path d="M4 1v11h11M1 4h11v11" /></svg>
          {:else if t.id === 'cutout-v'}
            <svg viewBox="0 0 16 16"><path d="M5 2v12M11 2v12" stroke-dasharray="2 2" /><path d="M5 8H2M14 8h-3" /></svg>
          {:else if t.id === 'cutout-h'}
            <svg viewBox="0 0 16 16"><path d="M2 5h12M2 11h12" stroke-dasharray="2 2" /><path d="M8 5V2M8 14v-3" /></svg>
          {/if}
          <span class="tlabel">{t.label}</span>
        </button>
      {/each}
    {/each}

    <!-- AI group: sparkle actions -->
    <span class="sep"></span>
    {#snippet sparkle()}
      <svg viewBox="0 0 16 16" class="ai-spark"><path d="M8 1.5l1.2 3.3L12.5 6 9.2 7.2 8 10.5 6.8 7.2 3.5 6l3.3-1.2z"/><path d="M12.8 10.2l.6 1.5 1.5.6-1.5.6-.6 1.5-.6-1.5-1.5-.6 1.5-.6z"/></svg>
    {/snippet}
    <button class="tool ai" disabled title="AI Redact — needs the AI backend (not wired yet)" onclick={() => aiNotReady('AI Redact')}>
      {@render sparkle()}<span class="tlabel">Redact</span>
    </button>
    <button class="tool ai" disabled title="AI Simplify — needs the AI backend (not wired yet)" onclick={() => aiNotReady('AI Simplify')}>
      {@render sparkle()}<span class="tlabel">Simplify</span>
    </button>
    <button class="tool ai" title={bgTip} aria-label="Remove background" onclick={removeBg} disabled={!bgEnabled}>
      {@render sparkle()}<span class="tlabel">{bgBusy ? 'Removing…' : 'Remove BG'}</span>
    </button>
  </div>

  <div class="spacer"></div>
  <span class="autosave" title="Edits save automatically">Auto-saved</span>
</header>

<style>
  .toolbar {
    height: 60px;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 0 8px;
    background: var(--bg-content);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
    overflow-x: auto;
  }
  .tools {
    display: flex;
    align-items: center;
    gap: 2px;
  }
  .spacer { flex: 1; }

  .sep {
    width: 1px;
    height: 22px;
    background: var(--border-strong);
    margin: 0 4px;
    flex-shrink: 0;
  }

  /* Tool buttons: icon on top, small label beneath (Qt rail parity). Active =
     accent bottom border + selected bg. */
  .tool {
    min-width: 46px;
    height: 50px;
    display: inline-flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 3px;
    border: none;
    background: transparent;
    color: var(--fg-secondary);
    border-radius: var(--radius);
    cursor: pointer;
    padding: 0 6px;
    border-bottom: 2px solid transparent;
    flex-shrink: 0;
  }
  .tool:hover:not(:disabled) { background: var(--bg-hover); color: var(--fg-primary); }
  .tool:disabled { opacity: 0.4; cursor: not-allowed; }
  .tool.active {
    background: var(--bg-selected);
    color: var(--fg-primary);
    border-bottom-color: var(--accent);
    border-bottom-left-radius: 0;
    border-bottom-right-radius: 0;
  }
  .tlabel { font-size: 10px; line-height: 1; color: inherit; }
  .tool.ai .ai-spark { color: var(--accent-strong); fill: var(--accent-strong); stroke: none; }
  .tool svg {
    width: 18px;
    height: 18px;
    fill: none;
    stroke: currentColor;
    stroke-width: 1.5;
    stroke-linecap: round;
    stroke-linejoin: round;
  }
  /* Solid-fill icons (pixelate blocks). */
  .tool svg.filled { fill: currentColor; stroke: none; }
  .glyph-num {
    fill: currentColor;
    stroke: none;
    font-size: 8px;
    text-anchor: middle;
    font-family: var(--font-ui);
    font-weight: 700;
  }


  .autosave {
    font-size: var(--text-small);
    color: var(--fg-secondary);
    flex-shrink: 0;
    padding: 0 6px;
  }

</style>
