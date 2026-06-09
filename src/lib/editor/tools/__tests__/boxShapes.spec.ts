import { describe, it, expect } from 'vitest';
import { rectItem, ellipseItem, highlightItem } from '$lib/editor/tools/boxShapes';
import { serializeItem } from '$lib/editor/model';

describe('box shape tools', () => {
  it('rect (no fill) exact JSON', () => {
    expect(serializeItem(rectItem([0, 0, 10, 20], { color: '#112233ff', width: 3 })!)).toEqual({
      type: 'rect',
      rect: [0, 0, 10, 20],
      color: '#112233ff',
      width: 3,
      pos: [0, 0],
      rotation: 0,
      origin: [0, 0],
    });
  });
  it('rect with fill includes fill', () => {
    expect(
      serializeItem(rectItem([0, 0, 10, 20], { color: '#112233ff', width: 3 }, '#445566ff')!),
    ).toEqual({
      type: 'rect',
      rect: [0, 0, 10, 20],
      color: '#112233ff',
      width: 3,
      fill: '#445566ff',
      pos: [0, 0],
      rotation: 0,
      origin: [0, 0],
    });
  });
  it('ellipse exact JSON', () => {
    expect(serializeItem(ellipseItem([0, 0, 10, 20], { color: '#112233ff', width: 3 })!)).toEqual({
      type: 'ellipse',
      rect: [0, 0, 10, 20],
      color: '#112233ff',
      width: 3,
      pos: [0, 0],
      rotation: 0,
      origin: [0, 0],
    });
  });
  it('highlight stores 6-digit color, no width', () => {
    expect(serializeItem(highlightItem([0, 0, 60, 20], '#ffe000')!)).toEqual({
      type: 'highlight',
      rect: [0, 0, 60, 20],
      color: '#ffe000',
      pos: [0, 0],
      rotation: 0,
      origin: [0, 0],
    });
  });
  it('degenerate box is null', () => {
    expect(rectItem([5, 5, 0, 0], { color: '#fff', width: 3 })).toBeNull();
  });
});
