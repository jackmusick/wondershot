import { describe, it, expect } from 'vitest';
import { translateTwoPoint } from '$lib/editor/tools/arrowLine';
import { serializeItem } from '$lib/editor/model';
import type { ArrowItem, LineItem } from '$lib/editor/model';

const arrow: ArrowItem = {
  type: 'arrow',
  p1: [10, 20],
  p2: [110, 120],
  color: '#fff',
  width: 4,
  pos: [0, 0],
  rotation: 0,
  origin: [0, 0],
};

const line: LineItem = {
  type: 'line',
  p1: [0, 0],
  p2: [50, 0],
  color: '#0f0',
  width: 2,
  pos: [0, 0],
  rotation: 0,
  origin: [0, 0],
};

describe('translateTwoPoint (drag readback)', () => {
  it('moves an arrow by a positive/negative delta', () => {
    const moved = translateTwoPoint(arrow, 5, -5);
    expect(serializeItem(moved)).toMatchObject({ p1: [15, 15], p2: [115, 115] });
  });

  it('moves a line by a negative delta', () => {
    const moved = translateTwoPoint(line, -10, -3);
    expect(serializeItem(moved)).toMatchObject({ p1: [-10, -3], p2: [40, -3] });
  });

  it('preserves color/width and normalizes the transform to identity', () => {
    const moved = translateTwoPoint(arrow, 100, 200);
    expect(serializeItem(moved)).toEqual({
      type: 'arrow',
      p1: [110, 220],
      p2: [210, 320],
      color: '#fff',
      width: 4,
      pos: [0, 0],
      rotation: 0,
      origin: [0, 0],
    });
  });

  it('does not mutate the input item', () => {
    translateTwoPoint(arrow, 7, 7);
    expect(arrow.p1).toEqual([10, 20]);
    expect(arrow.p2).toEqual([110, 120]);
  });
});
