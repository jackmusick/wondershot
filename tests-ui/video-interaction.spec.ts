import { test, expect } from '@playwright/test';

test.beforeEach(async ({ page }) => {
  await page.goto('/screen?screen=video');
  await page.waitForFunction(() => (document.querySelector('video')?.duration ?? 0) > 0);
});
test('play, pause and seek a real video', async ({ page }) => {
  await page.getByRole('button', { name: 'Play', exact: true }).click();
  await expect.poll(() => page.locator('video').evaluate(v => (v as HTMLVideoElement).currentTime)).toBeGreaterThan(0);
  await page.getByRole('button', { name: 'Pause', exact: true }).click();
  await expect.poll(() => page.locator('video').evaluate(v => (v as HTMLVideoElement).paused)).toBe(true);
  const seek = page.getByRole('slider', { name: 'Seek' });
  await seek.focus(); await seek.press('End');
  await expect.poll(() => page.locator('video').evaluate(v => (v as HTMLVideoElement).currentTime)).toBeGreaterThan(3);
});
test('draw two blur regions, delete one, and apply blur', async ({ page }) => {
  const box = await page.locator('.overlay').boundingBox(); if (!box) throw new Error('missing overlay');
  const cx = box.x + box.width / 2, cy = box.y + box.height / 2;
  for (const x of [cx - 110, cx + 20]) {
    await page.mouse.move(x, cy - 30); await page.mouse.down();
    await page.mouse.move(x + 80, cy + 30, { steps: 8 }); await page.mouse.up();
  }
  await expect(page.getByText(/2 regions —/)).toBeVisible();
  await page.getByRole('button', { name: 'Delete the selected region', exact: true }).click();
  await expect(page.getByText(/1 region —/)).toBeVisible();
  await page.getByRole('button', { name: 'Apply blur', exact: true }).click();
  await expect(page.getByText('Blur applied', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Apply blur', exact: true })).toBeDisabled();
});
test('GIF export supports range and cancellation', async ({ page }) => {
  await page.getByRole('button', { name: 'Export GIF…', exact: true }).click();
  await page.getByLabel('Limit to range').check();
  await page.getByLabel('start', { exact: true }).fill('0.5');
  await page.getByLabel('end', { exact: true }).fill('2.5');
  await page.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(page.locator('.gif-dialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'Export GIF…', exact: true }).click();
  await page.getByRole('button', { name: 'Export GIF', exact: true }).click();
  await expect(page.locator('.gif-dialog')).toHaveCount(0);
  await expect(page.getByText(/GIF exported:/)).toBeVisible();
});
