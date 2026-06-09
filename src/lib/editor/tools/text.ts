import type Konva from 'konva';
import type { TextItem, Vec2 } from '$lib/editor/model';
import { type DrawCtx, type DrawTool, drawTools } from './index';
import { tagNode, WS_NODE_NAME } from './arrowLine';

export interface TextOpts {
  color: string;
  family?: string;
  point_size?: number;
  bold?: boolean;
  text_width?: number;
  align?: string;
}

/**
 * Pure builder for text items. Unlike the shape tools (which normalize geometry
 * into rect/points with pos:[0,0]), TEXT carries its placement in pos:[x,y].
 * Returns null when the trimmed text is empty so the canvas can discard an
 * abandoned placeholder. Defaults mirror the Python editor: sans-serif, 24pt,
 * bold, auto width (-1), left-aligned.
 */
export function textItem(text: string, pos: Vec2, opts: TextOpts): TextItem | null {
  if (text.trim() === '') return null;
  return {
    type: 'text',
    text,
    color: opts.color,
    family: opts.family ?? 'sans-serif',
    point_size: opts.point_size ?? 24,
    bold: opts.bold ?? true,
    text_width: opts.text_width ?? -1,
    align: opts.align ?? 'left',
    pos: [pos[0], pos[1]],
    rotation: 0,
    origin: [0, 0],
  };
}

/** Build a Konva.Text node for a text item. Shared by render() and the inline
 *  editor in EditorCanvas (which creates an empty placeholder, then commits). */
export function makeTextNode(ctx: DrawCtx, item: TextItem): Konva.Text {
  return new ctx.Konva.Text({
    x: item.pos[0],
    y: item.pos[1],
    text: item.text,
    fontSize: item.point_size,
    fontStyle: item.bold ? 'bold' : 'normal',
    fontFamily: item.family,
    fill: item.color,
    align: item.align,
    ...(item.text_width > 0 ? { width: item.text_width } : {}),
    rotation: item.rotation ?? 0,
    name: WS_NODE_NAME,
    draggable: true,
  });
}

/**
 * The text tool. Text is click-placed (not dragged to size), and editing
 * happens through an HTML <textarea> overlay owned by EditorCanvas — the tool
 * cannot own DOM cleanly. So begin/update/finish here are near-no-ops; the
 * canvas intercepts a text-tool click directly to spawn the editor. render()
 * rebuilds the Konva.Text for undo/redo + load; fromNode() reads node x/y back
 * into pos and bakes any uniform Transformer scale into point_size.
 *
 * Deferred for M3: drag-to-set-box-width (text_width stays -1/auto).
 */
const textTool: DrawTool = {
  begin() {
    // no-op: text placement + editing is handled by EditorCanvas on click.
  },
  update() {
    // no-op.
  },
  finish() {
    // The canvas opens the inline editor and commits via textItem() directly,
    // so the normal finish→append path is bypassed for text.
    return null;
  },
  render(ctx, item) {
    const n = makeTextNode(ctx, item as TextItem);
    tagNode(n, item);
    ctx.layer.add(n);
    return n;
  },
  fromNode(_ctx, node, prev) {
    // Text uses the box Transformer for font scaling. Bake a uniform scale into
    // point_size and reset scale to 1; read the (dragged) node x/y back into
    // pos. Non-uniform scales are averaged so the glyphs stay proportional.
    const p = prev as TextItem;
    const sx = node.scaleX();
    const sy = node.scaleY();
    const scale = (Math.abs(sx) + Math.abs(sy)) / 2;
    const t = node as Konva.Text;
    node.scaleX(1);
    node.scaleY(1);
    const point_size = p.point_size * scale;
    t.fontSize(point_size);
    const updated: TextItem = {
      ...p,
      point_size,
      pos: [node.x(), node.y()],
      rotation: node.rotation(),
      origin: [0, 0],
    };
    tagNode(node, updated);
    return updated;
  },
};

drawTools.text = textTool;

export { textTool };
