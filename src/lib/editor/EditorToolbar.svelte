<script lang="ts">
  import { activeTool, SHORTCUTS, type ToolId } from './tools';
  import { drawStyle, textStyle, normalizeColor, type TextAlign } from './style';
  import { effects } from './effects';
  import { zoomApi, saveApi } from './zoom';

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
      { id: 'rect', label: 'Rectangle' },
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
      { id: 'cutout-v', label: 'Cut out vertical' },
      { id: 'cutout-h', label: 'Cut out horizontal' },
    ],
  ];

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

  // --- Color swatch: open a hidden native color input on click ---
  let colorEl: HTMLInputElement;
  // The native input only accepts/returns #rrggbb; store keeps #rrggbbaa.
  let colorRgb = $derived($drawStyle.color.slice(0, 7));
  function onColorInput(e: Event) {
    const v = (e.target as HTMLInputElement).value;
    drawStyle.update((s) => ({ ...s, color: normalizeColor(v) }));
  }

  function onWidth(e: Event) {
    const v = Number((e.target as HTMLInputElement).value);
    drawStyle.update((s) => ({ ...s, width: v }));
  }

  function onFontSize(e: Event) {
    const v = Number((e.target as HTMLInputElement).value);
    textStyle.update((s) => ({ ...s, point_size: v }));
  }
  function setAlign(a: TextAlign) {
    textStyle.update((s) => ({ ...s, align: a }));
  }

  function onRadius(e: Event) {
    const v = Number((e.target as HTMLInputElement).value);
    effects.update((s) => ({ ...s, corner_radius: v }));
  }
  function onFadeHeight(e: Event) {
    const v = Number((e.target as HTMLInputElement).value);
    effects.update((s) => ({ ...s, fade_height: v }));
  }

  function zoom(fn: 'zoomIn' | 'zoomOut' | 'zoomActual' | 'zoomFit') {
    $zoomApi?.[fn]();
  }

  function save() {
    void $saveApi?.();
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
        </button>
      {/each}
    {/each}
  </div>

  <span class="sep"></span>

  <!-- Style controls -->
  <div class="style">
    <button
      class="swatch"
      title="Stroke color"
      aria-label="Stroke color"
      style="--swatch:{colorRgb}"
      onclick={() => colorEl.click()}
    ></button>
    <input
      bind:this={colorEl}
      type="color"
      class="color-input"
      value={colorRgb}
      oninput={onColorInput}
      tabindex="-1"
      aria-hidden="true"
    />
    <label class="field" title="Stroke width">
      <span class="ico-stroke"></span>
      <input type="range" min="1" max="32" value={$drawStyle.width} oninput={onWidth} />
      <span class="num">{$drawStyle.width}</span>
    </label>

    {#if $activeTool === 'text'}
      <span class="sep"></span>
      <label class="field" title="Font size">
        <span class="lbl">A</span>
        <input type="number" min="6" max="96" value={$textStyle.point_size} oninput={onFontSize} />
      </label>
      <div class="align">
        <button class:active={$textStyle.align === 'left'} title="Align left" aria-label="Align left" onclick={() => setAlign('left')}>
          <svg viewBox="0 0 16 16"><path d="M2 4h12M2 8h8M2 12h11" /></svg>
        </button>
        <button class:active={$textStyle.align === 'center'} title="Align center" aria-label="Align center" onclick={() => setAlign('center')}>
          <svg viewBox="0 0 16 16"><path d="M2 4h12M4 8h8M3 12h10" /></svg>
        </button>
        <button class:active={$textStyle.align === 'right'} title="Align right" aria-label="Align right" onclick={() => setAlign('right')}>
          <svg viewBox="0 0 16 16"><path d="M2 4h12M6 8h8M3 12h11" /></svg>
        </button>
      </div>
    {/if}
  </div>

  <div class="spacer"></div>

  <!-- Effects -->
  <div class="effects">
    <label class="toggle" title="Round the image corners on save">
      <input type="checkbox" checked={$effects.rounded} onchange={(e) => effects.update((s) => ({ ...s, rounded: (e.target as HTMLInputElement).checked }))} />
      Rounded
    </label>
    <input class="effect-num" type="number" min="2" max="64" value={$effects.corner_radius} oninput={onRadius} disabled={!$effects.rounded} aria-label="Corner radius" />
    <label class="toggle" title="Fade the image bottom on save">
      <input type="checkbox" checked={$effects.fade} onchange={(e) => effects.update((s) => ({ ...s, fade: (e.target as HTMLInputElement).checked }))} />
      Fade
    </label>
    <input class="effect-num" type="number" min="8" max="512" value={$effects.fade_height} oninput={onFadeHeight} disabled={!$effects.fade} aria-label="Fade height" />
  </div>

  <span class="sep"></span>

  <!-- Zoom controls -->
  <div class="zoom">
    <button class="zbtn" title="Zoom out" aria-label="Zoom out" onclick={() => zoom('zoomOut')}>−</button>
    <button class="ztext" title="Fit to view" onclick={() => zoom('zoomFit')}>Fit</button>
    <button class="ztext" title="Actual size (100%)" onclick={() => zoom('zoomActual')}>100%</button>
    <button class="zbtn" title="Zoom in" aria-label="Zoom in" onclick={() => zoom('zoomIn')}>+</button>
  </div>

  <span class="sep"></span>

  <button class="save" title="Save (Ctrl+S)" aria-label="Save" onclick={save}>Save</button>
</header>

<style>
  .toolbar {
    height: 44px;
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 0 8px;
    background: var(--bg-content);
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
    overflow-x: auto;
  }
  .tools,
  .style,
  .effects,
  .zoom,
  .align {
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

  /* Icon buttons (tools + align). 28px square, accent BOTTOM border when active
     (horizontal-toolbar variant of wonderblob's inset accent bar). */
  .tool,
  .align button {
    width: 28px;
    height: 28px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: none;
    background: transparent;
    color: var(--fg-secondary);
    border-radius: var(--radius);
    cursor: pointer;
    padding: 0;
    border-bottom: 2px solid transparent;
    flex-shrink: 0;
  }
  .tool:hover,
  .align button:hover { background: var(--bg-hover); color: var(--fg-primary); }
  .tool.active,
  .align button.active {
    background: var(--bg-selected);
    color: var(--fg-primary);
    border-bottom-color: var(--accent);
    border-bottom-left-radius: 0;
    border-bottom-right-radius: 0;
  }
  .tool svg,
  .align button svg {
    width: 16px;
    height: 16px;
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

  /* Color swatch */
  .swatch {
    width: 26px;
    height: 22px;
    border: 1px solid var(--border-strong);
    border-radius: var(--radius);
    background: var(--swatch);
    cursor: pointer;
    padding: 0;
    flex-shrink: 0;
  }
  .color-input {
    position: absolute;
    width: 0;
    height: 0;
    opacity: 0;
    pointer-events: none;
  }

  .field {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    height: 28px;
    padding: 0 6px;
    color: var(--fg-secondary);
    font-size: var(--text-small);
  }
  .field input[type='range'] { width: 72px; accent-color: var(--accent); }
  .field input[type='number'] {
    width: 44px;
    height: 22px;
    background: var(--bg-field);
    color: var(--fg-primary);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    font-size: var(--text-small);
    padding: 0 4px;
  }
  .field .num {
    min-width: 16px;
    text-align: right;
    font-variant-numeric: tabular-nums;
    color: var(--fg-primary);
  }
  .field .lbl { font-weight: 700; color: var(--fg-primary); }
  .ico-stroke {
    width: 16px;
    height: 0;
    border-top: 3px solid var(--fg-secondary);
    border-radius: 2px;
  }

  .toggle {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: var(--text-small);
    color: var(--fg-primary);
    cursor: pointer;
    white-space: nowrap;
  }
  .toggle input { accent-color: var(--accent); }
  .effect-num {
    width: 48px;
    height: 22px;
    background: var(--bg-field);
    color: var(--fg-primary);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    font-size: var(--text-small);
    padding: 0 4px;
  }
  .effect-num:disabled { opacity: 0.4; }

  /* Zoom */
  .zbtn,
  .ztext {
    height: 24px;
    border: 1px solid var(--border);
    background: var(--bg-field);
    color: var(--fg-primary);
    border-radius: var(--radius);
    cursor: pointer;
    font-size: var(--text-small);
    flex-shrink: 0;
  }
  .zbtn { width: 26px; font-size: 15px; line-height: 1; }
  .ztext { padding: 0 8px; }
  .zbtn:hover,
  .ztext:hover { background: var(--bg-hover); }

  .save {
    height: 26px;
    padding: 0 12px;
    border: 1px solid var(--accent);
    background: var(--accent);
    color: #fff;
    border-radius: var(--radius);
    cursor: pointer;
    font-size: var(--text-small);
    font-weight: 600;
    flex-shrink: 0;
  }
  .save:hover { filter: brightness(1.08); }
</style>
