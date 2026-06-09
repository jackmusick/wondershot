import { test, expect } from '@playwright/test';
import { existsSync, statSync } from 'node:fs';

const SCREENS = ['shell', 'filmstrip', 'header', 'editor', 'video', 'settings', 'capture'];
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
      if (screen === 'settings') {
        await page.waitForSelector('[data-settings-ready="true"]', { timeout: 8000 });
      }
      if (screen === 'video') {
        // The <video> won't decode a real file headlessly, but the transport
        // controls render immediately on --bg-content — that's what we shoot.
        await page.waitForSelector('input.timeline', { timeout: 8000 });
      }
      await page.waitForTimeout(150);
      const out = `artifacts/ui/${screen}-${theme}.png`;
      await page.screenshot({ path: out });
      expect(existsSync(out) && statSync(out).size > 0).toBe(true);
    });
  }
}
