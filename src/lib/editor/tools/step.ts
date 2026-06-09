import type Konva from 'konva';
import type { Item, StepItem, Vec2 } from '$lib/editor/model';
import { type DrawCtx, type DrawTool, drawTools } from './index';
import { tagNode, WS_NODE_NAME } from './arrowLine';

/** Default badge radius (image pixels), matching the Python editor. */
const DEFAULT_RADIUS = 16;

/** White border + text color for the badge. */
const WHITE = '#ffffff';

/**
 * Font size for the centered number: bigger for single digits, smaller once the
 * number reaches double digits so it still fits inside the circle.
 */
function fontSizeFor(number: number, radius: number): number {
  return number < 10 ? radius * 0.85 : radius * 0.7;
}

/**
 * Pure builder for step items. Like text, a step carries its placement in
 * `pos:[x,y]` (the badge center) rather than normalizing into a rect. The
 * `number` is supplied by the caller (the canvas derives it from `items[]` via
 * `nextStepNumber`).
 */
export function stepItem(
  number: number,
  pos: Vec2,
  color: string,
  radius = DEFAULT_RADIUS,
): StepItem {
  return {
    type: 'step',
    number,
    color,
    radius,
    pos: [pos[0], pos[1]],
    rotation: 0,
    origin: [0, 0],
  };
}

/**
 * The next badge number, DERIVED from the current items each time:
 * `max(existing step numbers, 0) + 1`. Deriving (rather than keeping a separate
 * counter) makes undo/redo + load "just work" — after an undo removes a step,
 * the next stamp reuses that number, and on load the count picks up at max+1.
 */
export function nextStepNumber(items: Item[]): number {
  let max = 0;
  for (const it of items) {
    if (it.type === 'step' && it.number > max) max = it.number;
  }
  return max + 1;
}

/** Build the badge Konva.Group (circle + centered number) for a step item. */
function makeStepNode(ctx: DrawCtx, item: StepItem): Konva.Group {
  const group = new ctx.Konva.Group({
    x: item.pos[0],
    y: item.pos[1],
    rotation: item.rotation ?? 0,
    name: WS_NODE_NAME,
    draggable: true,
  });
  const circle = new ctx.Konva.Circle({
    x: 0,
    y: 0,
    radius: item.radius,
    fill: item.color,
    stroke: WHITE,
    strokeWidth: 2,
    name: 'ws-step-circle',
  });
  const fontSize = fontSizeFor(item.number, item.radius);
  const text = new ctx.Konva.Text({
    text: String(item.number),
    fill: WHITE,
    fontStyle: 'bold',
    fontSize,
    align: 'center',
    verticalAlign: 'middle',
    name: 'ws-step-text',
  });
  centerText(item, text);
  group.add(circle);
  group.add(text);
  return group;
}

/** Re-center the text within the circle by sizing it to the badge box and
 *  offsetting it so the circle center (group origin) is the box center. */
function centerText(item: StepItem, text: Konva.Text): void {
  const d = item.radius * 2;
  text.width(d);
  text.height(d);
  text.offsetX(item.radius);
  text.offsetY(item.radius);
}

/**
 * The step tool. Like text, a step is click-placed by EditorCanvas (which
 * derives the next number from items[] and calls `stepItem`), so begin/update/
 * finish are no-ops here. render() rebuilds the badge Group for undo/redo +
 * load; fromNode() reads the dragged position back into pos and bakes any
 * uniform Transformer scale into `radius`.
 *
 * Deferred for M3: drag-to-swap-numbers gesture (reordering badges by dragging
 * one onto another). Dragging only moves a badge; the transformer resizes it.
 */
const stepTool: DrawTool = {
  begin() {
    // no-op: step placement is handled by EditorCanvas on click.
  },
  update() {
    // no-op.
  },
  finish() {
    // no-op: the canvas stamps via stepItem() directly.
    return null;
  },
  render(ctx, item) {
    const n = makeStepNode(ctx, item as StepItem);
    tagNode(n, item);
    ctx.layer.add(n);
    return n;
  },
  fromNode(_ctx, node, prev) {
    // The badge uses the box Transformer for radius scaling. Bake a uniform
    // scale into radius and reset scale to 1; read the (dragged) node x/y back
    // into pos. Non-uniform scales are averaged so the badge stays circular.
    const p = prev as StepItem;
    const sx = node.scaleX();
    const sy = node.scaleY();
    const scale = (Math.abs(sx) + Math.abs(sy)) / 2;
    node.scaleX(1);
    node.scaleY(1);
    const radius = p.radius * scale;

    const group = node as Konva.Group;
    const circle = group.findOne<Konva.Circle>('.ws-step-circle');
    const text = group.findOne<Konva.Text>('.ws-step-text');

    const updated: StepItem = {
      ...p,
      radius,
      pos: [node.x(), node.y()],
      rotation: node.rotation(),
      origin: [0, 0],
    };

    if (circle) circle.radius(radius);
    if (text) {
      text.fontSize(fontSizeFor(updated.number, radius));
      centerText(updated, text);
    }

    tagNode(node, updated);
    return updated;
  },
};

drawTools.step = stepTool;

export { stepTool };
