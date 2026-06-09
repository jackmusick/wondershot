import { describe, it, expect } from 'vitest';
import { freehandItem, translatePoints } from '$lib/editor/tools/freehand';
import { serializeItem } from '$lib/editor/model';

describe('freehand tool', () => {
  it('produces exact JSON', () => {
    expect(
      serializeItem(
        freehandItem([[1, 2], [3, 4], [5, 6]], { color: '#000000ff', width: 2 })!,
      ),
    ).toEqual({
      type: 'freehand',
      points: [[1, 2], [3, 4], [5, 6]],
      color: '#000000ff',
      width: 2,
      pos: [0, 0],
      rotation: 0,
      origin: [0, 0],
    });
  });

  it('fewer than 2 points is null', () => {
    expect(freehandItem([[1, 2]], { color: '#fff', width: 2 })).toBeNull();
  });

  it('translatePoints shifts every point', () => {
    const moved = translatePoints(
      {
        type: 'freehand',
        points: [[0, 0], [10, 10]],
        color: '#fff',
        width: 2,
        pos: [0, 0],
        rotation: 0,
        origin: [0, 0],
      } as any,
      5,
      -5,
    );
    expect(serializeItem(moved).points).toEqual([[5, -5], [15, 5]]);
  });
});
