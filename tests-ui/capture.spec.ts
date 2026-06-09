import { test, expect } from '@playwright/test';
import { existsSync, statSync } from 'node:fs';

const SCREENS = ['shell', 'sidebar', 'header', 'editor'];
const THEMES = ['dark', 'light'] as const;

for (const screen of SCREENS) {
  for (const theme of THEMES) {
    test(`shot ${screen} ${theme}`, async ({ page }) => {
      const url = screen === 'shell' ? '/' : `/screen?screen=${screen}`;
      await page.goto(url);
      await page.evaluate((t) => document.documentElement.setAttribute('data-theme', t), theme);
      if (screen === 'editor') {
        await page.waitForSelector('[data-editor-ready="true"]', { timeout: 8000 });
      }
      await page.waitForTimeout(150);
      const out = `artifacts/ui/${screen}-${theme}.png`;
      await page.screenshot({ path: out });
      expect(existsSync(out) && statSync(out).size > 0).toBe(true);
    });
  }
}
