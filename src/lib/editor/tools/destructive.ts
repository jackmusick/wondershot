//! Destructive base-image operations: crop, cutout-vertical, cutout-horizontal.
//!
//! Unlike the annotation DrawTools, these don't add items. They flatten the
//! canvas (bake annotations into the base), transform the base image, clear
//! all annotations, and are undoable. The editor's undo history snapshots BOTH
//! the base image (as a data URL) and the items[] — see EditorSnapshot.
//!
//! Python parity:
//!   - crop:    flatten, then crop to the drawn rect.
//!   - cutoutV: remove a full-height vertical band [x1,x2), join left+right.
//!   - cutoutH: remove a full-width horizontal band [y1,y2), join top+bottom.
//! Each op records a "base push" (the pre-op flattened image) for the sidecar
//! base stack persisted at save time.
//!
//! This module holds the PURE index/dimension math (unit-tested) plus the
//! canvas-based pixel ops (driven by EditorCanvas, not directly testable).

export type Rect4 = [number, number, number, number];

/** New base dimensions after cropping to `rect` ([x, y, w, h]). */
export function cropDims(_baseW: number, _baseH: number, rect: Rect4): [number, number] {
  return [rect[2], rect[3]];
}

/**
 * New base dimensions after removing the band [a, b) along `axis`.
 *   axis 'v' removes a vertical band → width shrinks by (b - a).
 *   axis 'h' removes a horizontal band → height shrinks by (b - a).
 */
export function cutoutDims(
  baseW: number,
  baseH: number,
  a: number,
  b: number,
  axis: 'v' | 'h',
): [number, number] {
  const band = b - a;
  if (axis === 'v') return [baseW - band, baseH];
  return [baseW, baseH - band];
}

/**
 * Crop a source canvas/image to `rect` ([x, y, w, h]), returning a new canvas
 * sized exactly to the rect. The caller turns it into a data URL.
 */
export function cropCanvas(
  src: CanvasImageSource,
  rect: Rect4,
): HTMLCanvasElement {
  const [x, y, w, h] = rect;
  const out = document.createElement('canvas');
  out.width = w;
  out.height = h;
  const ctx = out.getContext('2d')!;
  ctx.drawImage(src, x, y, w, h, 0, 0, w, h);
  return out;
}

/**
 * Remove a vertical band [x1, x2) from `src` (natural size baseW×baseH),
 * joining the left part [0,x1) to the right part [x2,baseW). Returns a new
 * canvas of width (baseW - (x2-x1)), height baseH.
 */
export function cutoutVCanvas(
  src: CanvasImageSource,
  baseW: number,
  baseH: number,
  x1: number,
  x2: number,
): HTMLCanvasElement {
  const [w, h] = cutoutDims(baseW, baseH, x1, x2, 'v');
  const out = document.createElement('canvas');
  out.width = w;
  out.height = h;
  const ctx = out.getContext('2d')!;
  // Left part [0, x1)
  if (x1 > 0) ctx.drawImage(src, 0, 0, x1, baseH, 0, 0, x1, baseH);
  // Right part [x2, baseW) shifted left by the band width.
  const rightW = baseW - x2;
  if (rightW > 0) ctx.drawImage(src, x2, 0, rightW, baseH, x1, 0, rightW, baseH);
  return out;
}

/**
 * Remove a horizontal band [y1, y2) from `src`, joining top [0,y1) to bottom
 * [y2,baseH). Returns a new canvas of width baseW, height (baseH - (y2-y1)).
 */
export function cutoutHCanvas(
  src: CanvasImageSource,
  baseW: number,
  baseH: number,
  y1: number,
  y2: number,
): HTMLCanvasElement {
  const [w, h] = cutoutDims(baseW, baseH, y1, y2, 'h');
  const out = document.createElement('canvas');
  out.width = w;
  out.height = h;
  const ctx = out.getContext('2d')!;
  // Top part [0, y1)
  if (y1 > 0) ctx.drawImage(src, 0, 0, baseW, y1, 0, 0, baseW, y1);
  // Bottom part [y2, baseH) shifted up by the band height.
  const botH = baseH - y2;
  if (botH > 0) ctx.drawImage(src, 0, y2, baseW, botH, 0, y1, baseW, botH);
  return out;
}
