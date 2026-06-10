import type Konva from 'konva';
import type { Item, ArrowItem, LineItem, Vec2 } from '$lib/editor/model';
import type { DrawStyle } from '$lib/editor/style';
import { type DrawCtx, type DrawTool, drawTools } from './index';

/** Two points are "the same" (degenerate draw) within this pixel epsilon. */
const EPS = 1e-6;

function isZeroLength(p1: Vec2, p2: Vec2): boolean {
  return Math.abs(p1[0] - p2[0]) <= EPS && Math.abs(p1[1] - p2[1]) <= EPS;
}

/** Pure geometry→Item mapping for arrows. Returns null for a zero-length draw. */
export function arrowItem(p1: Vec2, p2: Vec2, style: DrawStyle): ArrowItem | null {
  if (isZeroLength(p1, p2)) return null;
  return {
    type: 'arrow',
    p1: [p1[0], p1[1]],
    p2: [p2[0], p2[1]],
    color: style.color,
    width: style.width,
    pos: [0, 0],
    rotation: 0,
    origin: [0, 0],
  };
}

/**
 * Pure drag-translation readback for two-point items (arrow/line). Adds the
 * drag delta (dx,dy) to both endpoints and returns an updated item with
 * identity transform (pos/rotation/origin), matching how `arrowItem`/`lineItem`
 * keep geometry in p1/p2. Unit-tested; `fromNode` delegates here.
 */
export function translateTwoPoint<T extends ArrowItem | LineItem>(
  item: T,
  dx: number,
  dy: number,
): T {
  return {
    ...item,
    p1: [item.p1[0] + dx, item.p1[1] + dy],
    p2: [item.p2[0] + dx, item.p2[1] + dy],
    pos: [0, 0],
    rotation: 0,
    origin: [0, 0],
  };
}

/** Pure geometry→Item mapping for lines. Returns null for a zero-length draw. */
export function lineItem(p1: Vec2, p2: Vec2, style: DrawStyle): LineItem | null {
  if (isZeroLength(p1, p2)) return null;
  return {
    type: 'line',
    p1: [p1[0], p1[1]],
    p2: [p2[0], p2[1]],
    color: style.color,
    width: style.width,
    pos: [0, 0],
    rotation: 0,
    origin: [0, 0],
  };
}

/**
 * Tag a Konva node with the model Item it represents. The select tool and the
 * undo/redo rebuild use this to map nodes↔items. Every tool's begin()/render()
 * MUST call this so the linkage stays intact — later tools follow the same rule.
 */
export function tagNode(node: Konva.Node, item: Item): void {
  node.setAttr('wsItem', item);
}

/** Read the model Item a node was tagged with (or undefined if untagged). */
export function nodeToItemRef(node: Konva.Node): Item | undefined {
  return node.getAttr('wsItem') as Item | undefined;
}

/** Pointer head sizing derived from stroke width, matching the Python editor. */
function pointerSize(width: number): { length: number; size: number } {
  return { length: Math.max(8, width * 3), size: Math.max(8, width * 3) };
}

/** Shared marker so the rebuild can find/destroy only tool-created nodes. */
const WS_NODE = 'wsNode';

function makeArrowNode(ctx: DrawCtx, p1: Vec2, p2: Vec2, style: DrawStyle): Konva.Arrow {
  const ps = pointerSize(style.width);
  return new ctx.Konva.Arrow({
    points: [p1[0], p1[1], p2[0], p2[1]],
    stroke: style.color,
    fill: style.color,
    strokeWidth: style.width,
    pointerLength: ps.length,
    pointerWidth: ps.size,
    hitStrokeWidth: Math.max(10, style.width),
    name: WS_NODE,
    draggable: true,
  });
}

function makeLineNode(ctx: DrawCtx, p1: Vec2, p2: Vec2, style: DrawStyle): Konva.Line {
  return new ctx.Konva.Line({
    points: [p1[0], p1[1], p2[0], p2[1]],
    stroke: style.color,
    strokeWidth: style.width,
    lineCap: 'round',
    hitStrokeWidth: Math.max(10, style.width),
    name: WS_NODE,
    draggable: true,
  });
}

/**
 * A two-point drag tool (arrow or line). The in-progress node lives on the
 * annotations layer; begin() creates it, update() moves p2, finish() returns
 * the model Item (or destroys the node + returns null for a degenerate draw).
 */
function makeTwoPointTool(
  kind: 'arrow' | 'line',
  toItem: (p1: Vec2, p2: Vec2, style: DrawStyle) => ArrowItem | LineItem | null,
  makeNode: (ctx: DrawCtx, p1: Vec2, p2: Vec2, style: DrawStyle) => Konva.Shape,
): DrawTool {
  let start: Vec2 | null = null;
  let node: Konva.Shape | null = null;

  return {
    begin(ctx, x, y) {
      start = [x, y];
      node = makeNode(ctx, start, start, ctx.style);
      ctx.layer.add(node);
      ctx.layer.batchDraw();
    },
    update(ctx, x, y) {
      if (!start || !node) return;
      (node as Konva.Arrow | Konva.Line).points([start[0], start[1], x, y]);
      ctx.layer.batchDraw();
    },
    finish(ctx, x, y) {
      const s = start;
      const n = node;
      start = null;
      node = null;
      if (!s) return null;
      const item = toItem(s, [x, y], ctx.style);
      if (!item) {
        n?.destroy();
        ctx.layer.batchDraw();
        return null;
      }
      if (n) {
        (n as Konva.Arrow | Konva.Line).points([s[0], s[1], x, y]);
        tagNode(n, item);
        ctx.layer.batchDraw();
      }
      return item;
    },
    render(ctx, item) {
      const a = item as ArrowItem | LineItem;
      const n = makeNode(ctx, a.p1, a.p2, { color: a.color, width: a.width });
      tagNode(n, item);
      ctx.layer.add(n);
      return n;
    },
    fromNode(_ctx, node, prev) {
      // Two-point items are edited by dragging the whole node (offset lands in
      // node.x/y) OR by dragging an endpoint grip (rewrites points[] in place).
      // Read the LIVE points + offset so both kinds of edit persist, then
      // reset the node so its points stay in absolute image coords and
      // subsequent drags compound from zero. Any stray Transformer scale is
      // discarded (these nodes are not box-resizable).
      const shape = node as Konva.Arrow | Konva.Line;
      const pts = shape.points();
      const dx = shape.x();
      const dy = shape.y();
      const p = prev as ArrowItem | LineItem;
      const updated = {
        ...p,
        p1: [pts[0] + dx, pts[1] + dy] as Vec2,
        p2: [pts[2] + dx, pts[3] + dy] as Vec2,
        pos: [0, 0] as Vec2,
        rotation: 0,
        origin: [0, 0] as Vec2,
      };
      shape.position({ x: 0, y: 0 });
      shape.scale({ x: 1, y: 1 });
      shape.rotation(0);
      shape.points([updated.p1[0], updated.p1[1], updated.p2[0], updated.p2[1]]);
      return updated;
    },
  };
}

export const arrowTool: DrawTool = makeTwoPointTool('arrow', arrowItem, makeArrowNode);
export const lineTool: DrawTool = makeTwoPointTool('line', lineItem, makeLineNode);

drawTools.arrow = arrowTool;
drawTools.line = lineTool;

/** Name applied to every tool-created Konva node (for the rebuild sweep). */
export const WS_NODE_NAME = WS_NODE;
