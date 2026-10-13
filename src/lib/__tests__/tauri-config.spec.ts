import { readFileSync } from 'node:fs';
import { describe, expect, test } from 'vitest';

describe('Tauri window configuration', () => {
  test('does not pre-create the countdown window at startup', () => {
    const config = JSON.parse(readFileSync('src-tauri/tauri.conf.json', 'utf8'));
    const labels = config.app.windows.map((window: { label: string }) => window.label);

    expect(labels).not.toContain('countdown');
  });
});
