import { describe, it, expect } from 'vitest';
import { toolForKey } from '../tools';

describe('toolForKey', () => {
  it('maps v to select', () => {
    expect(toolForKey('v', false)).toBe('select');
  });
  it('maps a to arrow', () => {
    expect(toolForKey('a', false)).toBe('arrow');
  });
  it('maps u to cutout-v without shift', () => {
    expect(toolForKey('u', false)).toBe('cutout-v');
  });
  it('maps u to cutout-h with shift', () => {
    expect(toolForKey('u', true)).toBe('cutout-h');
  });
  it('returns null for an unmapped key', () => {
    expect(toolForKey('z', false)).toBeNull();
  });
});
