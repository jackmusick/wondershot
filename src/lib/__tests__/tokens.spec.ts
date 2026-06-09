import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';

const css = readFileSync('src/lib/styles/tokens.css', 'utf8');

describe('design tokens', () => {
  it('defines the two-plane dark backgrounds', () => {
    expect(css).toContain('--bg-sidebar: #141416');
    expect(css).toContain('--bg-content: #29292c');
  });
  it('defines the accent and radius', () => {
    expect(css).toMatch(/--accent:\s*#3b82f6/);
    expect(css).toContain('--radius: 6px');
  });
});
