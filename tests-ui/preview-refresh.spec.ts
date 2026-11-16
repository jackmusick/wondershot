import { test, expect } from '@playwright/test';

test('same-path file changes refresh the gallery pixels as well as the timestamp', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/screen?screen=filmstrip');
  await expect(page.locator('.filmstrip .card').first()).toBeVisible();

  const images = await page.evaluate(() => {
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 20;
    const ctx = canvas.getContext('2d')!;
    return ['#ff0000', '#0000ff'].map(color => {
      ctx.fillStyle = color; ctx.fillRect(0, 0, 20, 20);
      return canvas.toDataURL().split(',')[1];
    });
  });
  let revision = 0;
  const requested: string[] = [];
  await page.route('**/preview-refresh.png*', async route => {
    requested.push(route.request().url());
    await route.fulfill({ contentType: 'image/png', headers: { 'Cache-Control': 'max-age=3600' },
      body: Buffer.from(images[revision], 'base64') });
  });

  async function scan(modified: number) {
    await page.evaluate(async modified => {
      const stores = await import('/src/lib/stores.ts' as string);
      const ipc = await import('/src/lib/ipc.ts' as string);
      stores.captures.set(await ipc.normalizeCaptures([{ id: 'same-file', path: '/library/photo.png',
        kind: 'image', thumbnail: '/preview-refresh.png', createdAt: modified, title: 'Edited photo' }]));
    }, modified);
  }
  const thumb = page.locator('.filmstrip img[alt="Edited photo"]');
  async function pixel() {
    return thumb.evaluate((image: HTMLImageElement) => {
      const canvas = document.createElement('canvas'); canvas.width = canvas.height = 1;
      const ctx = canvas.getContext('2d')!; ctx.drawImage(image, 0, 0, 1, 1);
      return Array.from(ctx.getImageData(0, 0, 1, 1).data);
    });
  }

  await scan(Date.parse('2026-06-08T12:00:00Z'));
  await expect.poll(pixel).toEqual([255, 0, 0, 255]);
  const oldSource = await thumb.getAttribute('src');
  const oldTime = await page.locator('.filmstrip .time').textContent();
  await thumb.evaluate(image => { (window as any).__previewImage = image; });

  revision = 1;
  await scan(Date.parse('2026-06-08T13:00:00Z'));
  await expect.poll(pixel).toEqual([0, 0, 255, 255]);
  expect(await thumb.getAttribute('src')).not.toBe(oldSource);
  expect(await page.locator('.filmstrip .time').textContent()).not.toBe(oldTime);
  expect(await thumb.evaluate(image => image === (window as any).__previewImage)).toBe(true);
  expect(requested).toHaveLength(2);
  expect(errors).toEqual([]);
});
