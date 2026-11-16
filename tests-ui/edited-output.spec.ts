import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';

async function drawBlur(page: Page, selector: string) {
  const box = await page.locator(selector).boundingBox();
  if (!box) throw new Error('missing canvas');
  await page.mouse.move(box.x + box.width * .4, box.y + box.height * .4);
  await page.mouse.down();
  await page.mouse.move(box.x + box.width * .6, box.y + box.height * .6, { steps: 4 });
  await page.mouse.up();
}

async function calls(page: Page) {
  return page.evaluate(() => (window as any).__wsMockCalls as {command: string; args: any}[]);
}

test('image autosave bakes the PNG and immediate copy waits for the edited pixels', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button', { name: /Screenshot 14:02/ }).click();
  await page.waitForSelector('[data-editor-ready="true"]');
  await page.getByRole('button', { name: 'Blur', exact: true }).click();
  await drawBlur(page, '.editor-canvas');
  // Copy immediately, before the debounce timer fires.
  await page.keyboard.press('Control+c');
  await expect.poll(async () => (await calls(page)).filter(c => c.command === 'copy_image').length).toBe(1);
  const log = await calls(page);
  const bake = log.findIndex(c => c.command === 'flatten_save');
  expect(bake).toBeGreaterThan(-1);
  expect(log.findIndex(c => c.command === 'copy_image')).toBeGreaterThan(bake);
  expect(log.find(c => c.command === 'save_sidecar')?.args.doc.items[0].type).toBe('blur');
  expect(log[bake].args.pngB64.length).toBeGreaterThan(100);
  const pixel = await page.evaluate(async b64 => {
    const image = new Image();
    image.src = `data:image/png;base64,${b64}`;
    await image.decode();
    const canvas = document.createElement('canvas');
    canvas.width = image.naturalWidth; canvas.height = image.naturalHeight;
    const ctx = canvas.getContext('2d')!;
    ctx.drawImage(image, 0, 0);
    return Array.from(ctx.getImageData(canvas.width / 2, canvas.height / 2, 1, 1).data);
  }, log[bake].args.pngB64);
  // Mock blur returns an opaque gray patch; verify it reached the exported pixels.
  // Canvas pattern interpolation can round a channel by one level.
  for (const channel of pixel.slice(0, 3)) expect(Math.abs(channel - 128)).toBeLessThanOrEqual(1);
  expect(pixel[3]).toBe(255);

  // A second edit must also reach the PNG without an explicit save or copy.
  await page.getByRole('button', { name: 'Box', exact: true }).click();
  await drawBlur(page, '.editor-canvas');
  await expect.poll(async () => (await calls(page)).filter(c => c.command === 'flatten_save').length).toBeGreaterThan(1);
});

test('video copy and Save As render draft blurs, including after switching away', async ({ page }) => {
  await page.goto('/');
  await page.locator('.filmstrip .card').filter({ has: page.locator('.play') }).first().click();
  await page.waitForFunction(() => (document.querySelector('video')?.duration ?? 0) > 0);
  await drawBlur(page, '.overlay');
  await page.keyboard.press('Control+c');
  await expect.poll(async () => (await calls(page)).filter(c => c.command === 'copy_files').length).toBe(1);
  let log = await calls(page);
  const render = log.findIndex(c => c.command === 'apply_blur');
  expect(render).toBeGreaterThan(-1);
  expect(log.findIndex(c => c.command === 'copy_files')).toBeGreaterThan(render);
  expect(log.find(c => c.command === 'copy_files')?.args.paths[0]).toContain('redacted');

  await page.locator('.filmstrip .card').filter({ hasNot: page.locator('.play') }).first().click();
  // The video draft survives switching away; reopening its menu still exports edits.
  await page.locator('.filmstrip .card').filter({ has: page.locator('.play') }).first().click({ button: 'right' });
  await page.getByRole('menuitem', { name: 'Save as…' }).click();
  await expect.poll(async () => (await calls(page)).filter(c => c.command === 'save_image_as').length).toBe(1);
  log = await calls(page);
  expect(log.find(c => c.command === 'save_image_as')?.args.path).toContain('redacted');
});
