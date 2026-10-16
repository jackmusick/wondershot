import { test, expect } from '@playwright/test';

test('Import opens an OBS recording ready for blur editing', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.goto('/');
  await expect(page.getByRole('button', { name: /Screenshot 14:02/ })).toBeVisible();
  await expect(page.getByText('Drop images or videos here, or choose Import')).toBeVisible();
  await page.getByRole('button', { name: 'Import', exact: true }).click();
  await expect(page.locator('video')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Blur', exact: true })).toBeVisible();
  await page.waitForFunction(() => (document.querySelector('video')?.duration ?? 0) > 0);
  const box = await page.locator('.overlay').boundingBox();
  if (!box) throw new Error('Missing video overlay');
  await page.mouse.move(box.x + box.width * .3, box.y + box.height * .3);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * .5, box.y + box.height * .5, { steps: 8 });
  await page.mouse.up();
  await expect(page.getByRole('button', { name: 'Apply Blur', exact: true })).toBeVisible();
  await expect(page.getByText('Importing media…', { exact: false })).toHaveCount(0);
  await page.screenshot({ path: '/tmp/wondershot-import.png' });
  expect(errors).toEqual([]);
});

test('keyboard shortcut opens media without triggering browser Open', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('button', { name: /Screenshot 14:02/ })).toBeVisible();
  await page.keyboard.press('Control+o');
  await expect(page.locator('video')).toBeVisible();
  const calls = await page.evaluate(() => (window as any).__wsMockCalls);
  expect(calls.some((c: any) => c.command === 'pick_import_files')).toBe(true);
  expect(calls.some((c: any) => c.command === 'import_files')).toBe(true);
});
