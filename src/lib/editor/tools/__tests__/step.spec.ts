import { describe, it, expect } from 'vitest';
import { stepItem, nextStepNumber } from '$lib/editor/tools/step';
import { serializeItem } from '$lib/editor/model';

describe('step tool', () => {
  it('produces exact JSON', () => {
    expect(serializeItem(stepItem(3, [5, 5], '#3b82f6ff'))).toEqual({
      type: 'step',
      number: 3,
      color: '#3b82f6ff',
      radius: 16,
      pos: [5, 5],
      rotation: 0,
      origin: [0, 0],
    });
  });
  it('nextStepNumber is max+1 (1 when none)', () => {
    expect(nextStepNumber([])).toBe(1);
    const a = stepItem(1, [0, 0], '#fff');
    const b = stepItem(2, [0, 0], '#fff');
    expect(nextStepNumber([a, b])).toBe(3);
    // after removing #2, next reuses 2 (derive from remaining)
    expect(nextStepNumber([a])).toBe(2);
  });
  it('honors custom radius', () => {
    expect(serializeItem(stepItem(1, [0, 0], '#fff', 24)).radius).toBe(24);
  });
});
