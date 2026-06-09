import type Konva from 'konva';
import type { Item, RectItem, EllipseItem, HighlightItem, Vec2, Vec4 } from '$lib/editor/model';
import type { DrawStyle } from '$lib/editor/style';
import { type DrawCtx, type DrawTool, drawTools } from './index';
import { tagNode, WS_NODE_NAME } from './arrowLine';

/** A box is "degenerate" (zero area) within this pixel epsilon. */
const EPS = 1e-6;

/** Highlight fill opacity — Python uses alpha 90/255 ≈ 0.353. */
const HIGHLIGHT_OPACITY = 90 / 255;

function isDegenerate(rect: Vec4): boolean {
  return Math.abs(rect[2]) <= EPS || Math.abs(rect[3]) <= EPS;
}

/** Strip an 8-digit (#RRGGBBAA) color down to 6-digit (#RRGGBB). */
function to6Digit(color: string): string {
  if (color.length === 9 && color[0] === '#') return color.slice(0, 7);
  return color;
}

/** Pure geometry→Item mapping for rects. Null for a zero-area box. */
export function rectItem(rect: Vec4, style: DrawStyle, fill?: string): RectItem | null {
  if (isDegenerate(rect)) return null;
  return {
    type: 'rect',
    rect: [rect[0], rect[1], rect[2], rect[3]],
    color: style.color,
    width: style.width,
    ...(fill ? { fill } : {}),
    pos: [0, 0],
    rotation: 0,
    origin: [0, 0],
  };
}

/** Pure geometry→Item mapping for ellipses. Null for a zero-area box. */
export function ellipseItem(rect: Vec4, style: DrawStyle): EllipseItem | null {
  if (isDegenerate(rect)) return null;
  return {
    type: 'ellipse',
    rect: [rect[0], rect[1], rect[2], rect[3]],
    color: style.color,
    width: style.width,
    pos: [0, 0],
    rotation: 0,
    origin: [0, 0],
  };
}

/** Pure geometry→Item mapping for highlights. Null for a zero-area box. The
 *  color is stored 6-digit (#RRGGBB); any alpha is dropped (opacity is fixed). */
export function highlightItem(rect: Vec4, color6: string): HighlightItem | null {
  if (isDegenerate(rect)) return null;
  return {
    type: 'highlight',
    rect: [rect[0], rect[1], rect[2], rect[3]],
    color: to6Digit(color6),
    pos: [0, 0],
    rotation: 0,
    origin: [0, 0],
  };
}

/** Normalize a start→current drag into a positive-extent bounding box. */
function normalizeBox(start: Vec2, cur: Vec2): Vec4 {
  const x = Math.min(start[0], cur[0]);
  const y = Math.min(start[1], cur[1]);
  const w = Math.abs(cur[0] - start[0]);
  const h = Math.abs(cur[1] - start[1]);
  return [x, y, w, h];
}

// --- Konva node builders ---

function makeRectNode(ctx: DrawCtx, rect: Vec4, color: string, width: number, fill?: string): Konva.Rect {
  return new ctx.Konva.Rect({
    x: rect[0],
    y: rect[1],
    width: rect[2],
    height: rect[3],
    stroke: color,
    strokeWidth: width,
    ...(fill ? { fill } : {}),
    hitStrokeWidth: Math.max(10, width),
    name: WS_NODE_NAME,
    draggable: true,
  });
}

function makeEllipseNode(ctx: DrawCtx, rect: Vec4, color: string, width: number): Konva.Ellipse {
  return new ctx.Konva.Ellipse({
    x: rect[0] + rect[2] / 2,
    y: rect[1] + rect[3] / 2,
    radiusX: rect[2] / 2,
    radiusY: rect[3] / 2,
    stroke: color,
    strokeWidth: width,
    hitStrokeWidth: Math.max(10, width),
    name: WS_NODE_NAME,
    draggable: true,
  });
}

function makeHighlightNode(ctx: DrawCtx, rect: Vec4, color6: string): Konva.Rect {
  return new ctx.Konva.Rect({
    x: rect[0],
    y: rect[1],
    width: rect[2],
    height: rect[3],
    fill: color6,
    opacity: HIGHLIGHT_OPACITY,
    globalCompositeOperation: 'multiply',
    name: WS_NODE_NAME,
    draggable: true,
  });
}

type BoxKind = 'rect' | 'ellipse' | 'highlight';

/**
 * A box-shape drag tool (rect / ellipse / highlight). begin() records the start
 * point and drops an in-progress node; update() resizes the bounding box;
 * finish() returns the model Item (or destroys the node + returns null for a
 * zero-area draw). Unlike arrow/line, these get the full box Transformer in the
 * editor, so `fromNode` bakes the Transformer scale into real geometry.
 */
function makeBoxTool(kind: BoxKind): DrawTool {
  let start: Vec2 | null = null;
  let node: Konva.Rect | Konva.Ellipse | null = null;

  function build(ctx: DrawCtx, rect: Vec4): Konva.Rect | Konva.Ellipse {
    if (kind === 'rect') return makeRectNode(ctx, rect, ctx.style.color, ctx.style.width);
    if (kind === 'ellipse') return makeEllipseNode(ctx, rect, ctx.style.color, ctx.style.width);
    return makeHighlightNode(ctx, rect, to6Digit(ctx.style.color));
  }

  /** Resize an existing in-progress node to a new bounding box. */
  function resize(n: Konva.Rect | Konva.Ellipse, rect: Vec4): void {
    if (kind === 'ellipse') {
      const e = n as Konva.Ellipse;
      e.x(rect[0] + rect[2] / 2);
      e.y(rect[1] + rect[3] / 2);
      e.radiusX(rect[2] / 2);
      e.radiusY(rect[3] / 2);
    } else {
      const r = n as Konva.Rect;
      r.x(rect[0]);
      r.y(rect[1]);
      r.width(rect[2]);
      r.height(rect[3]);
    }
  }

  function toItem(rect: Vec4, style: DrawStyle): Item | null {
    if (kind === 'rect') return rectItem(rect, style);
    if (kind === 'ellipse') return ellipseItem(rect, style);
    return highlightItem(rect, to6Digit(style.color));
  }

  return {
    begin(ctx, x, y) {
      start = [x, y];
      node = build(ctx, [x, y, 0, 0]);
      ctx.layer.add(node);
      ctx.layer.batchDraw();
    },
    update(ctx, x, y) {
      if (!start || !node) return;
      resize(node, normalizeBox(start, [x, y]));
      ctx.layer.batchDraw();
    },
    finish(ctx, x, y) {
      const s = start;
      const n = node;
      start = null;
      node = null;
      if (!s) return null;
      const rect = normalizeBox(s, [x, y]);
      const item = toItem(rect, ctx.style);
      if (!item) {
        n?.destroy();
        ctx.layer.batchDraw();
        return null;
      }
      if (n) {
        resize(n, rect);
        tagNode(n, item);
        ctx.layer.batchDraw();
      }
      return item;
    },
    render(ctx, item) {
      let n: Konva.Rect | Konva.Ellipse;
      if (item.type === 'rect') {
        const r = item as RectItem;
        n = makeRectNode(ctx, r.rect, r.color, r.width, r.fill);
      } else if (item.type === 'ellipse') {
        const e = item as EllipseItem;
        n = makeEllipseNode(ctx, e.rect, e.color, e.width);
      } else {
        const h = item as HighlightItem;
        n = makeHighlightNode(ctx, h.rect, h.color);
      }
      n.rotation((item as RectItem).rotation ?? 0);
      tagNode(n, item);
      ctx.layer.add(n);
      return n;
    },
    fromNode(_ctx, node, prev) {
      // Bake any Transformer scale into real geometry, then reset scale to 1 so
      // subsequent transforms compound from the new baseline. Geometry lives in
      // the item's `rect` (bounding box), matching the builders' pos:[0,0]
      // convention. Rotation is read back into the item's `rotation` field.
      const sx = node.scaleX();
      const sy = node.scaleY();
      node.scaleX(1);
      node.scaleY(1);
      const rotation = node.rotation();

      let rect: Vec4;
      if (prev.type === 'ellipse') {
        const e = node as Konva.Ellipse;
        const rx = e.radiusX() * sx;
        const ry = e.radiusY() * sy;
        // Persist the baked radii so render↔fromNode round-trips stay stable.
        e.radiusX(rx);
        e.radiusY(ry);
        const cx = e.x();
        const cy = e.y();
        rect = [cx - rx, cy - ry, 2 * rx, 2 * ry];
      } else {
        const r = node as Konva.Rect;
        const w = r.width() * sx;
        const h = r.height() * sy;
        r.width(w);
        r.height(h);
        rect = [r.x(), r.y(), w, h];
      }

      const base = { rect, pos: [0, 0] as Vec2, rotation, origin: [0, 0] as Vec2 };
      let updated: Item;
      if (prev.type === 'rect') {
        const p = prev as RectItem;
        updated = { type: 'rect', color: p.color, width: p.width, ...(p.fill ? { fill: p.fill } : {}), ...base };
      } else if (prev.type === 'ellipse') {
        const p = prev as EllipseItem;
        updated = { type: 'ellipse', color: p.color, width: p.width, ...base };
      } else {
        const p = prev as HighlightItem;
        updated = { type: 'highlight', color: p.color, ...base };
      }
      tagNode(node, updated);
      return updated;
    },
  };
}

export const rectTool: DrawTool = makeBoxTool('rect');
export const ellipseTool: DrawTool = makeBoxTool('ellipse');
export const highlightTool: DrawTool = makeBoxTool('highlight');

drawTools.rect = rectTool;
drawTools.ellipse = ellipseTool;
drawTools.highlight = highlightTool;
