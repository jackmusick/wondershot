import { readFileSync } from 'node:fs';
import { describe, expect, test } from 'vitest';

describe('settings hotkey support', () => {
  test('macOS uses the same recorder UI as Windows', () => {
    const source = readFileSync('src/lib/components/Settings.svelte', 'utf8');
    const windowsBranch = source.indexOf('{#if isWindows || isMac}');
    const disabledMacInput = source.indexOf('{:else if isMac}');

    expect(windowsBranch).toBeGreaterThan(-1);
    expect(disabledMacInput).toBe(-1);
    expect(source).toContain('Registered directly by Wondershot while the app is running.');
  });

  test('backend starts and updates macOS hotkey registration', () => {
    const source = readFileSync('src-tauri/src/hotkeys.rs', 'utf8');

    expect(source).toContain('target_os = "macos"');
    expect(source).toContain('register_macos_hotkey');
    expect(source).toContain('UnregisterEventHotKey');
    expect(source).toContain('cli://capture');
  });
});
