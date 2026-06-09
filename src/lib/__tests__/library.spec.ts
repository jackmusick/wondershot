import { describe, it, expect } from 'vitest';
import { groupByDate } from '$lib/library';
import type { Capture } from '$lib/types';

const cap = (id: string, createdAt: number): Capture => ({
  id, createdAt, path: `/x/${id}.png`, kind: 'image',
  thumbnail: '', title: id
});

describe('groupByDate', () => {
  it('buckets Today and Yesterday relative to a reference time', () => {
    const now = new Date('2026-06-08T12:00:00Z').getTime();
    const today = new Date('2026-06-08T09:00:00Z').getTime();
    const yest = new Date('2026-06-07T22:00:00Z').getTime();
    const groups = groupByDate([cap('a', today), cap('b', yest)], now);
    expect(groups[0].label).toBe('Today');
    expect(groups[0].items.map(i => i.id)).toEqual(['a']);
    expect(groups[1].label).toBe('Yesterday');
    expect(groups[1].items.map(i => i.id)).toEqual(['b']);
  });
  it('sorts items newest-first within a group', () => {
    const now = new Date('2026-06-08T12:00:00Z').getTime();
    const g = groupByDate([cap('old', now - 3000), cap('new', now - 1000)], now);
    expect(g[0].items.map(i => i.id)).toEqual(['new', 'old']);
  });
});
