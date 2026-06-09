import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';

const css = readFileSync('src/lib/styles/tokens.css', 'utf8');

describe('design tokens', () => {
  it('defines the two-plane dark backgrounds', () => {
    // Chrome (header/rail/properties) sits lighter over the darker canvas
    // (--bg-app) for Qt-style contrast.
    expect(css).toContain('--bg-app: #161618');
    expect(css).toContain('--bg-content: #303034');
  });
  it('defines the accent and radius', () => {
    expect(css).toMatch(/--accent:\s*#3b82f6/);
    expect(css).toContain('--radius: 6px');
  });
});
