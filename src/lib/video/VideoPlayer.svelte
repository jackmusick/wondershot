<script lang="ts">
  import { mediaSrc, ipcInvoke } from '$lib/ipc';
  import { loadLibrary, captures, activeItem } from '$lib/stores';
  import { get } from 'svelte/store';

  // A blur region in VIDEO pixel coords, active for [start,end] seconds.
  // Field names match wondershot-core::video::Redaction (serde).
  type Redaction = { x: number; y: number; w: number; h: number; start: number; end: number };

  let { path }: { path: string } = $props();

  // --- media element + playback state ---------------------------------------
  let videoEl = $state<HTMLVideoElement | null>(null);
  let src = $state('');
  let playing = $state(false);
  let current = $state(0);
  let duration = $state(0);

  // Resolve the playable src for the path (re-resolves if path changes).
  $effect(() => {
    let cancelled = false;
    mediaSrc(path).then((s) => {
      if (!cancelled) src = s;
    });
    return () => {
      cancelled = true;
    };
  });

  function fmt(t: number): string {
    if (!isFinite(t) || t < 0) t = 0;
    const m = Math.floor(t / 60);
    const s = Math.floor(t % 60);
    return `${m}:${String(s).padStart(2, '0')}`;
  }

  function togglePlay() {
    const v = videoEl;
    if (!v) return;
    if (v.paused) void v.play();
    else v.pause();
  }
  function onSeek(e: Event) {
    const v = videoEl;
    const t = Number((e.target as HTMLInputElement).value);
    if (v) v.currentTime = t;
    current = t;
  }

  // --- redaction overlay: draw boxes while paused ---------------------------
  let overlayEl = $state<HTMLElement | null>(null);
  let redactions = $state<Redaction[]>([]);
  let blur = $state(14);

  // In-progress drag, in DISPLAY (overlay client) coords.
  let drag = $state<{ x0: number; y0: number; x1: number; y1: number } | null>(null);

  // Map a display-space rect to VIDEO pixel coords using the intrinsic
  // videoWidth/videoHeight vs the overlay's client rect. The <video> uses
  // object-fit: contain, so we account for the letterbox/pillarbox margins.
  function displayContentBox(): { left: number; top: number; w: number; h: number; sx: number; sy: number } | null {
    const v = videoEl;
    const ov = overlayEl;
    if (!v || !ov) return null;
    const vw = v.videoWidth || 0;
    const vh = v.videoHeight || 0;
    const r = ov.getBoundingClientRect();
    if (vw === 0 || vh === 0 || r.width === 0 || r.height === 0) {
      // No intrinsic size yet (mock/headless): fall back to 1:1 with the box.
      return { left: 0, top: 0, w: r.width, h: r.height, sx: 1, sy: 1 };
    }
    // contain scale: the smaller ratio fills.
    const scale = Math.min(r.width / vw, r.height / vh);
    const dispW = vw * scale;
    const dispH = vh * scale;
    const left = (r.width - dispW) / 2;
    const top = (r.height - dispH) / 2;
    return { left, top, w: dispW, h: dispH, sx: vw / dispW, sy: vh / dispH };
  }

  // Convert a Redaction (video coords) → CSS box (display coords) for preview.
  function boxStyle(r: Redaction): string {
    const c = displayContentBox();
    if (!c) return 'display:none';
    const left = c.left + r.x / c.sx;
    const top = c.top + r.y / c.sy;
    const w = r.w / c.sx;
    const h = r.h / c.sy;
    return `left:${left}px;top:${top}px;width:${w}px;height:${h}px`;
  }

  function localPoint(e: PointerEvent): { x: number; y: number } {
    const r = overlayEl!.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }

  function onPointerDown(e: PointerEvent) {
    if (playing) return; // only draw while paused
    if (e.button !== 0) return;
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    const p = localPoint(e);
    drag = { x0: p.x, y0: p.y, x1: p.x, y1: p.y };
  }
  function onPointerMove(e: PointerEvent) {
    if (!drag) return;
    const p = localPoint(e);
    drag = { ...drag, x1: p.x, y1: p.y };
  }
  function onPointerUp() {
    if (!drag) return;
    const c = displayContentBox();
    const dx = Math.min(drag.x0, drag.x1);
    const dy = Math.min(drag.y0, drag.y1);
    const dw = Math.abs(drag.x1 - drag.x0);
    const dh = Math.abs(drag.y1 - drag.y0);
    drag = null;
    if (!c || dw < 6 || dh < 6) return; // ignore tiny accidental boxes
    // display → video coords; clamp to content area then scale.
    const vx = Math.max(0, (dx - c.left)) * c.sx;
    const vy = Math.max(0, (dy - c.top)) * c.sy;
    const vw = dw * c.sx;
    const vh = dh * c.sy;
    const start = current;
    const end = Math.min(duration || start + 2, start + 2);
    redactions = [
      ...redactions,
      { x: Math.round(vx), y: Math.round(vy), w: Math.round(vw), h: Math.round(vh), start, end }
    ];
  }

  // In-progress drag rect in display coords for the live preview.
  let dragStyle = $derived.by(() => {
    if (!drag) return 'display:none';
    const left = Math.min(drag.x0, drag.x1);
    const top = Math.min(drag.y0, drag.y1);
    const w = Math.abs(drag.x1 - drag.x0);
    const h = Math.abs(drag.y1 - drag.y0);
    return `left:${left}px;top:${top}px;width:${w}px;height:${h}px`;
  });

  // --- redaction list edits -------------------------------------------------
  function setField(i: number, field: 'start' | 'end', value: number) {
    redactions = redactions.map((r, j) => (j === i ? { ...r, [field]: value } : r));
  }
  function fromPlayhead(i: number, field: 'start' | 'end') {
    setField(i, field, Number(current.toFixed(3)));
  }
  function removeRedaction(i: number) {
    redactions = redactions.filter((_, j) => j !== i);
  }

  // --- apply / export status ------------------------------------------------
  let busy = $state(false);
  let toast = $state('');
  let errored = $state(false);
  function flash(msg: string, isErr = false) {
    toast = msg;
    errored = isErr;
    setTimeout(() => {
      if (toast === msg) toast = '';
    }, 3200);
  }

  // Reload the library and select the capture whose path matches `p`.
  async function selectByPath(p: string) {
    await loadLibrary();
    const list = get(captures);
    const found = list.find((c) => c.path === p);
    if (found) activeItem.set(found);
  }

  async function applyBlur() {
    if (!redactions.length || busy) return;
    busy = true;
    try {
      const out = await ipcInvoke<string>('apply_blur', { path, redactions, blur });
      redactions = [];
      await selectByPath(out);
      flash('Blur applied');
    } catch (e) {
      flash(`Blur failed: ${e}`, true);
    } finally {
      busy = false;
    }
  }

  // --- GIF dialog -----------------------------------------------------------
  let gifOpen = $state(false);
  let gifFps = $state(12);
  let gifWidth = $state(720);
  let gifUseRange = $state(false);
  let gifStart = $state(0);
  let gifEnd = $state(0);

  function openGif() {
    gifStart = Number(current.toFixed(3));
    gifEnd = Number(Math.min(duration || current + 3, current + 3).toFixed(3));
    gifOpen = true;
  }
  async function exportGif() {
    if (busy) return;
    busy = true;
    try {
      const start = gifUseRange ? gifStart : null;
      const end = gifUseRange ? gifEnd : null;
      const out = await ipcInvoke<string>('export_gif', {
        path,
        fps: gifFps,
        maxWidth: gifWidth,
        start,
        end
      });
      gifOpen = false;
      await loadLibrary();
      flash(`GIF exported: ${out.split('/').pop()}`);
    } catch (e) {
      flash(`GIF export failed: ${e}`, true);
    } finally {
      busy = false;
    }
  }
</script>

<div class="player">
  <div class="stage">
    <!-- svelte-ignore a11y_media_has_caption -->
    <video
      bind:this={videoEl}
      {src}
      onplay={() => (playing = true)}
      onpause={() => (playing = false)}
      ontimeupdate={() => (current = videoEl?.currentTime ?? 0)}
      onloadedmetadata={() => (duration = videoEl?.duration ?? 0)}
      onerror={() => console.error('video error', videoEl?.error?.code, videoEl?.error?.message)}
      onclick={togglePlay}
    ></video>

    <!-- Redaction overlay: draws boxes when paused. -->
    <div
      class="overlay"
      class:drawing={!playing}
      bind:this={overlayEl}
      role="presentation"
      onpointerdown={onPointerDown}
      onpointermove={onPointerMove}
      onpointerup={onPointerUp}
    >
      {#each redactions as r, i (i)}
        <div class="redbox" style={boxStyle(r)} title={`${r.start.toFixed(1)}s–${r.end.toFixed(1)}s`}></div>
      {/each}
      {#if drag}
        <div class="redbox active" style={dragStyle}></div>
      {/if}
    </div>

    {#if !playing}
      <div class="hint">Drag on the video to add a blur region</div>
    {/if}
  </div>

  <!-- Transport controls -->
  <div class="controls">
    <button class="iconbtn" onclick={togglePlay} aria-label={playing ? 'Pause' : 'Play'} title={playing ? 'Pause' : 'Play'}>
      {#if playing}
        <svg viewBox="0 0 16 16"><rect x="3.5" y="2.5" width="3" height="11" /><rect x="9.5" y="2.5" width="3" height="11" /></svg>
      {:else}
        <svg viewBox="0 0 16 16"><path d="M4 2.5l9 5.5-9 5.5z" /></svg>
      {/if}
    </button>
    <input
      class="timeline"
      type="range"
      min="0"
      max={duration || 0}
      step="0.01"
      value={current}
      oninput={onSeek}
      aria-label="Seek"
    />
    <span class="time">{fmt(current)} / {fmt(duration)}</span>
  </div>

  <!-- Redaction panel -->
  <div class="panel">
    <div class="panel-head">
      <span class="title">Blur regions</span>
      <label class="field" title="Blur strength">
        <span class="lbl">Strength</span>
        <input type="range" min="1" max="60" bind:value={blur} />
        <span class="num">{blur}</span>
      </label>
      <div class="spacer"></div>
      <button class="ghost" onclick={openGif} disabled={busy}>Export GIF…</button>
      <button class="primary" onclick={applyBlur} disabled={busy || redactions.length === 0}>
        {busy ? 'Working…' : 'Apply blur'}
      </button>
    </div>

    {#if redactions.length === 0}
      <div class="empty">Pause the video and drag a box to redact a region.</div>
    {:else}
      <ul class="redlist">
        {#each redactions as r, i (i)}
          <li class="redrow">
            <span class="idx">{i + 1}</span>
            <label class="t">
              start
              <input type="number" min="0" step="0.1" value={r.start} oninput={(e) => setField(i, 'start', Number((e.target as HTMLInputElement).value))} />
            </label>
            <button class="set" title="Set start from playhead" onclick={() => fromPlayhead(i, 'start')}>⌖</button>
            <label class="t">
              end
              <input type="number" min="0" step="0.1" value={r.end} oninput={(e) => setField(i, 'end', Number((e.target as HTMLInputElement).value))} />
            </label>
            <button class="set" title="Set end from playhead" onclick={() => fromPlayhead(i, 'end')}>⌖</button>
            <div class="spacer"></div>
            <button class="del" title="Delete region" aria-label="Delete region" onclick={() => removeRedaction(i)}>✕</button>
          </li>
        {/each}
      </ul>
    {/if}
  </div>

  {#if gifOpen}
    <div class="gif-dialog">
      <div class="gif-head">
        <span class="title">Export GIF</span>
        <button class="del" aria-label="Close" onclick={() => (gifOpen = false)}>✕</button>
      </div>
      <label class="grow">
        FPS
        <input type="range" min="4" max="30" bind:value={gifFps} />
        <span class="num">{gifFps}</span>
      </label>
      <label class="grow">
        Width
        <input type="range" min="160" max="1920" step="10" bind:value={gifWidth} />
        <span class="num">{gifWidth}</span>
      </label>
      <label class="toggle">
        <input type="checkbox" bind:checked={gifUseRange} />
        Limit to range
      </label>
      {#if gifUseRange}
        <div class="range-row">
          <label class="t">start <input type="number" min="0" step="0.1" bind:value={gifStart} /></label>
          <label class="t">end <input type="number" min="0" step="0.1" bind:value={gifEnd} /></label>
        </div>
      {/if}
      <div class="gif-actions">
        <button class="ghost" onclick={() => (gifOpen = false)}>Cancel</button>
        <button class="primary" onclick={exportGif} disabled={busy}>{busy ? 'Working…' : 'Export GIF'}</button>
      </div>
    </div>
  {/if}

  {#if toast}
    <div class="toast" class:err={errored}>{toast}</div>
  {/if}
</div>

<style>
  .player {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 0;
    background: var(--bg-content);
    position: relative;
  }
  .stage {
    position: relative;
    flex: 1;
    min-height: 0;
    background: #000;
    display: flex;
    align-items: center;
    justify-content: center;
    overflow: hidden;
  }
  video {
    max-width: 100%;
    max-height: 100%;
    width: 100%;
    height: 100%;
    object-fit: contain;
    display: block;
  }
  .overlay {
    position: absolute;
    inset: 0;
  }
  .overlay.drawing {
    cursor: crosshair;
  }
  .redbox {
    position: absolute;
    border: 1.5px solid var(--accent);
    background: rgba(255, 255, 255, 0.08);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    border-radius: 2px;
    pointer-events: none;
  }
  .redbox.active {
    background: rgba(59, 130, 246, 0.18);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
  }
  .hint {
    position: absolute;
    bottom: 10px;
    left: 50%;
    transform: translateX(-50%);
    background: rgba(0, 0, 0, 0.6);
    color: #fff;
    font-size: var(--text-small);
    padding: 4px 10px;
    border-radius: var(--radius);
    pointer-events: none;
  }

  .controls {
    height: 44px;
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 0 12px;
    background: var(--bg-content);
    border-top: 1px solid var(--border);
    flex-shrink: 0;
  }
  .iconbtn {
    width: 28px;
    height: 28px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    border: none;
    background: transparent;
    color: var(--fg-primary);
    border-radius: var(--radius);
    cursor: pointer;
    padding: 0;
  }
  .iconbtn:hover {
    background: var(--bg-hover);
  }
  .iconbtn svg {
    width: 16px;
    height: 16px;
    fill: currentColor;
  }
  .timeline {
    flex: 1;
    accent-color: var(--accent);
  }
  .time {
    font-size: var(--text-small);
    color: var(--fg-secondary);
    font-variant-numeric: tabular-nums;
    min-width: 84px;
    text-align: right;
  }

  .panel {
    background: var(--bg-content);
    border-top: 1px solid var(--border);
    padding: 8px 12px;
    flex-shrink: 0;
    max-height: 38vh;
    overflow: auto;
  }
  .panel-head {
    display: flex;
    align-items: center;
    gap: 12px;
  }
  .panel-head .title {
    font-size: var(--text-base);
    font-weight: 600;
    color: var(--fg-primary);
  }
  .spacer {
    flex: 1;
  }
  .field {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    color: var(--fg-secondary);
    font-size: var(--text-small);
  }
  .field input[type='range'] {
    width: 90px;
    accent-color: var(--accent);
  }
  .field .num,
  .grow .num {
    min-width: 28px;
    text-align: right;
    font-variant-numeric: tabular-nums;
    color: var(--fg-primary);
  }
  .field .lbl {
    color: var(--fg-secondary);
  }

  .empty {
    color: var(--fg-secondary);
    font-size: var(--text-small);
    padding: 10px 2px;
  }
  .redlist {
    list-style: none;
    margin: 8px 0 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .redrow {
    display: flex;
    align-items: center;
    gap: 6px;
    background: var(--bg-field);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 4px 8px;
  }
  .redrow .idx {
    width: 18px;
    height: 18px;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: var(--accent);
    color: #fff;
    border-radius: 50%;
    font-size: 10px;
    font-weight: 700;
    flex-shrink: 0;
  }
  .t {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: var(--text-small);
    color: var(--fg-secondary);
  }
  .t input[type='number'] {
    width: 64px;
    height: 22px;
    background: var(--bg-content);
    color: var(--fg-primary);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    font-size: var(--text-small);
    padding: 0 4px;
  }
  .set {
    height: 22px;
    min-width: 22px;
    border: 1px solid var(--border);
    background: var(--bg-content);
    color: var(--fg-primary);
    border-radius: var(--radius);
    cursor: pointer;
    font-size: 13px;
    line-height: 1;
  }
  .set:hover {
    background: var(--bg-hover);
  }
  .del {
    height: 22px;
    min-width: 22px;
    border: 1px solid var(--border);
    background: var(--bg-content);
    color: var(--danger);
    border-radius: var(--radius);
    cursor: pointer;
    font-size: 12px;
    line-height: 1;
  }
  .del:hover {
    background: var(--bg-hover);
  }

  .ghost,
  .primary {
    height: 28px;
    padding: 0 12px;
    border-radius: var(--radius);
    cursor: pointer;
    font-size: var(--text-small);
    font-weight: 600;
  }
  .ghost {
    border: 1px solid var(--border-strong);
    background: var(--bg-field);
    color: var(--fg-primary);
  }
  .ghost:hover {
    background: var(--bg-hover);
  }
  .primary {
    border: 1px solid var(--accent);
    background: var(--accent);
    color: #fff;
  }
  .primary:hover:not(:disabled) {
    filter: brightness(1.08);
  }
  .ghost:disabled,
  .primary:disabled {
    opacity: 0.45;
    cursor: default;
  }

  .gif-dialog {
    position: absolute;
    right: 16px;
    bottom: 60px;
    width: 280px;
    background: var(--bg-elevated);
    border: 1px solid var(--border-strong);
    border-radius: var(--radius);
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.5);
    padding: 12px;
    display: flex;
    flex-direction: column;
    gap: 10px;
    z-index: 10;
  }
  .gif-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .gif-head .title {
    font-weight: 600;
    color: var(--fg-primary);
  }
  .gif-dialog .grow {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: var(--text-small);
    color: var(--fg-secondary);
  }
  .gif-dialog .grow input[type='range'] {
    flex: 1;
    accent-color: var(--accent);
  }
  .toggle {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: var(--text-small);
    color: var(--fg-primary);
    cursor: pointer;
  }
  .toggle input {
    accent-color: var(--accent);
  }
  .range-row {
    display: flex;
    gap: 10px;
  }
  .gif-actions {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
  }

  .toast {
    position: absolute;
    bottom: 60px;
    left: 50%;
    transform: translateX(-50%);
    background: var(--bg-elevated);
    border: 1px solid var(--border-strong);
    color: var(--fg-primary);
    padding: 8px 14px;
    border-radius: var(--radius);
    font-size: var(--text-small);
    box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
    z-index: 20;
  }
  .toast.err {
    border-color: var(--danger);
    color: var(--danger);
  }
</style>
