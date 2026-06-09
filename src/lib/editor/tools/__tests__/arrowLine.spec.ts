import { describe, it, expect } from 'vitest';
import { arrowItem, lineItem } from '$lib/editor/tools/arrowLine';
import { serializeItem } from '$lib/editor/model';

describe('arrow/line tools', () => {
  it('arrow finish produces exact JSON', () => {
    const it = arrowItem([10, 20], [110, 120], { color: '#ff3b30ff', width: 4 });
    expect(serializeItem(it!)).toEqual({
      type: 'arrow',
      p1: [10, 20],
      p2: [110, 120],
      color: '#ff3b30ff',
      width: 4,
      pos: [0, 0],
      rotation: 0,
      origin: [0, 0],
    });
  });
  it('line finish produces exact JSON', () => {
    const it = lineItem([0, 0], [50, 0], { color: '#00ff00ff', width: 2 });
    expect(serializeItem(it!)).toEqual({
      type: 'line',
      p1: [0, 0],
      p2: [50, 0],
      color: '#00ff00ff',
      width: 2,
      pos: [0, 0],
      rotation: 0,
      origin: [0, 0],
    });
  });
  it('zero-length arrow is discarded (null)', () => {
    expect(arrowItem([5, 5], [5, 5], { color: '#fff', width: 4 })).toBeNull();
  });
});
