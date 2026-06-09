import { describe, it, expect } from 'vitest';
import { pixelateItem, blurItem } from '$lib/editor/tools/redact';
import { serializeItem } from '$lib/editor/model';

describe('redact tools', () => {
  it('pixelate exact JSON', () => {
    expect(serializeItem(pixelateItem([20, 20, 60, 40])!))
      .toEqual({ type: 'pixelate', rect: [20, 20, 60, 40], block: 14, pos: [0, 0], rotation: 0, origin: [0, 0] });
  });
  it('blur exact JSON', () => {
    expect(serializeItem(blurItem([20, 20, 60, 40])!))
      .toEqual({ type: 'blur', rect: [20, 20, 60, 40], radius: 12, pos: [0, 0], rotation: 0, origin: [0, 0] });
  });
  it('degenerate is null', () => {
    expect(pixelateItem([0, 0, 0, 0])).toBeNull();
    expect(blurItem([5, 5, 0, 10])).toBeNull();
  });
});
