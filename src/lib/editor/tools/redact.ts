import type Konva from 'konva';
import type { Item, PixelateItem, BlurItem, Vec2, Vec4 } from '$lib/editor/model';
import { type DrawCtx, type DrawTool, drawTools } from './index';
import { tagNode, WS_NODE_NAME } from './arrowLine';

/** A box is "degenerate" (zero area) within this pixel epsilon. */
const EPS = 1e-6;

/** Default pixelate block size + blur radius, matching the Python editor. */
const DEFAULT_BLOCK = 14;
const DEFAULT_RADIUS = 12;

/** Visual placeholder shown until (or instead of) the processed patch loads. */
const PLACEHOLDER_FILL = '#808080';
const PLACEHOLDER_OPACITY = 0.6;

function isDegenerate(rect: Vec4): boolean {
  return Math.abs(rect[2]) <= EPS || Math.abs(rect[3]) <= EPS;
}

/** Normalize a start→current drag into a positive-extent bounding box. */
function normalizeBox(start: Vec2, cur: Vec2): Vec4 {
  const x = Math.min(start[0], cur[0]);
  const y = Math.min(start[1], cur[1]);
  const w = Math.abs(cur[0] - start[0]);
  const h = Math.abs(cur[1] - start[1]);
  return [x, y, w, h];
}

/** Pure geometry→Item mapping for pixelate. Null for a zero-area box. */
export function pixelateItem(rect: Vec4, block = DEFAULT_BLOCK): PixelateItem | null {
  if (isDegenerate(rect)) return null;
  return {
    type: 'pixelate',
    rect: [rect[0], rect[1], rect[2], rect[3]],
    block,
    pos: [0, 0],
    rotation: 0,
    origin: [0, 0],
  };
}

/** Pure geometry→Item mapping for blur. Null for a zero-area box. */
export function blurItem(rect: Vec4, radius = DEFAULT_RADIUS): BlurItem | null {
  if (isDegenerate(rect)) return null;
  return {
    type: 'blur',
    rect: [rect[0], rect[1], rect[2], rect[3]],
    radius,
    pos: [0, 0],
    rotation: 0,
    origin: [0, 0],
  };
}

type RedactKind = 'pixelate' | 'blur';

/**
 * Build the redact node: a Konva.Rect placeholder (gray, semi-opaque) covering
 * the region. The processed patch (when it loads) is set as `fillPatternImage`,
 * which replaces the gray fill with the actual pixelated/blurred pixels. The
 * rect itself is the tagged top node.
 */
function makeRedactNode(ctx: DrawCtx, rect: Vec4): Konva.Rect {
  return new ctx.Konva.Rect({
    x: rect[0],
    y: rect[1],
    width: rect[2],
    height: rect[3],
    fill: PLACEHOLDER_FILL,
    opacity: PLACEHOLDER_OPACITY,
    name: WS_NODE_NAME,
    draggable: true,
  });
}

/** Round a rect's components to u32-compatible integers for the backend. */
function intRect(rect: Vec4): Vec4 {
  return [
    Math.max(0, Math.round(rect[0])),
    Math.max(0, Math.round(rect[1])),
    Math.max(1, Math.round(rect[2])),
    Math.max(1, Math.round(rect[3])),
  ];
}

/**
 * Kick off the async patch fetch for `node` covering `rect`, then swap the
 * gray placeholder for the processed patch when it resolves. The node's size
 * (not the requested rect) drives the fill pattern scale so the patch stretches
 * to fill the rect exactly. Guards against a node that has been destroyed (or
 * re-fetched for a newer rect) before the patch arrives: re-reads the node's
 * current size and bails if the node left the layer.
 */
function fillPatch(ctx: DrawCtx, node: Konva.Rect, kind: RedactKind, rect: Vec4, param: number): void {
  if (!ctx.patch) return; // no fetcher (e.g. unit tests) — keep the gray box
  const req = intRect(rect);
  const done = ctx
    .patch(kind, req, param)
    .then(
      (dataUrl) =>
        new Promise<void>((resolve) => {
          if (!dataUrl) return resolve(); // null → mock/error: keep the gray placeholder
          // The node may have been destroyed (deleted, undo) while we awaited.
          if (!node.getLayer()) return resolve();
          const img = new Image();
          img.onerror = () => {
            console.error(`${kind} patch image failed to decode`);
            resolve();
          };
          img.onload = () => {
            if (node.getLayer()) {
              node.fillPriority('pattern');
              node.fillPatternImage(img);
              node.fillPatternRepeat('no-repeat');
              // Stretch the (req.w × req.h) patch to cover the node's current box.
              node.fillPatternScaleX(node.width() / img.width);
              node.fillPatternScaleY(node.height() / img.height);
              node.opacity(1);
              node.getLayer()?.batchDraw();
            }
            resolve();
          };
          img.src = dataUrl;
        }),
    )
    .catch(() => {
      // Network/backend error: keep the gray placeholder, never throw.
    });
  // Let save/flatten wait for this fill so the placeholder is never baked.
  ctx.trackPending?.(done as Promise<void>);
}

/**
 * A redact (pixelate / blur) box tool. Like the box shapes it is drawn as a
 * box-drag and gets the full resize Transformer; UNLIKE them it displays a
 * processed raster patch of the base image (computed in Rust). The model item
 * is added synchronously on finish; the patch fills in asynchronously via
 * `ctx.patch`. If the fetch is unavailable or fails, the gray placeholder
 * stays. `fromNode` bakes the Transformer scale into `rect` (like box shapes)
 * and re-triggers a patch fetch for the new region.
 */
function makeRedactTool(kind: RedactKind): DrawTool {
  let start: Vec2 | null = null;
  let node: Konva.Rect | null = null;

  function toItem(rect: Vec4, param: number): PixelateItem | BlurItem | null {
    return kind === 'pixelate' ? pixelateItem(rect, param) : blurItem(rect, param);
  }

  function paramOf(item: PixelateItem | BlurItem): number {
    return item.type === 'pixelate' ? item.block : item.radius;
  }

  return {
    begin(ctx, x, y) {
      start = [x, y];
      node = makeRedactNode(ctx, [x, y, 0, 0]);
      ctx.layer.add(node);
      ctx.layer.batchDraw();
    },
    update(ctx, x, y) {
      if (!start || !node) return;
      const r = normalizeBox(start, [x, y]);
      node.x(r[0]);
      node.y(r[1]);
      node.width(r[2]);
      node.height(r[3]);
      ctx.layer.batchDraw();
    },
    finish(ctx, x, y) {
      const s = start;
      const n = node;
      start = null;
      node = null;
      if (!s) return null;
      const rect = normalizeBox(s, [x, y]);
      const param = kind === 'pixelate' ? DEFAULT_BLOCK : DEFAULT_RADIUS;
      const item = toItem(rect, param);
      if (!item) {
        n?.destroy();
        ctx.layer.batchDraw();
        return null;
      }
      if (n) {
        n.x(rect[0]);
        n.y(rect[1]);
        n.width(rect[2]);
        n.height(rect[3]);
        tagNode(n, item);
        ctx.layer.batchDraw();
        fillPatch(ctx, n, kind, rect, param);
      }
      return item;
    },
    render(ctx, item) {
      const it = item as PixelateItem | BlurItem;
      const n = makeRedactNode(ctx, it.rect);
      n.rotation(it.rotation ?? 0);
      tagNode(n, item);
      ctx.layer.add(n);
      fillPatch(ctx, n, kind, it.rect, paramOf(it));
      return n;
    },
    fromNode(ctx, node, prev) {
      // Bake the Transformer scale into the rect's real width/height (like box
      // shapes), reset scale to 1, then re-fetch the patch for the new region.
      const p = prev as PixelateItem | BlurItem;
      const sx = node.scaleX();
      const sy = node.scaleY();
      node.scaleX(1);
      node.scaleY(1);
      const rotation = node.rotation();

      const r = node as Konva.Rect;
      const w = r.width() * sx;
      const h = r.height() * sy;
      r.width(w);
      r.height(h);
      const rect: Vec4 = [r.x(), r.y(), w, h];

      // Reset to the gray placeholder while the new patch loads.
      r.fillPriority('color');
      r.fillPatternImage(undefined as unknown as HTMLImageElement);
      r.fill(PLACEHOLDER_FILL);
      r.opacity(PLACEHOLDER_OPACITY);

      const param = paramOf(p);
      const base = { rect, pos: [0, 0] as Vec2, rotation, origin: [0, 0] as Vec2 };
      const updated: Item =
        p.type === 'pixelate'
          ? { type: 'pixelate', block: p.block, ...base }
          : { type: 'blur', radius: p.radius, ...base };

      tagNode(node, updated);
      fillPatch(ctx, r, kind, rect, param);
      return updated;
    },
  };
}

export const pixelateTool: DrawTool = makeRedactTool('pixelate');
export const blurTool: DrawTool = makeRedactTool('blur');

drawTools.pixelate = pixelateTool;
drawTools.blur = blurTool;
