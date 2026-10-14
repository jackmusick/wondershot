import { test, expect } from '@playwright/test';

async function editor(page: import('@playwright/test').Page) {
  await page.goto('/screen?screen=editor');
  await page.waitForFunction(() => (window as any).__wsEditor?.ready());
  const box = await page.locator('.editor-canvas').boundingBox();
  if (!box) throw new Error('Missing canvas');
  return { x: box.x + box.width / 2, y: box.y + box.height / 2 };
}
async function count(page: import('@playwright/test').Page) {
  return page.evaluate(() => (window as any).__wsEditor.itemCount());
}
for (const tool of ['Arrow', 'Line', 'Box', 'Ellipse', 'Pen', 'Highlight', 'Pixelate', 'Blur']) {
  test(`${tool}: draw, undo, redo`, async ({ page }) => {
    const c = await editor(page);
    await page.getByRole('button', { name: tool, exact: true }).click();
    await page.mouse.move(c.x - 60, c.y - 30); await page.mouse.down();
    await page.mouse.move(c.x + 60, c.y + 30, { steps: 12 }); await page.mouse.up();
    await expect.poll(() => count(page)).toBe(1);
    await page.keyboard.press('Control+z');
    await expect.poll(() => count(page)).toBe(0);
    await page.keyboard.press('Control+Shift+z');
    await expect.poll(() => count(page)).toBe(1);
  });
}
for (const tool of ['Crop', 'Cut |', 'Cut —']) {
  test(`${tool}: changes dimensions and undo restores the original`, async ({ page }) => {
    const c = await editor(page);
    const initial = await page.evaluate(() => (window as any).__wsEditor.imageSize());
    await page.getByRole('button', { name: tool, exact: true }).click();
    await page.mouse.move(c.x - 60, c.y - 30); await page.mouse.down();
    await page.mouse.move(c.x + 60, c.y + 30, { steps: 8 }); await page.mouse.up();
    await expect.poll(() => page.evaluate(() => (window as any).__wsEditor.imageSize())).not.toEqual(initial);
    await page.keyboard.press('Control+z');
    await expect.poll(() => page.evaluate(() => (window as any).__wsEditor.imageSize())).toEqual(initial);
  });
}
test('Text: type, commit, undo and redo', async ({ page }) => {
  const c = await editor(page);
  await page.getByRole('button', { name: 'Text', exact: true }).click();
  await page.mouse.click(c.x, c.y);
  const input = page.locator('.editor-canvas textarea');
  await expect(input).toBeVisible(); await input.fill('macOS regression'); await input.press('Enter');
  await expect(input).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => (window as any).__wsEditor.items()[0]?.text)).toBe('macOS regression');
  await page.keyboard.press('Control+z');
  await expect.poll(() => count(page)).toBe(0);
  await page.keyboard.press('Control+Shift+z');
  await expect.poll(() => count(page)).toBe(1);
});

test('selection resize, stroke edits, deletion and undo preserve editable objects', async ({ page }) => {
  const c = await editor(page);
  await page.getByRole('button', { name: 'Box', exact: true }).click();
  await page.mouse.move(c.x - 60, c.y - 30); await page.mouse.down();
  await page.mouse.move(c.x + 60, c.y + 30, { steps: 8 }); await page.mouse.up();
  await page.getByRole('button', { name: 'Select', exact: true }).click();
  await page.mouse.click(c.x, c.y - 30);
  await expect.poll(() => page.evaluate(() => (window as any).__wsEditor.selectionCount())).toBe(1);
  const initial = await page.evaluate(() => (window as any).__wsEditor.items()[0]);
  const anchor = await page.evaluate(() => {
    const h = (window as any).__wsEditor;
    const r = h.transformer.findOne('.bottom-right').getClientRect();
    return { x: r.x + r.width / 2, y: r.y + r.height / 2 };
  });
  const box = await page.locator('.editor-canvas').boundingBox(); if (!box) throw new Error('missing canvas');
  await page.mouse.move(box.x + anchor.x, box.y + anchor.y); await page.mouse.down();
  await page.mouse.move(box.x + anchor.x + 35, box.y + anchor.y + 20, { steps: 8 }); await page.mouse.up();
  await expect.poll(() => page.evaluate(() => (window as any).__wsEditor.items()[0].rect[2])).toBeGreaterThan(initial.rect[2]);
  await page.getByLabel('Stroke width', { exact: true }).fill('12');
  await expect.poll(() => page.evaluate(() => (window as any).__wsEditor.items()[0].width)).toBe(12);
  // Return focus to the canvas so Delete acts on the selection, not the field.
  await page.locator('.editor-canvas').click({ position: { x: box.width / 2, y: box.height / 2 - 30 } });
  await page.keyboard.press('Delete');
  await expect.poll(() => count(page)).toBe(0);
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect.poll(() => count(page)).toBe(1);
  await page.getByRole('button', { name: 'Redo', exact: true }).click();
  await expect.poll(() => count(page)).toBe(0);
});

test('zoom buttons change scale and actual size restores one-to-one pixels', async ({ page }) => {
  await editor(page);
  const scale = () => page.evaluate(() => (window as any).__wsEditor.scale());
  const start = await scale();
  await page.getByRole('button', { name: 'Zoom in', exact: true }).click();
  await expect.poll(scale).toBeGreaterThan(start);
  await page.getByRole('button', { name: 'Zoom out', exact: true }).click();
  await expect.poll(scale).toBeCloseTo(start);
  await page.getByTitle('Actual size (100%)', { exact: true }).click();
  await expect.poll(scale).toBe(1);
});

test('rotation persists in the editable model and supports undo/redo', async ({ page }) => {
  const c = await editor(page);
  await page.getByRole('button', { name: 'Box', exact: true }).click();
  await page.mouse.move(c.x - 60, c.y - 30); await page.mouse.down();
  await page.mouse.move(c.x + 60, c.y + 30, { steps: 8 }); await page.mouse.up();
  const geometry = await page.evaluate(() => {
    const h = (window as any).__wsEditor;
    const anchor = h.transformer.findOne('.rotater').getClientRect();
    const node = h.transformer.nodes()[0].getClientRect();
    return { x: anchor.x + anchor.width / 2, y: anchor.y + anchor.height / 2, cx: node.x + node.width / 2, cy: node.y + node.height / 2 };
  });
  const box = await page.locator('.editor-canvas').boundingBox(); if (!box) throw new Error('missing canvas');
  await page.mouse.move(box.x + geometry.x, box.y + geometry.y); await page.mouse.down();
  await page.mouse.move(box.x + geometry.cx + 90, box.y + geometry.cy, { steps: 12 }); await page.mouse.up();
  const rotation = () => page.evaluate(() => Math.abs((window as any).__wsEditor.items()[0]?.rotation ?? 0));
  await expect.poll(rotation).toBeGreaterThan(30);
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  await expect.poll(rotation).toBe(0);
  await page.getByRole('button', { name: 'Redo', exact: true }).click();
  await expect.poll(rotation).toBeGreaterThan(30);
});

test('selected text accepts font size and alignment changes', async ({ page }) => {
  const c = await editor(page);
  await page.getByRole('button', { name: 'Text', exact: true }).click();
  await page.mouse.click(c.x, c.y);
  await page.locator('.editor-canvas textarea').fill('Editable text');
  await page.locator('.editor-canvas textarea').press('Enter');
  await page.getByLabel('Text size', { exact: true }).fill('36');
  await page.getByRole('button', { name: 'Align center', exact: true }).click();
  await expect.poll(() => page.evaluate(() => (window as any).__wsEditor.items()[0]?.point_size)).toBe(36);
  await expect.poll(() => page.evaluate(() => (window as any).__wsEditor.items()[0]?.align)).toBe('center');
});

test('editing properties preserves annotation stacking through undo and redo', async ({ page }) => {
  const c = await editor(page);
  await page.getByRole('button', { name: 'Box', exact: true }).click();
  for (const offset of [0, 160]) {
    await page.mouse.move(c.x - 60 + offset, c.y - 30); await page.mouse.down();
    await page.mouse.move(c.x + 60 + offset, c.y + 30, { steps: 8 }); await page.mouse.up();
  }
  await expect.poll(() => count(page)).toBe(2);
  await page.getByRole('button', { name: 'Select', exact: true }).click();
  await page.mouse.click(c.x, c.y - 30);
  await expect.poll(() => page.evaluate(() => (window as any).__wsEditor.selectionCount())).toBe(1);
  const selectedIndex = () => page.evaluate(() => (window as any).__wsEditor.transformer.nodes()[0]?.zIndex());
  const before = await selectedIndex();
  await page.getByLabel('Stroke width', { exact: true }).fill('12');
  await expect.poll(selectedIndex).toBe(before);
  await expect.poll(() => page.evaluate(() => (window as any).__wsEditor.items()[0].width)).toBe(12);
  await page.getByRole('button', { name: 'Undo', exact: true }).click();
  // Undo/redo rebuild Konva's annotation hit graph asynchronously. Wait until
  // the old transformer selection is cleared before clicking the box stroke.
  await expect.poll(() => page.evaluate(() => (window as any).__wsEditor.selectionCount())).toBe(0);
  await page.mouse.click(c.x, c.y - 30);
  await expect.poll(selectedIndex).toBe(before);
  await page.getByRole('button', { name: 'Redo', exact: true }).click();
  await expect.poll(() => page.evaluate(() => (window as any).__wsEditor.selectionCount())).toBe(0);
  await page.mouse.click(c.x, c.y - 30);
  await expect.poll(selectedIndex).toBe(before);
});
