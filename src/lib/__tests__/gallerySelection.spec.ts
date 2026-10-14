import { describe, expect, it } from 'vitest';
import { placeContextMenu, selectGalleryItem } from '$lib/gallerySelection';

const ordered = ['a', 'b', 'c', 'd'];

describe('gallery selection', () => {
  it('replaces the selection on a plain click', () => {
    expect(selectGalleryItem(['a', 'b'], ordered, 'c', 'a', { toggle: false, range: false }))
      .toEqual({ selected: ['c'], anchor: 'c' });
  });

  it('toggles individual items while preserving gallery order', () => {
    expect(selectGalleryItem(['c'], ordered, 'a', 'c', { toggle: true, range: false }).selected)
      .toEqual(['a', 'c']);
    expect(selectGalleryItem(['a', 'c'], ordered, 'c', 'a', { toggle: true, range: false }).selected)
      .toEqual(['a']);
  });

  it('selects an inclusive range from the anchor', () => {
    expect(selectGalleryItem(['b'], ordered, 'd', 'b', { toggle: false, range: true }).selected)
      .toEqual(['b', 'c', 'd']);
  });
});

describe('context menu placement', () => {
  it('keeps a menu at a pointer with enough room', () => {
    expect(placeContextMenu(20, 30, 160, 200, 800, 600)).toEqual({ x: 20, y: 30 });
  });

  it('flips above and clamps away from the right edge', () => {
    expect(placeContextMenu(780, 580, 160, 200, 800, 600)).toEqual({ x: 632, y: 380 });
  });

  it('handles a viewport smaller than the menu', () => {
    expect(placeContextMenu(0, 0, 200, 200, 100, 100)).toEqual({ x: 8, y: 8 });
  });
});
