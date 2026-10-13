<script lang="ts">
  import { mediaSrc, ipcInvoke } from '$lib/ipc';
  import { loadLibrary, captures, activeItem } from '$lib/stores';
  import { get } from 'svelte/store';
  import VideoToolIcon from './VideoToolIcon.svelte';

  // A blur region in VIDEO pixel coords, active for [start,end] seconds.
  // Field names match wondershot-core::video::Redaction (serde).
  type Redaction = { x: number; y: number; w: number; h: number; start: number; end: number; blur?: number };

  let { path }: { path: string } = $props();

  // --- media element + playback state ---------------------------------------
  let videoEl = $state<HTMLVideoElement | null>(null);
  let src = $state('');
  let playing = $state(false);
  let rangeMode = $state(false);
  let blurSettingsOpen = $state(false);
  let rangeStart = $state(0);
  let rangeEnd = $state(0);
  let rangeBar = $state<HTMLDivElement | null>(null);
  let rangeDrag: { mode: 'start' | 'end' | 'define'; anchor: number } | null = null;
  let current = $state(0);
  let duration = $state(0);
  let videoWidth = $state(0);
  let videoHeight = $state(0);

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
  let overlaySize = $state({ width: 0, height: 0 });
  $effect(() => {
    const overlay = overlayEl; if (!overlay) return;
    const observer = new ResizeObserver(([entry]) => {
      overlaySize = { width: entry.contentRect.width, height: entry.contentRect.height };
    });
    observer.observe(overlay);
    return () => observer.disconnect();
  });
  let redactions = $state<Redaction[]>([]);
  let blur = $state(30);
  let undoStack = $state<Redaction[][]>([]);
  let redoStack = $state<Redaction[][]>([]);
  const snapshot = () => redactions.map(r => ({ ...r }));
  function remember() { undoStack = [...undoStack, snapshot()].slice(-100); redoStack = []; }
  function undo() {
    const previous = undoStack.at(-1); if (!previous || busy) return;
    redoStack = [...redoStack, snapshot()]; undoStack = undoStack.slice(0, -1);
    redactions = previous; selected = Math.max(0, Math.min(selected, redactions.length - 1));
    blur = redactions[selected]?.blur ?? blur;
    if (redactions.length) { rangeMode = false; gifOpen = false; }
  }
  function redo() {
    const next = redoStack.at(-1); if (!next || busy) return;
    undoStack = [...undoStack, snapshot()]; redoStack = redoStack.slice(0, -1);
    redactions = next; selected = Math.max(0, Math.min(selected, redactions.length - 1));
    blur = redactions[selected]?.blur ?? blur;
    if (redactions.length) { rangeMode = false; gifOpen = false; }
  }
  // Preserve editable drafts per source, independently of rendered exports.
  $effect(() => {
    const key = `wondershot-video-blurs:${path}`;
    videoEl?.pause(); playing = false; current = 0; duration = 0; videoWidth = 0; videoHeight = 0;
    rangeMode = false; gifOpen = false; blurSettingsOpen = false; drag = null; transformDrag = null;
    undoStack = []; redoStack = []; selected = 0;
    try {
      const saved = JSON.parse(localStorage.getItem(key) ?? '[]');
      redactions = Array.isArray(saved) ? saved.filter(r => ['x','y','w','h','start','end'].every(k => Number.isFinite(r[k])) && r.w > 0 && r.h > 0 && r.start >= 0 && r.end > r.start && (r.blur == null || (Number.isFinite(r.blur) && r.blur >= 1 && r.blur <= 60))) : [];
    } catch { redactions = []; }
  });
  $effect(() => {
    try { localStorage.setItem(`wondershot-video-blurs:${path}`, JSON.stringify(redactions)); } catch { /* storage may be unavailable */ }
  });
  let transformDrag: { index: number; mode: 'move' | 'resize'; x: number; y: number; original: Redaction; recorded: boolean } | null = null;
  function selectRegion(i: number) {
    selected = i; blur = redactions[i]?.blur ?? blur; videoEl?.pause(); playing = false;
    const r = redactions[i]; if (r && (current < r.start || current >= r.end)) scrub(r.start);
  }
  function beginTransform(e: PointerEvent, i: number, mode: 'move' | 'resize') {
    if (playing || busy || rangeMode || e.button !== 0) return;
    e.stopPropagation(); selectRegion(i);
    const p = localPoint(e); transformDrag = { index: i, mode, ...p, original: { ...redactions[i] }, recorded: false };
    overlayEl?.setPointerCapture(e.pointerId);
  }
  function changeStrength(value: number) {
    blur = value;
    if (redactions[selected]) { remember(); redactions = redactions.map((r,i) => i === selected ? {...r, blur:value} : r); }
  }
  function updateRegion(i: number, key: 'x' | 'y' | 'w' | 'h' | 'start' | 'end', value: number) {
    const r = redactions[i]; if (!r || !Number.isFinite(value)) return;
    const vw = videoEl?.videoWidth ?? 0, vh = videoEl?.videoHeight ?? 0;
    const limits = { x: [0, Math.max(0, vw - r.w)], y: [0, Math.max(0, vh - r.h)], w: [4, Math.max(4, vw - r.x)], h: [4, Math.max(4, vh - r.y)], start: [0, r.end - MIN_SPAN], end: [r.start + MIN_SPAN, duration] };
    const [min, max] = limits[key]; remember();
    redactions = redactions.map((item,j) => j === i ? { ...item, [key]: key === 'start' || key === 'end' ? round3(Math.max(min, Math.min(max,value))) : Math.round(Math.max(min, Math.min(max,value))) } : item);
  }


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
    const vw = videoWidth;
    const vh = videoHeight;
    const r = ov.getBoundingClientRect();
    const width = overlaySize.width || r.width, height = overlaySize.height || r.height;
    if (vw === 0 || vh === 0 || width === 0 || height === 0) {
      // No intrinsic size yet (mock/headless): fall back to 1:1 with the box.
      return { left: 0, top: 0, w: width, h: height, sx: 1, sy: 1 };
    }
    // contain scale: the smaller ratio fills.
    const scale = Math.min(width / vw, height / vh);
    const dispW = vw * scale;
    const dispH = vh * scale;
    const left = (width - dispW) / 2;
    const top = (height - dispH) / 2;
    return { left, top, w: dispW, h: dispH, sx: vw / dispW, sy: vh / dispH };
  }

  // Convert a Redaction (video coords) → CSS box (display coords) for preview.
  function boxStyle(r: Redaction): string {
    const c = displayContentBox();
    if (!c) return 'display:none';
    // Match the outward-rounded pixel edges used by the export backend.
    const x = Math.floor(r.x / 2) * 2, y = Math.floor(r.y / 2) * 2;
    const right = Math.min(videoWidth || Infinity, Math.ceil((r.x + r.w) / 2) * 2);
    const bottom = Math.min(videoHeight || Infinity, Math.ceil((r.y + r.h) / 2) * 2);
    const left = c.left + x / c.sx;
    const top = c.top + y / c.sy;
    const w = (right - x) / c.sx;
    const h = (bottom - y) / c.sy;
    return `left:${left}px;top:${top}px;width:${w}px;height:${h}px;--blur:${(r.blur ?? blur) / c.sx}px`;
  }

  function localPoint(e: PointerEvent): { x: number; y: number } {
    const r = overlayEl!.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }

  function onPointerDown(e: PointerEvent) {
    if (playing || busy || rangeMode || gifOpen) return; // only draw while paused
    if (e.button !== 0) return;
    (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
    const p = localPoint(e);
    drag = { x0: p.x, y0: p.y, x1: p.x, y1: p.y };
  }
  function onPointerMove(e: PointerEvent) {
    if (transformDrag) {
      const c = displayContentBox(); if (!c) return;
      const p = localPoint(e), d = transformDrag, r = d.original;
      const dx = (p.x - d.x) * c.sx, dy = (p.y - d.y) * c.sy;
      if (Math.abs(dx) + Math.abs(dy) < 1) return;
      if (!d.recorded) { remember(); d.recorded = true; }
      const vw = videoEl?.videoWidth || c.w * c.sx, vh = videoEl?.videoHeight || c.h * c.sy;
      const updated = d.mode === 'move'
        ? { ...r, x: Math.round(Math.max(0, Math.min(vw-r.w, r.x+dx))), y: Math.round(Math.max(0, Math.min(vh-r.h, r.y+dy))) }
        : { ...r, w: Math.round(Math.max(4, Math.min(vw-r.x, r.w+dx))), h: Math.round(Math.max(4, Math.min(vh-r.y, r.h+dy))) };
      redactions = redactions.map((item,i) => i === d.index ? updated : item); return;
    }
    if (!drag) return;
    const p = localPoint(e);
    drag = { ...drag, x1: p.x, y1: p.y };
  }
  function onPointerUp() {
    if (transformDrag) { transformDrag = null; return; }
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
    const vw = Math.min(dw * c.sx, c.w * c.sx - vx);
    const vh = Math.min(dh * c.sy, c.h * c.sy - vy);
    if (vw < 4 || vh < 4) return;
    const start = Math.min(current, Math.max(0, duration - MIN_SPAN));
    const end = Math.min(duration || start + 2, start + 2);
    remember();
    redactions = [
      ...redactions,
      { x: Math.round(vx), y: Math.round(vy), w: Math.round(vw), h: Math.round(vh), start, end, blur }
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
  type SpanDrag = { idx: number; mode: 'start' | 'end' | 'move' | 'define'; grab: number; anchor: number; recorded?: boolean };
  let spanDrag: SpanDrag | null = null;
  const EDGE_PX = 7;
  const MIN_SPAN = 0.05;
  // Hover cursor on the span bar — Qt SpanBar parity (video.py mouseMoveEvent):
  // resize over an edge handle, grab over a band body, crosshair on empty.
  let spanCursor = $state('crosshair');

  function regionOrder() { return [selected, ...redactions.map((_,i) => i).filter(i => i !== selected)].filter(i => !!redactions[i]); }

  /** What a press at the pointer would do (edge handle / band body / empty). */
  function spanHit(e: PointerEvent): 'start' | 'end' | 'move' | null {
    if (!duration || !spanbarEl) return null;
    const r = spanbarEl.getBoundingClientRect();
    const x = e.clientX - r.left;
    const t = tAt(e);
    // Edges first so adjacent/overlapping bands stay resizable.
    for (const i of regionOrder()) {
      const b = redactions[i];
      if (Math.abs(x - (b.start / duration) * r.width) <= EDGE_PX) return 'start';
      if (Math.abs(x - (b.end / duration) * r.width) <= EDGE_PX) return 'end';
    }
    for (const i of regionOrder()) {
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
    if (!duration || !spanbarEl || e.button !== 0 || busy) return;
    spanbarEl.setPointerCapture(e.pointerId);
    const r = spanbarEl.getBoundingClientRect();
    const x = e.clientX - r.left;
    const t = tAt(e);
    // Edges win over interiors so adjacent/overlapping bands stay editable.
    for (const i of regionOrder()) {
      const b = redactions[i];
      const x0 = (b.start / duration) * r.width;
      const x1 = (b.end / duration) * r.width;
      if (Math.abs(x - x0) <= EDGE_PX) {
        selected = i;
        blur = b.blur ?? blur;
        spanDrag = { idx: i, mode: 'start', grab: 0, anchor: t };
        spanCursor = 'ew-resize';
        scrub(b.start);
        return;
      }
      if (Math.abs(x - x1) <= EDGE_PX) {
        selected = i;
        blur = b.blur ?? blur;
        spanDrag = { idx: i, mode: 'end', grab: 0, anchor: t };
        spanCursor = 'ew-resize';
        scrub(b.end);
        return;
      }
    }
    for (const i of regionOrder()) {
      const b = redactions[i];
      if (t >= b.start && t <= b.end) {
        selected = i;
        blur = b.blur ?? blur;
        spanDrag = { idx: i, mode: 'move', grab: t - b.start, anchor: t };
        spanCursor = 'grabbing';
        scrub(t);
        return;
      }
    }
    if (redactions.length > 0) {
      const i = Math.min(selected, redactions.length - 1);
      selected = i;
      remember();
      spanDrag = { idx: i, mode: 'define', grab: 0, anchor: t, recorded: true };
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
    if (!spanDrag.recorded) { remember(); spanDrag.recorded = true; }
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
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z') { e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
    if (busy || rangeMode) return;
    if ((e.key === 'Delete' || e.key === 'Backspace') && redactions.length > 0) {
      removeRedaction(selected);
      e.preventDefault();
    }
  }
  function removeRedaction(i: number) {
    if (busy || !redactions[i]) return;
    remember();
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
      await selectByPath(out);
      flash('Blur applied');
    } catch (e) {
      flash(`Blur failed: ${e}`, true);
    } finally {
      busy = false;
    }
  }

  function openRange() {
    if (redactions.length && !rangeMode) { flash('Apply or remove blur layers before trimming', true); return; }
    gifOpen = false;
    videoEl?.pause(); playing = false; rangeMode = !rangeMode;
    if (rangeMode) { rangeStart = 0; rangeEnd = duration; }
  }
  function rangeTime(e: PointerEvent) {
    const r = rangeBar!.getBoundingClientRect();
    return round3(Math.max(0, Math.min(1,(e.clientX-r.left)/r.width))*duration);
  }
  function rangeDown(e: PointerEvent) {
    if (e.button !== 0 || busy || !duration || !rangeBar) return;
    e.preventDefault();
    (e.target as HTMLElement).closest<HTMLButtonElement>('[data-range-handle]')?.focus();
    rangeBar.setPointerCapture(e.pointerId); const t = rangeTime(e);
    const tolerance = duration * 10 / rangeBar.getBoundingClientRect().width;
    const handle = (e.target as HTMLElement).closest('[data-range-handle]')?.getAttribute('data-range-handle');
    const mode = handle === 'start' || handle === 'end' ? handle : Math.abs(t-rangeStart) < tolerance ? 'start' : Math.abs(t-rangeEnd) < tolerance ? 'end' : 'define';
    rangeDrag = { mode, anchor: t };
    if (mode === 'define') { rangeStart = Math.min(t,duration-MIN_SPAN); rangeEnd = Math.min(duration,t+MIN_SPAN); }
    scrub(t);
  }
  function rangeMove(e: PointerEvent) {
    if (!rangeDrag) return; const t = rangeTime(e);
    if (rangeDrag.mode === 'start') rangeStart = Math.min(t,rangeEnd-MIN_SPAN);
    else if (rangeDrag.mode === 'end') rangeEnd = Math.max(t,rangeStart+MIN_SPAN);
    else { rangeStart = Math.min(rangeDrag.anchor,t,duration-MIN_SPAN); rangeEnd = Math.min(duration,Math.max(rangeDrag.anchor,t,rangeStart+MIN_SPAN)); }
    scrub(t);
  }
  function rangeKey(e: KeyboardEvent, edge: 'start' | 'end') {
    const value = edge === 'start' ? rangeStart : rangeEnd;
    const delta = e.shiftKey ? 1 : .1;
    const next = e.key === 'ArrowLeft' ? value - delta : e.key === 'ArrowRight' ? value + delta : e.key === 'Home' ? 0 : e.key === 'End' ? duration : null;
    if (next === null || busy) return;
    e.preventDefault();
    e.stopPropagation();
    if (edge === 'start') rangeStart = round3(Math.max(0,Math.min(next,rangeEnd-MIN_SPAN)));
    else rangeEnd = round3(Math.min(duration,Math.max(next,rangeStart+MIN_SPAN)));
    scrub(edge === 'start' ? rangeStart : rangeEnd);
  }
  const rangeValid = $derived(Number.isFinite(rangeStart) && Number.isFinite(rangeEnd) && rangeStart >= 0 && rangeEnd <= duration && rangeEnd-rangeStart >= MIN_SPAN);
  async function saveRange(cut: boolean) {
    if (redactions.length) { flash('Apply or remove blur layers before trimming',true); return; }
    if (busy || !rangeValid) return;
    busy = true;
    try {
      const out = await ipcInvoke<string>(cut ? 'cut_video' : 'trim_video', { path, start: rangeStart, end: rangeEnd, reencode: true });
      await selectByPath(out); rangeMode = false; flash(cut ? 'Section removed — saved as a new video' : 'Trim saved as a new video');
    } catch (e) { flash(`Video edit failed: ${e}`,true); } finally { busy = false; }
  }
  async function grabFrame() {
    if (redactions.length) { flash('Apply blur layers before taking a screenshot',true); return; }
    if (busy) return; busy = true;
    try { const out = await ipcInvoke<string>('grab_frame', { path, position: Math.min(current, Math.max(0,duration-0.05)) }); await selectByPath(out); flash('Frame saved'); }
    catch(e) { flash(`Frame capture failed: ${e}`,true); } finally { busy = false; }
  }

  // --- GIF dialog -----------------------------------------------------------
  let gifOpen = $state(false);
  let gifFps = $state(12);
  let gifWidth = $state(720);
  let gifUseRange = $state(false);
  let gifStart = $state(0);
  let gifEnd = $state(0);

  function openGif() {
    if (redactions.length) { flash('Apply blur layers before exporting a GIF',true); return; }
    rangeMode = false;
    gifStart = Number(current.toFixed(3));
    gifEnd = Number(Math.min(duration || current + 3, current + 3).toFixed(3));
    gifOpen = true;
  }
  async function exportGif() {
    if (redactions.length) { flash('Apply blur layers before exporting a GIF',true); return; }
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
  <header class="toolbar" aria-label="Video Editing Tools">
    <button class="tool" class:active={rangeMode} onclick={openRange} disabled={busy || !duration} aria-pressed={rangeMode}><VideoToolIcon name="trim" /><span>Trim / Cut</span></button>
    {#if rangeMode}
      <button class="tool" onclick={() => saveRange(false)} disabled={busy || !rangeValid} title="Keep the selected section in a new video"><VideoToolIcon name="save" /><span>Save Trim</span></button>
      <button class="tool" onclick={() => saveRange(true)} disabled={busy || !rangeValid || (rangeStart === 0 && rangeEnd === duration)} title="Remove the selected section and join the rest in a new video"><VideoToolIcon name="cut" /><span>Remove Selection</span></button>
      <button class="tool" onclick={() => rangeMode = false} disabled={busy} title="Cancel Trim"><VideoToolIcon name="close" /><span>Cancel</span></button>
    {:else}
      <button class="tool" class:active={blurSettingsOpen || redactions.length > 0} onclick={() => blurSettingsOpen = !blurSettingsOpen} disabled={busy}><VideoToolIcon name="blur" /><span>Blur</span></button>
      {#if redactions.length}
        <button class="tool" onclick={applyBlur} disabled={busy}><VideoToolIcon name="apply" /><span>{busy ? 'Working…' : 'Apply Blur'}</span></button>
      {/if}
      <span class="sep"></span>
      <button class="tool" onclick={undo} disabled={busy || !undoStack.length} title="Undo (⌘Z)"><VideoToolIcon name="undo" /><span>Undo</span></button>
      <button class="tool" onclick={redo} disabled={busy || !redoStack.length} title="Redo (⇧⌘Z)"><VideoToolIcon name="redo" /><span>Redo</span></button>
      <span class="sep"></span>
      <button class="tool" onclick={grabFrame} disabled={busy || !duration}><VideoToolIcon name="screenshot" /><span>Screenshot</span></button>
      <button class="tool" class:active={gifOpen} aria-expanded={gifOpen} onclick={openGif} disabled={busy}><VideoToolIcon name="gif" /><span>Export GIF…</span></button>
      {#if gifOpen}
        <button class="tool" onclick={exportGif} disabled={busy}><VideoToolIcon name="save" /><span>{busy ? 'Working…' : 'Export GIF'}</span></button>
        <button class="tool" onclick={() => gifOpen = false} disabled={busy}><VideoToolIcon name="close" /><span>Cancel</span></button>
      {/if}
    {/if}
  </header>
  <div class="video-body">
  <div class="video-main">
  <div class="stage">
    <!-- svelte-ignore a11y_media_has_caption -->
    <video
      bind:this={videoEl}
      {src}
      onplay={() => (playing = true)}
      onpause={() => (playing = false)}
      ontimeupdate={() => (current = videoEl?.currentTime ?? 0)}
      onloadedmetadata={() => { duration = videoEl?.duration ?? 0; videoWidth = videoEl?.videoWidth ?? 0; videoHeight = videoEl?.videoHeight ?? 0; }}
      onerror={() => console.error('video error', videoEl?.error?.code, videoEl?.error?.message)}
      onclick={togglePlay}
    ></video>

    <!-- Redaction overlay: draws boxes when paused. -->
    <div
      class="overlay"
      class:drawing={!playing && !rangeMode && !gifOpen}
      bind:this={overlayEl}
      role="presentation"
      onpointerdown={onPointerDown}
      onpointermove={onPointerMove}
      onpointerup={onPointerUp}
      onpointercancel={() => { drag = null; transformDrag = null; }}
    >
      {#each redactions as r, i (i)}
        <!-- Qt parity (video.py:295): only frost the region while the playhead
             is inside its span — scrubbing previews exactly what gets blurred
             and when. Outside the span this blur isn't applied, so it vanishes. -->
        {#if current >= r.start && current <= r.end}
          <!-- Plain blur by default; only the SELECTED region gets its palette
               colour, so you can tell which one you're editing. Colour is
               preview-only CSS — it never reaches the exported video. -->
          <!-- svelte-ignore a11y_no_static_element_interactions -->
          <div
            class="redbox"
            role="button" tabindex={0} aria-label={`Blur Region ${i + 1}`}
            onpointerdown={(e) => beginTransform(e,i,'move')}
            onkeydown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); selectRegion(i); } }}
            class:sel={i === selected}
            style="{boxStyle(r)};--c:{colorOf(i)}"
            title={`${r.start.toFixed(1)}s–${r.end.toFixed(1)}s`}
          >
            {#if i === selected}
              <span class="rednum">{i + 1}</span>
              <button class="resize-handle" aria-label={`Resize Blur Region ${i + 1}`} onpointerdown={(e) => beginTransform(e,i,'resize')}></button>
            {/if}
          </div>
        {/if}
      {/each}
      {#if drag}
        <div class="redbox active" style={dragStyle}></div>
      {/if}
    </div>

  </div>

    <div class="controls" aria-label="Video Playback Controls">
    <button class="iconbtn" onclick={togglePlay} aria-label={playing ? 'Pause' : 'Play'} title={playing ? 'Pause' : 'Play'}>
      {#if playing}
        <svg viewBox="0 0 16 16"><rect x="3.5" y="2.5" width="3" height="11" /><rect x="9.5" y="2.5" width="3" height="11" /></svg>
      {:else}
        <svg viewBox="0 0 16 16"><path d="M4 2.5l9 5.5-9 5.5z" /></svg>
      {/if}
    </button>
      <div class="tstack">
        <div class="timeline-track">
          <input class="timeline" class:trimming={rangeMode} type="range" min="0" max={duration || 0} step="0.01" value={current} oninput={onSeek} aria-label="Seek" />
          {#if rangeMode}
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <div class="rangebar" role="presentation" bind:this={rangeBar} onpointerdown={rangeDown} onpointermove={rangeMove} onpointerup={() => rangeDrag = null} onpointercancel={() => rangeDrag = null} title="Drag to select a section; drag its edges to adjust">
              <div class="range-selection" style={`left:${rangeStart/duration*100}%;width:${(rangeEnd-rangeStart)/duration*100}%`}><button class="grip l trim-handle" data-range-handle="start" aria-label="Trim Start Handle" title="Drag selection start" onclick={(e) => e.currentTarget.focus()} onkeydown={(e) => rangeKey(e,'start')}></button><button class="grip r trim-handle" data-range-handle="end" aria-label="Trim End Handle" title="Drag selection end" onclick={(e) => e.currentTarget.focus()} onkeydown={(e) => rangeKey(e,'end')}></button></div>
            </div>
          {:else if redactions.length > 0}
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <div class="spanbar" role="presentation" style="cursor:{spanCursor}" bind:this={spanbarEl} onpointerdown={spanPointerDown} onpointermove={spanPointerMove} onpointerup={spanPointerUp} onpointercancel={spanPointerUp} title="Drag blur edges to adjust timing; drag a band to move it">
              {#if duration > 0}
                {#each redactions as b, i}
                  <div class="span" class:sel={i === selected} style="left:{(b.start/duration)*100}%;width:{Math.max(.6,((b.end-b.start)/duration)*100)}%;--c:{colorOf(i)}"><span class="grip l"></span><span class="grip r"></span></div>
                {/each}
              {/if}
            </div>
          {/if}
        </div>
      </div>
      <span class="time">{fmt(current)} / {fmt(duration)}</span>
      {#if rangeMode}
        <div class="trim-fields">
          <input class="trim-time" aria-label="Selection Start" title="Selection Start (Seconds)" type="number" min="0" max={duration} step="0.01" bind:value={rangeStart} />
          <span class="time">–</span>
          <input class="trim-time" aria-label="Selection End" title="Selection End (Seconds)" type="number" min="0" max={duration} step="0.01" bind:value={rangeEnd} />
        </div>
      {/if}
    </div>
  </div>
  {#if !rangeMode && (gifOpen || redactions.length || blurSettingsOpen)}
  <aside class="properties" aria-label="Video properties">
    {#if gifOpen}
    <div class="gif-dialog">
      <div class="gif-head">
        <span class="title">Export GIF</span>
        <button class="del" aria-label="Close" onclick={() => (gifOpen = false)}><VideoToolIcon name="close" /></button>
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
        Limit to Range
      </label>
      {#if gifUseRange}
        <div class="range-row">
          <label class="t">Start <input type="number" min="0" step="0.1" bind:value={gifStart} /></label>
          <label class="t">End <input type="number" min="0" step="0.1" bind:value={gifEnd} /></label>
        </div>
      {/if}

    </div>
    {:else}
      <div class="section">{redactions.length ? 'Blur Layers' : 'Video'}</div>
      {#if redactions.length}
        <div class="blur-layers" aria-label="Blur Layers">
          {#each redactions as r,i}
            <div class="blur-layer" class:chosen={i === selected}>
              <button class="layer-select" aria-label={`Blur ${i+1}`} aria-pressed={i === selected} onclick={() => selectRegion(i)}>Blur {i+1}<span>{r.start.toFixed(1)}–{r.end.toFixed(1)}s</span></button>
              <button class="del" aria-label={`Delete Blur ${i+1}`} onclick={() => removeRedaction(i)} disabled={busy}><VideoToolIcon name="delete" /></button>
            </div>
          {/each}
        </div>
        {#if redactions[selected]}
          <div class="fields">
            <label>Start <input aria-label={`Blur ${selected+1} Start`} type="number" step="0.01" value={redactions[selected].start} onchange={(e) => updateRegion(selected,'start',e.currentTarget.valueAsNumber)} disabled={busy} /></label>
            <label>End <input aria-label={`Blur ${selected+1} End`} type="number" step="0.01" value={redactions[selected].end} onchange={(e) => updateRegion(selected,'end',e.currentTarget.valueAsNumber)} disabled={busy} /></label>
          </div>
        {/if}
      {/if}
      <label class="strength">Strength <span>{blur}</span><input aria-label="Blur Strength" type="range" min="1" max="60" value={blur} oninput={(e) => changeStrength(Number(e.currentTarget.value))} disabled={busy} /></label>
      {#if redactions[selected]}
        <details>
          <summary>Position and Size</summary>
          <div class="fields geometry-fields">
            {#each ['x','y','w','h'] as field}
              <label>{({x:'X',y:'Y',w:'Width',h:'Height'} as Record<string,string>)[field]}
                <input aria-label={`Selected Blur ${({x:'X',y:'Y',w:'Width',h:'Height'} as Record<string,string>)[field]}`} type="number" step="1" value={redactions[selected][field as keyof Redaction]} onchange={(e) => updateRegion(selected,field as 'x' | 'y' | 'w' | 'h',e.currentTarget.valueAsNumber)} disabled={busy} />
              </label>
            {/each}
          </div>
        </details>
      {/if}

      {#if !redactions.length}<p class="help">Pause and drag on the video to add a blur.</p>{/if}
    {/if}
  </aside>
  {/if}
  </div>
  {#if toast}<div class="toast" class:err={errored}>{toast}</div>{/if}
</div>

<style>
  .player { flex:1; display:flex; flex-direction:column; min-width:0; min-height:0; background:var(--bg-content); position:relative; }
  .video-body { flex:1; display:flex; min-width:0; min-height:0; }
  .toolbar { height:60px; display:flex; align-items:center; gap:2px; padding:0 8px; border-bottom:1px solid var(--border); flex-shrink:0; overflow-x:auto; }
  .tool { min-width:46px; height:50px; display:inline-flex; flex-direction:column; align-items:center; justify-content:center; gap:3px; border:0; border-bottom:2px solid transparent; background:transparent; color:var(--fg-secondary); border-radius:var(--radius); cursor:pointer; padding:0 6px; flex-shrink:0; }
  .tool span { font-size:10px; line-height:1; white-space:nowrap; }
  .tool:hover:not(:disabled) { background:var(--bg-hover); color:var(--fg-primary); }
  .tool:disabled { opacity:.4; cursor:not-allowed; }
  .tool.active { background:var(--bg-selected); color:var(--fg-primary); border-bottom-color:var(--accent); border-bottom-left-radius:0; border-bottom-right-radius:0; }
  .sep { width:1px; height:22px; background:var(--border-strong); margin:0 4px; flex-shrink:0; }
  .trim-fields { display:flex; align-items:center; gap:4px; }
  .video-main { flex:1; display:flex; flex-direction:column; min-width:0; min-height:0; }
  .stage { position:relative; flex:1; min-height:0; background:#000; display:flex; align-items:center; justify-content:center; overflow:hidden; }
  video { width:100%; height:100%; object-fit:contain; display:block; }
  .overlay { position:absolute; inset:0; }
  .overlay.drawing { cursor:crosshair; }
  .redbox { position:absolute; border:1px solid rgba(255,255,255,.22); background:transparent; backdrop-filter:blur(var(--blur,8px)); -webkit-backdrop-filter:blur(var(--blur,8px)); border-radius:2px; pointer-events:auto; cursor:move; touch-action:none; }
  .redbox.active { pointer-events:none; border-color:var(--accent); background:rgba(59,130,246,.18); backdrop-filter:blur(4px); -webkit-backdrop-filter:blur(4px); }
  .redbox.sel { border:2px solid var(--c); box-shadow:0 0 0 1px rgba(0,0,0,.45); }
  .rednum { position:absolute; top:2px; left:4px; font-size:11px; font-weight:700; line-height:1; color:white; text-shadow:0 1px 2px rgba(0,0,0,.8); pointer-events:none; }
  .resize-handle { position:absolute; right:-5px; bottom:-5px; width:10px; height:10px; border:1px solid white; background:var(--c); cursor:nwse-resize; padding:0; }
  .controls { height:44px; flex-shrink:0; display:flex; align-items:center; gap:6px; padding:0 8px; border-top:1px solid var(--border); }
  .iconbtn { width:28px; height:28px; display:inline-flex; align-items:center; justify-content:center; border:0; background:transparent; color:var(--fg-primary); border-radius:var(--radius); cursor:pointer; padding:0; flex-shrink:0; }
  .iconbtn:hover { background:var(--bg-hover); }
  .iconbtn svg { width:16px; height:16px; fill:currentColor; }
  .tstack { flex:1; min-width:60px; }
  .timeline-track { height:28px; position:relative; }
  .timeline { width:100%; height:28px; accent-color:var(--accent); margin:0; }
  .rangebar { z-index:2; position:absolute; inset:4px 0; cursor:crosshair; touch-action:none; user-select:none; }
  .timeline.trimming { opacity:0; }
  .timeline-track:has(.rangebar) { background:linear-gradient(var(--border-strong),var(--border-strong)) center / 100% 4px no-repeat; }
  .trim-time { max-width:64px; height:28px; font-size:11px; font-variant-numeric:tabular-nums; }
  .range-selection { position:absolute; inset:0 auto; border:1px solid var(--accent); background:color-mix(in srgb,var(--accent) 35%,transparent); pointer-events:none; border-radius:3px; }
  .spanbar { position:absolute; top:0; left:0; right:0; height:9px; touch-action:none; user-select:none; }
  .span { position:absolute; inset:0 auto; background:color-mix(in srgb,var(--c) 28%,transparent); border:1px solid var(--c); border-radius:2px; pointer-events:none; }
  .span.sel { background:color-mix(in srgb,var(--c) 60%,transparent); z-index:1; }
  .grip { position:absolute; top:1px; bottom:1px; width:3px; background:rgba(255,255,255,.92); border-radius:2px; }
  .grip.l { left:-1px; } .grip.r { right:-1px; }
  .grip.trim-handle { width:10px; padding:0; border:1px solid var(--accent); pointer-events:auto; cursor:ew-resize; touch-action:none; }
  .trim-handle.l { left:-5px; } .trim-handle.r { right:-5px; }
  .trim-handle:focus-visible { outline:2px solid white; outline-offset:2px; }
  .time { font-size:10px; color:var(--fg-secondary); font-variant-numeric:tabular-nums; white-space:nowrap; }
  .properties { width:220px; flex-shrink:0; display:flex; flex-direction:column; gap:12px; padding:14px; background:var(--bg-content); border-left:1px solid var(--border); overflow-y:auto; }
  .section { font-weight:700; color:var(--fg-primary); font-size:var(--text-base); }
  .fields { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
  .fields label { display:flex; flex-direction:column; gap:4px; min-width:0; color:var(--fg-secondary); font-size:var(--text-small); }
  input[type=number] { width:100%; min-width:0; background:var(--bg-field); color:var(--fg-primary); border:1px solid var(--border); border-radius:var(--radius); padding:4px 6px; }
  .strength { display:flex; flex-wrap:wrap; align-items:center; gap:6px; color:var(--fg-secondary); font-size:var(--text-small); }
  .strength span { margin-left:auto; font-variant-numeric:tabular-nums; }
  .strength input { width:100%; accent-color:var(--accent); }
  .blur-layers { display:flex; flex-direction:column; max-height:30vh; overflow:auto; gap:2px; }
  .blur-layer { display:flex; align-items:center; gap:4px; border-radius:var(--radius); }
  .chosen { background:var(--bg-hover); }
  .layer-select { flex:1; min-width:0; display:flex; justify-content:space-between; gap:6px; padding:7px 6px; border:0; background:transparent; color:var(--fg-primary); font-size:var(--text-small); text-align:left; cursor:pointer; }
  .layer-select span { color:var(--fg-secondary); font-size:10px; }
  .blur-layer.chosen .layer-select { color:var(--accent); }
  .del { display:inline-flex; align-items:center; justify-content:center; width:24px; height:24px; border:0; background:transparent; color:var(--fg-secondary); cursor:pointer; border-radius:var(--radius); }
  .del:hover { color:var(--danger); background:var(--bg-hover); }
  details { font-size:var(--text-small); color:var(--fg-secondary); }
  summary { cursor:pointer; }
  .geometry-fields { padding-top:8px; }
  .help { margin:0; font-size:var(--text-small); color:var(--fg-secondary); line-height:1.5; }
  .gif-dialog { display:flex; flex-direction:column; gap:12px; }
  .gif-head { display:flex; justify-content:space-between; align-items:center; font-weight:700; color:var(--fg-primary); }
  .grow { display:flex; align-items:center; flex-wrap:wrap; gap:6px; font-size:var(--text-small); color:var(--fg-secondary); }
  .grow input { flex:1; min-width:60px; accent-color:var(--accent); }
  .toggle { font-size:var(--text-small); color:var(--fg-secondary); display:flex; align-items:center; gap:6px; }
  .range-row { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
  .t { display:flex; flex-direction:column; gap:4px; font-size:var(--text-small); color:var(--fg-secondary); }
  .toast { position:absolute; bottom:52px; left:50%; transform:translateX(-50%); padding:8px 12px; background:var(--bg-content); border:1px solid var(--border); color:var(--fg-primary); border-radius:var(--radius); font-size:var(--text-small); z-index:5; }
  .toast.err { color:var(--danger); }

</style>
