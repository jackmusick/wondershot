import { describe, it, expect } from 'vitest';
import { History } from '$lib/editor/history';

describe('History', () => {
  it('undo/redo restores prior snapshots', () => {
    const h = new History<number[]>([]);
    h.push([1]);
    h.push([1, 2]);
    expect(h.current()).toEqual([1, 2]);
    expect(h.undo()).toEqual([1]);
    expect(h.undo()).toEqual([]);
    expect(h.redo()).toEqual([1]);
  });
  it('push after undo truncates the redo branch', () => {
    const h = new History<number[]>([]);
    h.push([1]); h.push([1,2]); h.undo();
    h.push([9]);
    expect(h.redo()).toBeNull();        // nothing to redo
    expect(h.current()).toEqual([9]);
  });
  it('clean index tracks saved state', () => {
    const h = new History<number[]>([]);
    h.push([1]);
    h.markClean();
    expect(h.isClean()).toBe(true);
    h.push([1,2]);
    expect(h.isClean()).toBe(false);
    h.undo();
    expect(h.isClean()).toBe(true);
  });
});
