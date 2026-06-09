//! Frontend editor item model — serialize/deserialize with exact Python
//! `items.py` `to_dict()`/`from_dict()` JSON parity, mirroring the Rust serde
//! models in `crates/wondershot-core/src/editor.rs`.
//!
//! The serialized shape MUST match the Python app byte-for-key so the
//! `.wondershot` sidecar interchanges between the Python app, the Rust core,
//! and this frontend.

export type Vec2 = [number, number];
export type Vec4 = [number, number, number, number];

/** Shared transform fields present on every item. */
export interface Transform {
  pos: Vec2;
  rotation: number;
  origin: Vec2;
}

export interface ArrowItem extends Transform {
  type: 'arrow';
  p1: Vec2;
  p2: Vec2;
  color: string;
  width: number;
}

export interface LineItem extends Transform {
  type: 'line';
  p1: Vec2;
  p2: Vec2;
  color: string;
  width: number;
}

export interface RectItem extends Transform {
  type: 'rect';
  rect: Vec4;
  color: string;
  width: number;
  /** Omitted from JSON when absent. */
  fill?: string;
}

export interface EllipseItem extends Transform {
  type: 'ellipse';
  rect: Vec4;
  color: string;
  width: number;
}

export interface HighlightItem extends Transform {
  type: 'highlight';
  rect: Vec4;
  color: string;
}

export interface FreehandItem extends Transform {
  type: 'freehand';
  points: Vec2[];
  color: string;
  width: number;
}

export interface TextItem extends Transform {
  type: 'text';
  text: string;
  color: string;
  family: string;
  point_size: number;
  bold: boolean;
  text_width: number;
  align: string;
}

export interface StepItem extends Transform {
  type: 'step';
  number: number;
  color: string;
  radius: number;
}

export interface PixelateItem extends Transform {
  type: 'pixelate';
  rect: Vec4;
  block: number;
}

export interface BlurItem extends Transform {
  type: 'blur';
  rect: Vec4;
  radius: number;
}

export type Item =
  | ArrowItem
  | LineItem
  | RectItem
  | EllipseItem
  | HighlightItem
  | FreehandItem
  | TextItem
  | StepItem
  | PixelateItem
  | BlurItem;

const ITEM_TYPES = new Set([
  'arrow',
  'line',
  'rect',
  'ellipse',
  'highlight',
  'freehand',
  'text',
  'step',
  'pixelate',
  'blur',
]);

/** Spread the shared transform fields, in the same order Python emits them. */
function transformFields(item: Transform): Record<string, unknown> {
  return { pos: item.pos, rotation: item.rotation, origin: item.origin };
}

/**
 * Serialize a typed item to its canonical JSON object (the per-type fields,
 * then the spread transform). Matches Python `to_dict()` exactly — notably,
 * `fill` is omitted for rects when absent.
 */
export function serializeItem(item: Item): Record<string, unknown> {
  switch (item.type) {
    case 'arrow':
      return {
        type: 'arrow',
        p1: item.p1,
        p2: item.p2,
        color: item.color,
        width: item.width,
        ...transformFields(item),
      };
    case 'line':
      return {
        type: 'line',
        p1: item.p1,
        p2: item.p2,
        color: item.color,
        width: item.width,
        ...transformFields(item),
      };
    case 'rect': {
      const d: Record<string, unknown> = {
        type: 'rect',
        rect: item.rect,
        color: item.color,
        width: item.width,
        ...transformFields(item),
      };
      if (item.fill !== undefined) d.fill = item.fill;
      return d;
    }
    case 'ellipse':
      return {
        type: 'ellipse',
        rect: item.rect,
        color: item.color,
        width: item.width,
        ...transformFields(item),
      };
    case 'highlight':
      return {
        type: 'highlight',
        rect: item.rect,
        color: item.color,
        ...transformFields(item),
      };
    case 'freehand':
      return {
        type: 'freehand',
        points: item.points,
        color: item.color,
        width: item.width,
        ...transformFields(item),
      };
    case 'text':
      return {
        type: 'text',
        text: item.text,
        color: item.color,
        family: item.family,
        point_size: item.point_size,
        bold: item.bold,
        text_width: item.text_width,
        align: item.align,
        ...transformFields(item),
      };
    case 'step':
      return {
        type: 'step',
        number: item.number,
        color: item.color,
        radius: item.radius,
        ...transformFields(item),
      };
    case 'pixelate':
      return {
        type: 'pixelate',
        rect: item.rect,
        block: item.block,
        ...transformFields(item),
      };
    case 'blur':
      return {
        type: 'blur',
        rect: item.rect,
        radius: item.radius,
        ...transformFields(item),
      };
  }
}

/** Pull the shared transform fields out of a raw JSON object. */
function readTransform(d: Record<string, any>): Transform {
  const pos = d.pos ?? [0, 0];
  const origin = d.origin ?? [0, 0];
  return {
    pos: [pos[0], pos[1]],
    rotation: d.rotation ?? 0,
    origin: [origin[0], origin[1]],
  };
}

/**
 * Rebuild a typed item from its serialized JSON. Returns `null` for unknown
 * types, mirroring Python `item_from_dict` (the editor skips future types
 * rather than crashing).
 */
export function deserializeItem(json: Record<string, any>): Item | null {
  const t = json?.type;
  if (!ITEM_TYPES.has(t)) return null;
  const tf = readTransform(json);
  switch (t) {
    case 'arrow':
      return {
        type: 'arrow',
        p1: [json.p1[0], json.p1[1]],
        p2: [json.p2[0], json.p2[1]],
        color: json.color,
        width: json.width,
        ...tf,
      };
    case 'line':
      return {
        type: 'line',
        p1: [json.p1[0], json.p1[1]],
        p2: [json.p2[0], json.p2[1]],
        color: json.color,
        width: json.width,
        ...tf,
      };
    case 'rect': {
      const item: RectItem = {
        type: 'rect',
        rect: [json.rect[0], json.rect[1], json.rect[2], json.rect[3]],
        color: json.color,
        width: json.width,
        ...tf,
      };
      if (json.fill !== undefined && json.fill !== null) item.fill = json.fill;
      return item;
    }
    case 'ellipse':
      return {
        type: 'ellipse',
        rect: [json.rect[0], json.rect[1], json.rect[2], json.rect[3]],
        color: json.color,
        width: json.width,
        ...tf,
      };
    case 'highlight':
      return {
        type: 'highlight',
        rect: [json.rect[0], json.rect[1], json.rect[2], json.rect[3]],
        color: json.color,
        ...tf,
      };
    case 'freehand':
      return {
        type: 'freehand',
        points: json.points.map((p: number[]) => [p[0], p[1]] as Vec2),
        color: json.color,
        width: json.width,
        ...tf,
      };
    case 'text':
      return {
        type: 'text',
        text: json.text,
        color: json.color,
        family: json.family,
        point_size: json.point_size,
        bold: json.bold,
        text_width: json.text_width,
        align: json.align,
        ...tf,
      };
    case 'step':
      return {
        type: 'step',
        number: json.number,
        color: json.color,
        radius: json.radius,
        ...tf,
      };
    case 'pixelate':
      return {
        type: 'pixelate',
        rect: [json.rect[0], json.rect[1], json.rect[2], json.rect[3]],
        block: json.block,
        ...tf,
      };
    case 'blur':
      return {
        type: 'blur',
        rect: [json.rect[0], json.rect[1], json.rect[2], json.rect[3]],
        radius: json.radius,
        ...tf,
      };
    default:
      return null;
  }
}
