import { test, expect } from '@playwright/test';
import { existsSync } from 'node:fs';

const REF_URL = process.env.WONDERBLOB_URL ?? 'http://localhost:1430';

test('reference: wonderblob shell', async ({ page }) => {
  let up = true;
  await page.goto(REF_URL).catch(() => { up = false; });
  test.skip(!up, 'wonderblob dev server not running on ' + REF_URL);
  await page.waitForTimeout(300);
  await page.screenshot({ path: 'artifacts/ui/ref/wonderblob-shell.png' });
  expect(existsSync('artifacts/ui/ref/wonderblob-shell.png')).toBe(true);
});
