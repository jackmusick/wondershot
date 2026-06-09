import type Konva from 'konva';
import type { Item } from '$lib/editor/model';
import type { DrawStyle } from '$lib/editor/style';

export interface DrawCtx {
  layer: Konva.Layer; // annotations layer to draw onto
  Konva: typeof Konva; // the loaded Konva module
  style: DrawStyle; // current color/width
  /** Fetch a processed patch PNG (data URL) for a region of the base image.
   *  kind 'pixelate' uses `param` as block size; 'blur' uses it as radius.
   *  Returns null if unavailable. Provided by the canvas (wraps the Tauri command). */
  patch?(kind: 'pixelate' | 'blur', rect: [number, number, number, number], param: number): Promise<string | null>;
}

/** A drawing tool: begins on pointerdown, updates on move, finishes on up.
 *  begin() creates an in-progress Konva node; update() mutates it; finish()
 *  returns the finished model Item (or null to discard a degenerate draw). */
export interface DrawTool {
  begin(ctx: DrawCtx, x: number, y: number): void;
  update(ctx: DrawCtx, x: number, y: number): void;
  finish(ctx: DrawCtx, x: number, y: number): Item | null;
  /** Recreate a Konva node from a saved Item (for undo/redo + load). */
  render(ctx: DrawCtx, item: Item): Konva.Node;
  /** Read a (possibly transformed) Konva node back into an updated model Item.
   *  MUST bake any Transformer scale into real geometry and reset scale to 1. */
  fromNode(ctx: DrawCtx, node: Konva.Node, prev: Item): Item;
}

export const drawTools: Partial<Record<string, DrawTool>> = {};
