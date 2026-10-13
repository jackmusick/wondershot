import { describe, expect, it } from 'vitest';
import { isNativeRecorderPlatform, shouldUseBrowserMedia } from '$lib/platform';

describe('platform media policy', () => {
  it('uses app-owned browser media on macOS and native media elsewhere', () => {
    expect(shouldUseBrowserMedia('windows')).toBe(false);
    expect(shouldUseBrowserMedia('linux')).toBe(false);
    expect(shouldUseBrowserMedia('macos')).toBe(true);
  });

  it('advertises native recorder support only where implemented', () => {
    expect(isNativeRecorderPlatform('windows')).toBe(true);
    expect(isNativeRecorderPlatform('linux')).toBe(true);
    expect(isNativeRecorderPlatform('macos')).toBe(true);
    expect(isNativeRecorderPlatform('unknown')).toBe(false);
  });
});
