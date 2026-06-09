import { describe, it, expect } from 'vitest';
import { textItem } from '$lib/editor/tools/text';
import { serializeItem } from '$lib/editor/model';

describe('text tool', () => {
  it('produces exact JSON with defaults', () => {
    expect(serializeItem(textItem('hi', [10, 20], { color: '#ffffffff' })!)).toEqual({
      type: 'text',
      text: 'hi',
      color: '#ffffffff',
      family: 'sans-serif',
      point_size: 24,
      bold: true,
      text_width: -1,
      align: 'left',
      pos: [10, 20],
      rotation: 0,
      origin: [0, 0],
    });
  });
  it('honors overrides', () => {
    expect(
      serializeItem(
        textItem('x', [0, 0], {
          color: '#000000ff',
          family: 'Mono',
          point_size: 18,
          bold: false,
          text_width: 200,
          align: 'center',
        })!,
      ),
    ).toEqual({
      type: 'text',
      text: 'x',
      color: '#000000ff',
      family: 'Mono',
      point_size: 18,
      bold: false,
      text_width: 200,
      align: 'center',
      pos: [0, 0],
      rotation: 0,
      origin: [0, 0],
    });
  });
  it('empty text is null', () => {
    expect(textItem('   ', [0, 0], { color: '#fff' })).toBeNull();
  });
});
