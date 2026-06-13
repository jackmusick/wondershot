import { describe, expect, it } from 'vitest';
import { isNativeRecorderPlatform, shouldUseBrowserMedia } from '$lib/platform';

describe('platform media policy', () => {
  it('keeps desktop media off browser permission prompts', () => {
    expect(shouldUseBrowserMedia('windows')).toBe(false);
    expect(shouldUseBrowserMedia('macos')).toBe(false);
    expect(shouldUseBrowserMedia('linux')).toBe(false);
  });

  it('advertises native recorder support only where implemented', () => {
    expect(isNativeRecorderPlatform('windows')).toBe(true);
    expect(isNativeRecorderPlatform('linux')).toBe(true);
    expect(isNativeRecorderPlatform('macos')).toBe(false);
    expect(isNativeRecorderPlatform('unknown')).toBe(false);
  });
});
