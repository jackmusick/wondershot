import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';

async function trashCalls(page: Page) {
  return page.evaluate(() => ((window as any).__wsMockCalls ?? []).filter((c: any) => c.command === 'trash_item'));
}

async function openImage(page: Page) {
  await page.goto('/');
  await page.getByRole('button', { name: /Screenshot 13:51/ }).click();
  await page.getByRole('button', { name: /Screenshot 14:02/ }).click({ modifiers: ['Shift'] });
  await expect(page.locator('.filmstrip .card.selected')).toHaveCount(2);
  await page.waitForSelector('[data-editor-ready="true"]');
}

for (const key of ['Delete', 'Backspace']) {
  test(`${key} removes a resized image blur while preserving selected gallery files`, async ({ page }) => {
    await openImage(page);
    const cards = page.locator('.filmstrip .card');
    const count = await cards.count();
    await page.getByRole('button', { name: 'Blur', exact: true }).click();
    const box = await page.locator('.editor-canvas').boundingBox();
    if (!box) throw new Error('missing editor');
    const x0 = box.x + box.width * .4, y0 = box.y + box.height * .4;
    const x1 = box.x + box.width * .6, y1 = box.y + box.height * .6;
    await page.mouse.move(x0, y0); await page.mouse.down();
    await page.mouse.move(x1, y1, { steps: 5 }); await page.mouse.up();
    await page.getByRole('button', { name: 'Select', exact: true }).click();
    await page.mouse.click((x0 + x1) / 2, (y0 + y1) / 2);
    await expect.poll(() => page.evaluate(() => (window as any).__wsEditor.selectionCount())).toBe(1);
    expect(await page.evaluate(() => (window as any).__wsEditor.selectionHasHandles())).toBe(true);
    const beforeWidth = await page.evaluate(() => (window as any).__wsEditor.items()[0].rect[2]);
    const anchor = await page.evaluate(() => {
      const bounds = (window as any).__wsEditor.transformer.findOne('.bottom-right').getClientRect();
      return { x: bounds.x + bounds.width / 2, y: bounds.y + bounds.height / 2 };
    });
    await page.mouse.move(box.x + anchor.x, box.y + anchor.y); await page.mouse.down();
    await page.mouse.move(box.x + anchor.x + 20, box.y + anchor.y + 20, { steps: 5 }); await page.mouse.up();
    await expect.poll(() => page.evaluate(() => (window as any).__wsEditor.items()[0].rect[2])).toBeGreaterThan(beforeWidth);
    await page.keyboard.press(key);
    await expect.poll(() => page.evaluate(() => (window as any).__wsEditor.itemCount())).toBe(0);
    await expect(cards).toHaveCount(count);
    await expect(page.locator('.filmstrip .card.selected')).toHaveCount(2);
    expect(await trashCalls(page)).toHaveLength(0);
    // Repeating Delete on an empty editor must never fall through to gallery deletion.
    await page.keyboard.press(key);
    await expect(cards).toHaveCount(count);
    expect(await trashCalls(page)).toHaveLength(0);
    await page.keyboard.press('Control+z');
    await expect.poll(() => page.evaluate(() => (window as any).__wsEditor.itemCount())).toBe(1);
  });
}

test('Delete still trashes files when focus is explicitly in the gallery', async ({ page }) => {
  await openImage(page);
  await page.getByRole('button', { name: /Screenshot 14:02/ }).click();
  await page.keyboard.press('Delete');
  await expect(page.locator('.filmstrip .card')).toHaveCount(3);
  expect(await trashCalls(page)).toHaveLength(1);
});

for (const interaction of ['layer', 'resize']) {
  test(`Delete removes a video blur after ${interaction} selection without trashing the video`, async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: /Recording 11:20/ }).click();
    await page.waitForFunction(() => (document.querySelector('video')?.duration ?? 0) > 0);
    const box = await page.locator('.overlay').boundingBox();
    if (!box) throw new Error('missing video overlay');
    await page.mouse.move(box.x + box.width * .4, box.y + box.height * .4); await page.mouse.down();
    await page.mouse.move(box.x + box.width * .6, box.y + box.height * .6, { steps: 5 }); await page.mouse.up();
    await expect(page.getByRole('button', { name: 'Blur 1', exact: true })).toBeVisible();
    // Return focus to the gallery, then select or resize an existing blur.
    await page.getByRole('button', { name: /Recording 11:20/ }).click();
    if (interaction === 'layer') {
      await page.getByRole('button', { name: 'Blur 1', exact: true }).click();
    } else {
      const handle = await page.getByRole('button', { name: 'Resize Blur Region 1', exact: true }).boundingBox();
      if (!handle) throw new Error('missing blur resize handle');
      await page.mouse.move(handle.x + handle.width / 2, handle.y + handle.height / 2);
      await page.mouse.down(); await page.mouse.move(handle.x + 25, handle.y + 25, { steps: 5 }); await page.mouse.up();
    }
    await page.keyboard.press('Delete');
    await expect(page.getByRole('button', { name: 'Blur 1', exact: true })).toHaveCount(0);
    await page.keyboard.press('Delete');
    await expect(page.locator('.filmstrip .card')).toHaveCount(4);
    expect(await trashCalls(page)).toHaveLength(0);
  });
}
