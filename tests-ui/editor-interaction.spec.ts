import { test, expect } from '@playwright/test';

// End-to-end editor interaction, driven with real mouse events against the live
// Konva canvas (mock IPC — no Tauri backend needed). Asserts via the window
// __wsEditor test hook. These catch the interaction bugs that JSON/screenshot
// tests structurally cannot (selection, transformer handles, step placement…).

type Hook = {
  itemCount: () => number;
  selectionCount: () => number;
  selectionHasHandles: () => boolean;
  ready: () => boolean;
};

async function gotoEditor(page: import('@playwright/test').Page) {
  await page.goto('/screen?screen=editor');
  await page.waitForSelector('[data-editor-ready="true"]', { timeout: 10000 });
  // Wait for the hook to be installed.
  await page.waitForFunction(() => (window as any).__wsEditor?.ready?.() === true);
}

/** Bounding box of the editor canvas, for picking in-image coordinates. */
async function canvasBox(page: import('@playwright/test').Page) {
  const el = page.locator('.editor-canvas');
  const box = await el.boundingBox();
  if (!box) throw new Error('no canvas box');
  return box;
}

async function pickTool(page: import('@playwright/test').Page, label: string) {
  await page.locator(`button[aria-label="${label}"]`).click();
}

function hook<T>(page: import('@playwright/test').Page, fn: (h: Hook) => T) {
  return page.evaluate(fn as any, undefined);
}

test('draw a box, then select it → transformer shows resize/rotate handles', async ({ page }) => {
  await gotoEditor(page);
  const start = await hook(page, () => (window as any).__wsEditor.itemCount());
  expect(start).toBe(0);

  const box = await canvasBox(page);
  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;

  // Draw a rectangle (Box tool) by dragging across the image center.
  await pickTool(page, 'Box');
  await page.mouse.move(cx - 80, cy - 60);
  await page.mouse.down();
  await page.mouse.move(cx + 80, cy + 60, { steps: 8 });
  await page.mouse.up();

  await expect
    .poll(() => hook(page, () => (window as any).__wsEditor.itemCount()))
    .toBe(1);

  // Switch to Select and click the rectangle's center.
  await pickTool(page, 'Select');
  await page.mouse.click(cx, cy);

  await expect
    .poll(() => hook(page, () => (window as any).__wsEditor.selectionCount()))
    .toBe(1);
  // The reported bug: no 4-corner/rotation handles. resizeEnabled must be true
  // for a box (only arrow/line are drag-only).
  expect(await hook(page, () => (window as any).__wsEditor.selectionHasHandles())).toBe(true);
  // …and the anchors must actually RENDER (the visual "corners"): 4 corners + rotater.
  expect(await hook(page, () => (window as any).__wsEditor.renderedAnchors())).toBeGreaterThanOrEqual(5);
});

test('step tool places exactly one badge per click (not drag-existing + add)', async ({ page }) => {
  await gotoEditor(page);
  const box = await canvasBox(page);
  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;

  await pickTool(page, 'Step');
  await page.mouse.click(cx - 40, cy - 40);
  await expect.poll(() => hook(page, () => (window as any).__wsEditor.itemCount())).toBe(1);
  await page.mouse.click(cx + 40, cy + 40);
  await expect.poll(() => hook(page, () => (window as any).__wsEditor.itemCount())).toBe(2);
});
