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
  let blur = $state(30);

  // Per-region colour (Qt parity: video.py PALETTE). Used to tell the timeline
  // bands apart and to tint the SELECTED overlay box — never the export, which
  // is a plain ffmpeg boxblur with no colour.
  const PALETTE = ['#f59e0b', '#3b82f6', '#10b981', '#ef4444', '#a855f7', '#ec4899', '#22d3ee', '#84cc16'];
  function colorOf(i: number): string {
    return PALETTE[i % PALETTE.length];
  }
  // Seed strength from settings (video_blur_strength, default 30).
  $effect(() => {
    void ipcInvoke<Record<string, unknown>>('get_settings')
      .then((s) => {
        const v = Number(s?.video_blur_strength ?? 30);
        if (Number.isFinite(v) && v > 0) blur = v;
      })
      .catch(() => {});
  });

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
    selected = redactions.length - 1; // new blur becomes the active span
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

  // --- timeline span bar (Qt parity: video.py SpanBar) -----------------------
  // Each blur's [start,end] is a draggable band above the seek bar:
  //   drag a band's edge  → adjust start/end independently
  //   drag inside a band  → move the whole span
  //   drag on empty bar   → redefine the SELECTED blur's span from scratch
  // The video scrubs live during every drag.
  let selected = $state(0);
  let spanbarEl = $state<HTMLDivElement | null>(null);
  type SpanDrag = { idx: number; mode: 'start' | 'end' | 'move' | 'define'; grab: number; anchor: number };
  let spanDrag: SpanDrag | null = null;
  const EDGE_PX = 7;
  const MIN_SPAN = 0.05;
  // Hover cursor on the span bar — Qt SpanBar parity (video.py mouseMoveEvent):
  // resize over an edge handle, grab over a band body, crosshair on empty.
  let spanCursor = $state('crosshair');

  /** What a press at the pointer would do (edge handle / band body / empty). */
  function spanHit(e: PointerEvent): 'start' | 'end' | 'move' | null {
    if (!duration || !spanbarEl) return null;
    const r = spanbarEl.getBoundingClientRect();
    const x = e.clientX - r.left;
    const t = tAt(e);
    // Edges first so adjacent/overlapping bands stay resizable.
    for (let i = 0; i < redactions.length; i++) {
      const b = redactions[i];
      if (Math.abs(x - (b.start / duration) * r.width) <= EDGE_PX) return 'start';
      if (Math.abs(x - (b.end / duration) * r.width) <= EDGE_PX) return 'end';
    }
    for (let i = 0; i < redactions.length; i++) {
      const b = redactions[i];
      if (t >= b.start && t <= b.end) return 'move';
    }
    return null;
  }

  function round3(v: number): number {
    return Number(v.toFixed(3));
  }
  function tAt(e: PointerEvent): number {
    const r = spanbarEl!.getBoundingClientRect();
    const f = Math.min(1, Math.max(0, (e.clientX - r.left) / Math.max(1, r.width)));
    return f * (duration || 0);
  }
  function scrub(t: number) {
    const v = videoEl;
    const c = Math.min(Math.max(0, t), duration || 0);
    if (v) v.currentTime = c;
    current = c;
  }

  function spanPointerDown(e: PointerEvent) {
    if (!duration || !spanbarEl || e.button !== 0) return;
    spanbarEl.setPointerCapture(e.pointerId);
    const r = spanbarEl.getBoundingClientRect();
    const x = e.clientX - r.left;
    const t = tAt(e);
    // Edges win over interiors so adjacent/overlapping bands stay editable.
    for (let i = 0; i < redactions.length; i++) {
      const b = redactions[i];
      const x0 = (b.start / duration) * r.width;
      const x1 = (b.end / duration) * r.width;
      if (Math.abs(x - x0) <= EDGE_PX) {
        selected = i;
        spanDrag = { idx: i, mode: 'start', grab: 0, anchor: t };
        spanCursor = 'ew-resize';
        scrub(b.start);
        return;
      }
      if (Math.abs(x - x1) <= EDGE_PX) {
        selected = i;
        spanDrag = { idx: i, mode: 'end', grab: 0, anchor: t };
        spanCursor = 'ew-resize';
        scrub(b.end);
        return;
      }
    }
    for (let i = 0; i < redactions.length; i++) {
      const b = redactions[i];
      if (t >= b.start && t <= b.end) {
        selected = i;
        spanDrag = { idx: i, mode: 'move', grab: t - b.start, anchor: t };
        spanCursor = 'grabbing';
        scrub(t);
        return;
      }
    }
    if (redactions.length > 0) {
      const i = Math.min(selected, redactions.length - 1);
      selected = i;
      spanDrag = { idx: i, mode: 'define', grab: 0, anchor: t };
      spanCursor = 'grabbing';
      redactions = redactions.map((b, j) =>
        j === i ? { ...b, start: round3(t), end: round3(Math.min(duration, t + MIN_SPAN)) } : b
      );
      scrub(t);
    }
  }

  function spanPointerMove(e: PointerEvent) {
    if (!spanDrag) {
      // Not dragging: reflect what a press would do, so the edge handles are
      // discoverable (Qt SpanBar cursor parity).
      const h = spanHit(e);
      spanCursor = h === 'start' || h === 'end' ? 'ew-resize' : h === 'move' ? 'grab' : 'crosshair';
      return;
    }
    if (!duration) return;
    const t = tAt(e);
    const { idx, mode, grab, anchor } = spanDrag;
    const b = redactions[idx];
    if (!b) return;
    if (mode === 'start') {
      setField(idx, 'start', round3(Math.min(Math.max(0, t), b.end - MIN_SPAN)));
    } else if (mode === 'end') {
      setField(idx, 'end', round3(Math.max(Math.min(duration, t), b.start + MIN_SPAN)));
    } else if (mode === 'move') {
      const len = b.end - b.start;
      const ns = Math.min(Math.max(0, t - grab), duration - len);
      redactions = redactions.map((r2, j) =>
        j === idx ? { ...r2, start: round3(ns), end: round3(ns + len) } : r2
      );
    } else {
      const a = Math.min(anchor, t);
      const z = Math.max(anchor, t);
      redactions = redactions.map((r2, j) =>
        j === idx ? { ...r2, start: round3(Math.max(0, a)), end: round3(Math.min(duration, Math.max(z, a + MIN_SPAN))) } : r2
      );
    }
    scrub(t);
  }

  function spanPointerUp() {
    spanDrag = null;
    spanCursor = 'crosshair'; // next hover recomputes the handle/body cursor
  }

  /** Delete/Backspace removes the selected blur region. */
  function onKeyDown(e: KeyboardEvent) {
    const el = e.target as HTMLElement | null;
    if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) return;
    if ((e.key === 'Delete' || e.key === 'Backspace') && redactions.length > 0) {
      removeRedaction(selected);
      e.preventDefault();
    }
  }
  function removeRedaction(i: number) {
    redactions = redactions.filter((_, j) => j !== i);
    selected = Math.max(0, Math.min(selected, redactions.length - 1));
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

<svelte:window onkeydown={onKeyDown} />

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
        <!-- Qt parity (video.py:295): only frost the region while the playhead
             is inside its span — scrubbing previews exactly what gets blurred
             and when. Outside the span this blur isn't applied, so it vanishes. -->
        {#if current >= r.start && current <= r.end}
          <!-- Plain blur by default; only the SELECTED region gets its palette
               colour, so you can tell which one you're editing. Colour is
               preview-only CSS — it never reaches the exported video. -->
          <div
            class="redbox"
            class:sel={i === selected}
            style="{boxStyle(r)};--c:{colorOf(i)}"
            title={`${r.start.toFixed(1)}s–${r.end.toFixed(1)}s`}
          >
            {#if i === selected}<span class="rednum">{i + 1}</span>{/if}
          </div>
        {/if}
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
    <div class="tstack">
      {#if redactions.length > 0}
        <!-- svelte-ignore a11y_no_static_element_interactions -->
        <div
          class="spanbar"
          style="cursor:{spanCursor}"
          bind:this={spanbarEl}
          onpointerdown={spanPointerDown}
          onpointermove={spanPointerMove}
          onpointerup={spanPointerUp}
          onpointercancel={spanPointerUp}
          title="Drag edges to adjust · drag inside to move · drag empty space to redefine the selected blur"
        >
          {#if duration > 0}
            {#each redactions as b, i (i)}
              <div
                class="span"
                class:sel={i === selected}
                style="left:{(b.start / duration) * 100}%; width:{Math.max(0.6, ((b.end - b.start) / duration) * 100)}%; --c:{colorOf(i)}"
              >
                <span class="grip l"></span>
                <span class="grip r"></span>
              </div>
            {/each}
          {/if}
        </div>
      {/if}
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
    </div>
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
      <div class="spanhint">
        {redactions.length} region{redactions.length === 1 ? '' : 's'} — the orange bands above
        the timeline are when each blur is active: drag the handles to adjust, drag inside to
        move, click a band to select it.
        <button class="del" title="Delete the selected region (Del)" aria-label="Delete the selected region" onclick={() => removeRedaction(selected)}>✕ region {selected + 1}</button>
      </div>
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
    /* Plain blur — neutral hairline only, no colour, so it reads as a frosted
       region. Colour appears solely on the selected box (.sel). */
    border: 1px solid rgba(255, 255, 255, 0.22);
    background: transparent;
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
    border-radius: 2px;
    pointer-events: none;
  }
  /* The in-progress draw band (transient) — accent so you see what you're drawing. */
  .redbox.active {
    border-color: var(--accent);
    background: rgba(59, 130, 246, 0.18);
    backdrop-filter: blur(4px);
    -webkit-backdrop-filter: blur(4px);
  }
  .redbox.sel {
    border: 2px solid var(--c);
    box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.45);
  }
  .rednum {
    position: absolute;
    top: 2px;
    left: 4px;
    font-size: 11px;
    font-weight: 700;
    line-height: 1;
    color: #fff;
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.8);
    pointer-events: none;
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
  .tstack {
    flex: 1;
    display: flex;
    flex-direction: column;
    gap: 3px;
    min-width: 0;
  }
  .timeline {
    width: 100%;
    accent-color: var(--accent);
  }
  /* Blur-span bands: deliberately NOT the accent blue — these are blur time
     ranges, not a seek control. */
  .spanbar {
    position: relative;
    height: 18px;
    background: var(--bg-field);
    border: 1px solid var(--border);
    border-radius: 4px;
    cursor: crosshair;
    touch-action: none;
    user-select: none;
  }
  /* Each band is tinted with its region's palette colour (--c) so multiple
     blurs are distinguishable; the selected one is more saturated. */
  .span {
    position: absolute;
    top: 1px;
    bottom: 1px;
    background: color-mix(in srgb, var(--c) 28%, transparent);
    border: 1px solid var(--c);
    border-radius: 3px;
    cursor: grab;
    pointer-events: none; /* the bar owns hit-testing (edges need slop) */
  }
  .span.sel {
    background: color-mix(in srgb, var(--c) 60%, transparent);
    border-width: 2px;
    z-index: 1;
  }
  .grip {
    position: absolute;
    top: 2px;
    bottom: 2px;
    width: 4px;
    border-radius: 2px;
    background: rgba(255, 255, 255, 0.92);
    box-shadow: 0 0 0 1px rgba(0, 0, 0, 0.35);
  }
  .grip.l { left: -2px; }
  .grip.r { right: -2px; }
  .spanhint {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: var(--text-small);
    color: var(--fg-secondary);
    padding: 4px 2px;
  }
  .spanhint .del {
    margin-left: auto;
    white-space: nowrap;
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
