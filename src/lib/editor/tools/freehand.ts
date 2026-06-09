import type Konva from 'konva';
import type { FreehandItem, Vec2 } from '$lib/editor/model';
import type { DrawStyle } from '$lib/editor/style';
import { type DrawCtx, type DrawTool, drawTools } from './index';
import { tagNode, nodeToItemRef, WS_NODE_NAME } from './arrowLine';

/**
 * Pure geometry→Item mapping for freehand strokes. Returns null if fewer
 * than 2 points (degenerate draw).
 */
export function freehandItem(
  points: Vec2[],
  style: DrawStyle,
): FreehandItem | null {
  if (points.length < 2) return null;
  return {
    type: 'freehand',
    points: points.map((p) => [p[0], p[1]]),
    color: style.color,
    width: style.width,
    pos: [0, 0],
    rotation: 0,
    origin: [0, 0],
  };
}

/**
 * Pure drag-translation for freehand items. Adds the drag delta (dx,dy) to
 * every point and returns an updated item with identity transform
 * (pos/rotation/origin), matching how `freehandItem` keeps geometry in points.
 * Unit-tested; `fromNode` delegates here.
 */
export function translatePoints(
  item: FreehandItem,
  dx: number,
  dy: number,
): FreehandItem {
  return {
    ...item,
    points: item.points.map((p) => [p[0] + dx, p[1] + dy]),
    pos: [0, 0],
    rotation: 0,
    origin: [0, 0],
  };
}

/**
 * A freehand (pen) drawing tool. The in-progress node lives on the
 * annotations layer; begin() creates it, update() appends points, finish()
 * returns the model Item (or destroys the node + returns null for a
 * degenerate draw).
 */
const freehandTool: DrawTool = {
  begin(ctx, x, y) {
    const node = new ctx.Konva.Line({
      points: [x, y],
      stroke: ctx.style.color,
      strokeWidth: ctx.style.width,
      lineCap: 'round',
      lineJoin: 'round',
      hitStrokeWidth: Math.max(10, ctx.style.width),
      name: WS_NODE_NAME,
      draggable: true,
    });
    ctx.layer.add(node);
    ctx.layer.batchDraw();
    // Store the node and running points in the tool state via an attribute
    // so that update() and finish() can access them.
    node.setAttr('_freehandPoints', [x, y]);
    node.setAttr('_freehandNode', node);
  },

  update(ctx, x, y) {
    // Find the in-progress freehand node by looking for one with _freehandPoints
    const nodes = ctx.layer.find('.' + WS_NODE_NAME);
    let node: Konva.Line | null = null;
    let pointsFlat: number[] = [];

    for (const n of nodes) {
      const points = n.getAttr('_freehandPoints');
      if (points) {
        node = n as Konva.Line;
        pointsFlat = points;
        break;
      }
    }

    if (!node || !pointsFlat) return;

    // Append the new point to the running array
    pointsFlat.push(x, y);
    node.setAttr('_freehandPoints', pointsFlat);

    // Update the Konva line points (already in flattened [x1,y1,x2,y2,...] format)
    node.points(pointsFlat);
    ctx.layer.batchDraw();
  },

  finish(ctx, x, y) {
    // Find the in-progress node and collect all its points
    const nodes = ctx.layer.find('.' + WS_NODE_NAME);
    let node: Konva.Line | null = null;
    let pointsFlat: number[] = [];

    for (const n of nodes) {
      const points = n.getAttr('_freehandPoints');
      if (points) {
        node = n as Konva.Line;
        pointsFlat = points;
        break;
      }
    }

    if (!node) return null;

    // Clean up the temporary attributes
    node.setAttr('_freehandPoints', undefined);
    node.setAttr('_freehandNode', undefined);

    // Convert flattened array back to Vec2[]
    const points: Vec2[] = [];
    for (let i = 0; i < pointsFlat.length; i += 2) {
      points.push([pointsFlat[i], pointsFlat[i + 1]]);
    }

    // Append the final point
    points.push([x, y]);

    // Build the item; null if degenerate
    const item = freehandItem(points, ctx.style);
    if (!item) {
      node.destroy();
      ctx.layer.batchDraw();
      return null;
    }

    // Update the final node with the complete points and tag it
    node.points([...pointsFlat, x, y]);
    tagNode(node, item);
    ctx.layer.batchDraw();

    return item;
  },

  render(ctx, item) {
    const a = item as FreehandItem;
    // Flatten points for Konva
    const pointsFlat: number[] = [];
    for (const p of a.points) {
      pointsFlat.push(p[0], p[1]);
    }

    const node = new ctx.Konva.Line({
      points: pointsFlat,
      stroke: a.color,
      strokeWidth: a.width,
      lineCap: 'round',
      lineJoin: 'round',
      hitStrokeWidth: Math.max(10, a.width),
      name: WS_NODE_NAME,
      draggable: true,
    });
    tagNode(node, item);
    ctx.layer.add(node);
    return node;
  },

  fromNode(_ctx, node, prev) {
    // Freehand items are edited by dragging the whole node; bake the drag
    // offset (node.x/y) into every point, then reset the node position so
    // its points stay in absolute image coords and subsequent drags compound
    // from zero.
    const dx = node.x();
    const dy = node.y();
    const updated = translatePoints(prev as FreehandItem, dx, dy);

    const shape = node as Konva.Line;
    shape.position({ x: 0, y: 0 });
    shape.scale({ x: 1, y: 1 });
    shape.rotation(0);

    // Flatten the updated points and set them on the node
    const pointsFlat: number[] = [];
    for (const p of updated.points) {
      pointsFlat.push(p[0], p[1]);
    }
    shape.points(pointsFlat);

    return updated;
  },
};

drawTools.freehand = freehandTool;
