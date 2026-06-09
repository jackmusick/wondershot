import { describe, it, expect } from 'vitest';
import { normalizeColor } from '../style';

describe('normalizeColor', () => {
  it('appends ff alpha to a 6-digit hex', () => {
    expect(normalizeColor('#ff3b30')).toBe('#ff3b30ff');
  });
  it('uppercases pass through unchanged in value, alpha added', () => {
    expect(normalizeColor('#AABBCC')).toBe('#AABBCCff');
  });
  it('leaves an 8-digit hex untouched', () => {
    expect(normalizeColor('#11223344')).toBe('#11223344');
  });
  it('passes through non-hex values unchanged', () => {
    expect(normalizeColor('rgba(0,0,0,1)')).toBe('rgba(0,0,0,1)');
  });
});
