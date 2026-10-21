import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';

// Toolbar buttons follow the native (Snagit/macOS) treatment: state is shown by
// the glyph/label colour only, never by a filled background pill.
const TOOLBARS: Record<string, RegExp> = {
  'src/lib/components/CaptureHeader.svelte': /\.hbtn/,
  'src/lib/editor/EditorToolbar.svelte': /\.tool\b/,
  'src/lib/video/VideoPlayer.svelte': /\.(tool|iconbtn)\b/,
  'src/lib/components/OverflowToolbar.svelte': /\.more\b/,
  'src/routes/capture-actionbar/+page.svelte': /\.tool\b/,
  'src/routes/region-picker/+page.svelte': /\.tool\b/
};

function styleRules(file: string): { selector: string; body: string }[] {
  const source = readFileSync(file, 'utf8');
  const style = source.slice(source.indexOf('<style'));
  const rules: { selector: string; body: string }[] = [];
  for (const match of style.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    rules.push({ selector: match[1].replace(/\/\*[\s\S]*?\*\//g, '').trim(), body: match[2] });
  }
  return rules;
}

function backgrounds(body: string): string[] {
  return [...body.matchAll(/(?:^|[;\s])background(?:-color)?\s*:\s*([^;]+)/g)].map(m => m[1].trim());
}

describe('native toolbar buttons', () => {
  for (const [file, button] of Object.entries(TOOLBARS)) {
    it(`${file} never paints a button background`, () => {
      const rules = styleRules(file).filter(r => button.test(r.selector) && !r.selector.includes('.popup'));
      expect(rules.length).toBeGreaterThan(0);
      for (const rule of rules) {
        for (const value of backgrounds(rule.body)) {
          expect(value, `${rule.selector} background`).toBe('transparent');
        }
      }
    });
  }

  it('keeps the Capture action as accent-coloured glyph and label', () => {
    const rules = styleRules('src/lib/components/CaptureHeader.svelte');
    const capture = rules.find(r => r.selector === '.hbtn.capture-action');
    expect(capture?.body).toContain('color: var(--toolbar-fg-emphasis)');
    const active = rules.find(r => r.selector.startsWith('.hbtn.active'));
    expect(active?.body).toContain('color: var(--toolbar-fg-active)');
  });

  it('marks the selected editor tool with the accent colour only', () => {
    const rules = styleRules('src/lib/editor/EditorToolbar.svelte');
    const active = rules.find(r => r.selector.startsWith('.tool.active'));
    expect(active?.body.trim()).toBe('color: var(--toolbar-fg-active);');
  });
});
