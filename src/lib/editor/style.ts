import { writable } from 'svelte/store';

export interface DrawStyle {
  color: string;
  width: number;
}

export const drawStyle = writable<DrawStyle>({ color: '#ff3b30ff', width: 4 });

export type TextAlign = 'left' | 'center' | 'right';

export interface TextStyle {
  point_size: number;
  align: TextAlign;
}

/** Text defaults driven by the toolbar's font-size + align controls (shown
 *  only when the text tool is active). The text tool reads these when placing
 *  a new text annotation. */
export const textStyle = writable<TextStyle>({ point_size: 24, align: 'left' });

/** Normalize a color input to an 8-digit (#rrggbbaa) hex string. A native
 *  <input type="color"> yields 6-digit #rrggbb; we append 'ff' (opaque) so the
 *  stored color always carries an alpha channel. Already-8-digit values pass
 *  through unchanged. */
export function normalizeColor(value: string): string {
  if (/^#[0-9a-fA-F]{6}$/.test(value)) return `${value}ff`;
  return value;
}
