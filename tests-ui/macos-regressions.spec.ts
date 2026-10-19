import { test, expect } from '@playwright/test';

test('fresh capture shows all editor controls immediately', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText('Drop images or videos here, or choose Import')).toBeVisible();
  // Library loading confirms client hydration has attached the capture handler.
  await expect(page.getByRole('button', { name: /Screenshot 14:02/ })).toBeVisible();
  await page.getByRole('button', { name: 'Capture', exact: true }).click();
  await page.getByRole('button', { name: 'Full screen', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Arrow', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Crop', exact: true })).toBeVisible();
  await expect(page.locator('[data-editor-ready="true"]')).toBeVisible();
});

test('camera bubble has transparent document corners', async ({ page }) => {
  await page.goto('/bubble');
  const backgrounds = await page.evaluate(() => [document.documentElement, document.body, document.querySelector('.bubble')!].map(e => getComputedStyle(e).backgroundColor));
  expect(backgrounds).toEqual(['rgba(0, 0, 0, 0)', 'rgba(0, 0, 0, 0)', 'rgba(0, 0, 0, 0)']);
  await expect(page.locator('.bubble')).toHaveCSS('border-radius', '50%');
});
