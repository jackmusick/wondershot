import { describe, it, expect } from 'vitest';
import { cropDims, cutoutDims } from '$lib/editor/tools/destructive';

describe('destructive geometry', () => {
  it('cropDims returns the rect size', () => {
    expect(cropDims(800, 500, [100, 50, 300, 200])).toEqual([300, 200]);
  });
  it('cutoutV shrinks width by the band', () => {
    expect(cutoutDims(800, 500, 200, 500, 'v')).toEqual([500, 500]); // removed [200,500)=300 wide -> 500
  });
  it('cutoutH shrinks height by the band', () => {
    expect(cutoutDims(800, 500, 100, 300, 'h')).toEqual([800, 300]); // removed 200 tall -> 300
  });
});
