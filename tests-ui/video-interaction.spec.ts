import { test, expect } from '@playwright/test';
import type { Page } from '@playwright/test';

const browserErrors = new WeakMap<Page, string[]>();

test.beforeEach(async ({ page }) => {
  const errors: string[] = []; browserErrors.set(page, errors);
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
  await page.goto('/screen?screen=video');
  await page.waitForFunction(() => (document.querySelector('video')?.duration ?? 0) > 0);
});
test.afterEach(async ({ page }) => { expect(browserErrors.get(page)).toEqual([]); });
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
  expect((await lastCall(page,'apply_blur')).args.redactions).toHaveLength(1);
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

async function drawBlur(page: import('@playwright/test').Page, fraction: number) {
  const box = await page.locator('.overlay').boundingBox(); if (!box) throw new Error('missing overlay');
  const x = box.x + box.width * fraction, y = box.y + box.height * .4;
  await page.mouse.move(x,y); await page.mouse.down();
  await page.mouse.move(x + box.width * .08,y + box.height * .1,{steps:8}); await page.mouse.up();
}
async function lastCall(page: import('@playwright/test').Page, command: string) {
  return page.evaluate(cmd => (window as any).__wsMockCalls.filter((c:any) => c.command === cmd).at(-1),command);
}

test('select, move, resize, edit and delete a specific blur layer with undo and persistence', async ({ page }) => {
  await drawBlur(page,.3); await drawBlur(page,.6);
  await expect(page.getByRole('button',{name:'Blur 2',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Blur 1',exact:true}).click();
  await expect(page.getByRole('button',{name:'Blur 1',exact:true})).toHaveAttribute('aria-pressed','true');
  const first = page.getByRole('button',{name:'Blur region 1',exact:true});
  const box = await first.boundingBox(); if (!box) throw new Error('missing first region');
  const xInput = page.getByRole('spinbutton',{name:'Selected blur X',exact:true});
  const originalX = Number(await xInput.inputValue());
  await page.mouse.move(box.x + box.width/2,box.y + box.height/2); await page.mouse.down();
  await page.mouse.move(box.x + box.width/2+35,box.y+box.height/2+15,{steps:8}); await page.mouse.up();
  await expect.poll(async () => Number(await xInput.inputValue())).toBeGreaterThan(originalX);
  const width = page.getByRole('spinbutton',{name:'Selected blur Width',exact:true});
  const originalWidth = Number(await width.inputValue());
  const handle = await page.getByRole('button',{name:'Resize blur region 1',exact:true}).boundingBox(); if (!handle) throw new Error('missing resize handle');
  await page.mouse.move(handle.x+handle.width/2,handle.y+handle.height/2); await page.mouse.down();
  await page.mouse.move(handle.x+handle.width/2+45,handle.y+handle.height/2+20,{steps:8}); await page.mouse.up();
  await expect.poll(async () => Number(await width.inputValue())).toBeGreaterThan(originalWidth);
  await page.getByRole('spinbutton',{name:'Blur 1 start',exact:true}).fill('0.5'); await page.keyboard.press('Tab');
  await page.getByRole('spinbutton',{name:'Blur 1 end',exact:true}).fill('1.5'); await page.keyboard.press('Tab');
  const strength = page.getByRole('slider',{name:'Blur strength',exact:true}); await strength.focus(); await strength.press('Home');
  await page.getByRole('button',{name:'Apply blur',exact:true}).click();
  const call = await lastCall(page,'apply_blur');
  expect(call.args.redactions[0]).toMatchObject({start:.5,end:1.5,blur:1});
  expect(call.args.redactions[1]).toMatchObject({start:0,end:2,blur:14});
  await page.screenshot({ path: 'artifacts/ui/video-layers.png' });
  await page.getByRole('button',{name:'Delete blur 1',exact:true}).click();
  await expect(page.getByRole('button',{name:'Blur 2',exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'Undo',exact:true}).click();
  await expect(page.getByRole('button',{name:'Blur 2',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Redo',exact:true}).click();
  await expect(page.getByRole('button',{name:'Blur 2',exact:true})).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole('button',{name:'Blur 1',exact:true})).toBeVisible();
  await expect(page.getByRole('spinbutton',{name:'Blur 1 start',exact:true})).toHaveValue('0');
});

test('drag a timeline range, adjust handles, save a trim and remove a section', async ({ page }) => {
  await page.getByRole('button',{name:'Trim / Cut',exact:true}).click();
  const bar = await page.locator('.rangebar').boundingBox(); if (!bar) throw new Error('missing range');
  await page.mouse.move(bar.x+bar.width*.25,bar.y+12); await page.mouse.down();
  await page.mouse.move(bar.x+bar.width*.75,bar.y+12,{steps:8}); await page.mouse.up();
  await expect(page.getByLabel('Selection start')).toHaveValue('1');
  await expect(page.getByLabel('Selection end')).toHaveValue('3');
  await page.mouse.move(bar.x+bar.width*.25,bar.y+12); await page.mouse.down();
  await page.mouse.move(bar.x+bar.width*.125,bar.y+12,{steps:8}); await page.mouse.up();
  await expect(page.getByLabel('Selection start')).toHaveValue('0.5');
  await page.screenshot({ path: 'artifacts/ui/video-range.png' });
  await page.getByRole('button',{name:'Save trim',exact:true}).click();
  await expect(page.getByText('Trim saved as a new video', {exact:true})).toBeVisible();
  expect((await lastCall(page,'trim_video')).args).toMatchObject({start:.5,end:3,reencode:true});
  await page.getByRole('button',{name:'Trim / Cut',exact:true}).click();
  await page.getByLabel('Selection start').fill('1'); await page.getByLabel('Selection end').fill('2');
  await page.getByRole('button',{name:'Remove selection',exact:true}).click();
  await expect(page.getByText('Section removed — saved as a new video',{exact:true})).toBeVisible();
  expect((await lastCall(page,'cut_video')).args).toMatchObject({start:1,end:2});
});

test('invalid ranges disable editing and grab frame uses the playhead', async ({ page }) => {
  await page.getByRole('button',{name:'Trim / Cut',exact:true}).click();
  await expect(page.getByRole('button',{name:'Remove selection',exact:true})).toBeDisabled();
  await page.getByLabel('Selection start').fill('3'); await page.getByLabel('Selection end').fill('1');
  await expect(page.getByRole('button',{name:'Save trim',exact:true})).toBeDisabled();
  await expect(page.getByRole('button',{name:'Remove selection',exact:true})).toBeDisabled();
  await page.getByRole('button',{name:'Cancel',exact:true}).click();
  const seek = page.getByRole('slider',{name:'Seek',exact:true}); await seek.focus(); await seek.press('End');
  await page.getByRole('button',{name:'Grab frame',exact:true}).click();
  await expect(page.getByText('Frame saved',{exact:true})).toBeVisible();
  expect((await lastCall(page,'grab_frame')).args.position).toBeCloseTo(3.95);
});

test('exports select the new library result while the original retains editable layers', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('button',{name:/Recording 11:20/}).click();
  await page.waitForFunction(() => (document.querySelector('video')?.duration ?? 0) > 0);
  await drawBlur(page,.4);
  await page.getByRole('button',{name:'Grab frame',exact:true}).click();
  await expect(page.getByText('Apply blur layers before grabbing a frame',{exact:true})).toBeVisible();
  expect(await lastCall(page,'grab_frame')).toBeUndefined();
  await page.getByRole('button',{name:'Apply blur',exact:true}).click();
  await expect(page.getByRole('button',{name:'Blur 1',exact:true})).toHaveCount(0);
  await expect(page.getByRole('button',{name:/redacted result/})).toBeVisible();
  await page.getByRole('button',{name:/Recording 11:20/}).click();
  await expect(page.getByRole('button',{name:'Blur 1',exact:true})).toBeVisible();
  await page.waitForFunction(() => (document.querySelector('video')?.duration ?? 0) > 0);
  // Restored layer pixels must be scaled to the decoded video, not 1:1.
  const region = await page.getByRole('button',{name:'Blur region 1',exact:true}).boundingBox();
  const pixels = Number(await page.getByRole('spinbutton',{name:'Selected blur Width',exact:true}).inputValue());
  expect(region!.width).toBeGreaterThan(pixels * 1.5);
  await page.getByRole('button',{name:'Delete blur 1',exact:true}).click();
  await page.getByRole('button',{name:'Grab frame',exact:true}).click();
  await expect(page.getByRole('button',{name:'Arrow',exact:true})).toBeVisible();
});
