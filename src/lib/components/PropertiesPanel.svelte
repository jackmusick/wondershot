<script lang="ts">
  // Right-hand Properties panel (Qt parity): color / stroke / text size / align /
  // effects. Binds the same editor stores the canvas reads, so it stays in sync
  // with the toolbar's tool selection.
  import { activeTool } from '$lib/editor/tools';
  import { drawStyle, textStyle, normalizeColor, type TextAlign } from '$lib/editor/style';
  import { effects } from '$lib/editor/effects';

  let colorEl: HTMLInputElement;
  let colorRgb = $derived($drawStyle.color.slice(0, 7));
  function onColorInput(e: Event) {
    drawStyle.update((s) => ({ ...s, color: normalizeColor((e.target as HTMLInputElement).value) }));
  }
  function onWidth(e: Event) {
    drawStyle.update((s) => ({ ...s, width: Number((e.target as HTMLInputElement).value) }));
  }
  function onFontSize(e: Event) {
    textStyle.update((s) => ({ ...s, point_size: Number((e.target as HTMLInputElement).value) }));
  }
  function setAlign(a: TextAlign) {
    textStyle.update((s) => ({ ...s, align: a }));
  }
  function onRadius(e: Event) {
    effects.update((s) => ({ ...s, corner_radius: Number((e.target as HTMLInputElement).value) }));
  }
  function onFadeHeight(e: Event) {
    effects.update((s) => ({ ...s, fade_height: Number((e.target as HTMLInputElement).value) }));
  }
</script>

<aside class="properties">
  <div class="row">
    <span class="label">Color</span>
    <button class="swatch" style="--swatch:{colorRgb}" aria-label="Stroke color" onclick={() => colorEl.click()}></button>
    <input bind:this={colorEl} type="color" class="color-input" value={colorRgb} oninput={onColorInput} tabindex="-1" aria-hidden="true" />
  </div>

  <div class="row">
    <span class="label">Stroke</span>
    <input class="num" type="number" min="1" max="64" value={$drawStyle.width} oninput={onWidth} aria-label="Stroke width" />
  </div>

  <div class="row">
    <span class="label">Text size</span>
    <input class="num" type="number" min="6" max="96" value={$textStyle.point_size} oninput={onFontSize}
      disabled={$activeTool !== 'text'} aria-label="Text size" />
  </div>

  <div class="row">
    <span class="label">Align</span>
    <div class="align" class:disabled={$activeTool !== 'text'}>
      <button class:active={$textStyle.align === 'left'} aria-label="Align left" onclick={() => setAlign('left')} disabled={$activeTool !== 'text'}>
        <svg viewBox="0 0 16 16"><path d="M2 4h12M2 8h8M2 12h11" /></svg>
      </button>
      <button class:active={$textStyle.align === 'center'} aria-label="Align center" onclick={() => setAlign('center')} disabled={$activeTool !== 'text'}>
        <svg viewBox="0 0 16 16"><path d="M2 4h12M4 8h8M3 12h10" /></svg>
      </button>
      <button class:active={$textStyle.align === 'right'} aria-label="Align right" onclick={() => setAlign('right')} disabled={$activeTool !== 'text'}>
        <svg viewBox="0 0 16 16"><path d="M2 4h12M6 8h8M3 12h11" /></svg>
      </button>
    </div>
  </div>

  <div class="section">Effects</div>

  <label class="check">
    <input type="checkbox" checked={$effects.rounded} onchange={(e) => effects.update((s) => ({ ...s, rounded: (e.target as HTMLInputElement).checked }))} />
    Rounded corners
  </label>
  <div class="row indent">
    <span class="label">Radius</span>
    <input class="num" type="number" min="2" max="64" value={$effects.corner_radius} oninput={onRadius} disabled={!$effects.rounded} aria-label="Corner radius" />
  </div>

  <label class="check">
    <input type="checkbox" checked={$effects.fade} onchange={(e) => effects.update((s) => ({ ...s, fade: (e.target as HTMLInputElement).checked }))} />
    Bottom fade
  </label>
  <div class="row indent">
    <span class="label">Fade height</span>
    <input class="num" type="number" min="8" max="512" value={$effects.fade_height} oninput={onFadeHeight} disabled={!$effects.fade} aria-label="Fade height" />
  </div>

  <p class="note">Applies to the selection and to new objects</p>
</aside>

<style>
  .properties {
    width: 220px;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    gap: 8px;
    padding: 14px 14px;
    background: var(--bg-content);
    border-left: 1px solid var(--border);
    overflow-y: auto;
  }
  .row { display: flex; align-items: center; gap: 10px; }
  .row.indent { padding-left: 4px; }
  .label { flex: 1; font-size: var(--text-base); color: var(--fg-secondary); }
  .section { font-weight: 700; color: var(--fg-primary); margin-top: 6px; font-size: var(--text-base); }
  .num {
    width: 64px; height: 26px; background: var(--bg-field); color: var(--fg-primary);
    border: 1px solid var(--border); border-radius: var(--radius); font-size: var(--text-small); padding: 0 6px;
  }
  .num:disabled { opacity: 0.4; }
  .swatch {
    width: 64px; height: 24px; border: 1px solid var(--border-strong);
    border-radius: var(--radius); background: var(--swatch); cursor: pointer; padding: 0;
  }
  .color-input { position: absolute; width: 0; height: 0; opacity: 0; pointer-events: none; }
  .align { display: inline-flex; gap: 2px; }
  .align.disabled { opacity: 0.4; }
  .align button {
    width: 28px; height: 26px; display: inline-flex; align-items: center; justify-content: center;
    border: 1px solid var(--border); background: var(--bg-field); color: var(--fg-secondary);
    border-radius: var(--radius); cursor: pointer; padding: 0;
  }
  .align button.active { background: var(--bg-selected); color: var(--fg-primary); border-color: var(--accent); }
  .align button svg { width: 14px; height: 14px; fill: none; stroke: currentColor; stroke-width: 1.5; stroke-linecap: round; }
  .check { display: flex; align-items: center; gap: 6px; font-size: var(--text-base); color: var(--fg-primary); cursor: pointer; }
  .check input { accent-color: var(--accent); }
  .note { margin: 8px 0 0; font-size: var(--text-small); color: var(--fg-secondary); }
</style>
