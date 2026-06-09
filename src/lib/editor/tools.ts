import { writable } from 'svelte/store';

export type ToolId =
  | 'select' | 'arrow' | 'line' | 'rect' | 'ellipse' | 'freehand'
  | 'highlight' | 'text' | 'step' | 'pixelate' | 'blur'
  | 'crop' | 'cutout-v' | 'cutout-h';

export const SHORTCUTS: Record<string, ToolId> = {
  v: 'select', a: 'arrow', l: 'line', r: 'rect', e: 'ellipse', p: 'freehand',
  h: 'highlight', t: 'text', n: 'step', x: 'pixelate', b: 'blur',
  c: 'crop', u: 'cutout-v', U: 'cutout-h', // shift+u
};

export const activeTool = writable<ToolId>('select');

/** Resolve a keyboard event to a tool id, honoring shift for cutout-h. */
export function toolForKey(key: string, shift: boolean): ToolId | null {
  if (shift && (key === 'u' || key === 'U')) return 'cutout-h';
  return SHORTCUTS[key.toLowerCase()] ?? null;
}
