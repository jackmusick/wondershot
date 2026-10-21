import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';

const css = readFileSync('src/lib/styles/tokens.css', 'utf8');
const bifrost = readFileSync('src/lib/styles/bifrost-tokens.css', 'utf8');

describe('design tokens', () => {
  it('maps the app canvas and chrome to the Bifrost surface contract', () => {
    expect(css).toContain('--bg-app: var(--bf-canvas)');
    expect(css).toContain('--bg-content: var(--bf-paper)');
    expect(bifrost).toContain('--bf-canvas: var(--background, #08090b)');
    expect(bifrost).toContain('--bf-paper: var(--card, #0a0c0f)');
  });
  it('uses Bifrost action and control geometry tokens', () => {
    expect(css).toContain('--accent: var(--bf-primary)');
    expect(css).toContain('--radius: var(--bf-radius-control)');
    expect(bifrost).toContain('--bf-primary: #2fd4d4');
    expect(bifrost).toContain('--bf-radius-control: 6px');
  });
  it('defines native toolbar colour states on top of the Bifrost palette', () => {
    expect(css).toContain('--toolbar-fg: var(--fg-secondary)');
    expect(css).toContain('--toolbar-fg-hover: var(--fg-primary)');
    expect(css).toContain('--toolbar-fg-active: var(--accent)');
    expect(css).toContain('--toolbar-fg-emphasis: var(--accent)');
    expect(css).toContain('--toolbar-fg-emphasis-hover: var(--accent-strong)');
  });
});
