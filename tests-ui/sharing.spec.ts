import { test, expect } from '@playwright/test';

async function openCapture(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.getByRole('button', { name: /Screenshot 14:02/ }).click();
  await expect(page.locator('[data-editor-ready="true"]')).toBeVisible();
}

async function uploads(page: import('@playwright/test').Page) {
  return page.evaluate(() =>
    ((window as any).__wsMockCalls ?? []).filter((call: { command: string }) => call.command === 'share_capture').length
  );
}

test('Share opens setup, keeps incomplete setup open, and resumes after connecting', async ({ page }) => {
  await openCapture(page);
  await page.getByRole('button', { name: 'Share', exact: true }).click();
  const settings = page.getByRole('dialog', { name: 'Settings', exact: true });
  await expect(settings.getByText('Set up sharing to create a link.', { exact: false })).toBeVisible();
  await expect(settings.getByLabel('Default provider')).toBeVisible();
  expect(await uploads(page)).toBe(0);
  await settings.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(settings.getByRole('alert')).toContainText('Connect OneDrive');
  expect(await uploads(page)).toBe(0);
  await settings.getByRole('button', { name: 'Connect…', exact: true }).click();
  await expect(settings.getByText('Connected as mock@example.com')).toBeVisible();
  await settings.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(settings).toBeHidden();
  await expect(page.getByText('Link copied (onedrive)', { exact: true })).toBeVisible();
  expect(await uploads(page)).toBe(1);
  expect(await page.evaluate(() => (window as any).__wsMockCalls.find((call: any) => call.command === 'share_capture').args.path))
    .toBe('/lib/Screenshot_20260608_140200.png');
  // A configured provider shares immediately on subsequent clicks.
  await page.getByRole('button', { name: 'Share', exact: true }).click();
  await expect(settings).toBeHidden();
  await expect.poll(() => uploads(page)).toBe(2);
});

test('Cancel discards the pending share even when settings are later saved', async ({ page }) => {
  await openCapture(page);
  await page.getByRole('button', { name: 'Share', exact: true }).click();
  const settings = page.getByRole('dialog', { name: 'Settings', exact: true });
  await settings.getByRole('button', { name: 'Cancel', exact: true }).click();
  await expect(settings).toBeHidden();
  await page.keyboard.press('Control+,');
  await settings.getByRole('tab', { name: 'Sharing', exact: true }).click();
  await settings.getByRole('button', { name: 'Connect…', exact: true }).click();
  await expect(settings.getByText('Connected as mock@example.com')).toBeVisible();
  await settings.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(settings).toBeHidden();
  expect(await uploads(page)).toBe(0);
});
