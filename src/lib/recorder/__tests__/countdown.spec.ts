import { describe, it, expect } from 'vitest';
import { tickDown } from '$lib/recorder/countdown';

describe('countdown', () => {
  it('decrements and reports not-done', () => {
    expect(tickDown(3)).toEqual({ remaining: 2, done: false });
  });
  it('reaches done at zero', () => {
    expect(tickDown(1)).toEqual({ remaining: 0, done: true });
  });
  it('done stays done past zero', () => {
    expect(tickDown(0)).toEqual({ remaining: -1, done: true });
  });
});
