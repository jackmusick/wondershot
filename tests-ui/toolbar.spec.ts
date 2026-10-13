import { test, expect } from '@playwright/test';

async function image(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page.getByRole('button',{name:/Screenshot 14:02/}).click();
  await page.waitForFunction(() => (window as any).__wsEditor?.ready());
}

test('image actions share one row with Capture and Camera and overflow on resize', async ({page}) => {
  await page.setViewportSize({width:860,height:800});
  await image(page);
  const header = page.getByRole('banner',{name:'Main Toolbar'});
  const tools = page.getByRole('toolbar',{name:'Image Editing Tools'});
  await expect(header).toHaveCSS('height','60px');
  expect(await header.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
  const canvas = await page.locator('.editor-canvas').boundingBox();
  const row = await header.boundingBox();
  expect(canvas!.y).toBeCloseTo(row!.y + row!.height,0);
  for (const name of ['Capture','Camera']) {
    const button = header.getByRole('button',{name,exact:true});
    const icon = await button.locator('svg').boundingBox();
    const label = await button.locator('span').boundingBox();
    expect(icon!.y + icon!.height).toBeLessThan(label!.y);
  }
  await expect(page.getByText('Auto-saved',{exact:true})).toHaveCount(0);
  const more = tools.getByRole('button',{name:'More Tools',exact:true});
  await more.click();
  const menu = tools.getByRole('group',{name:'More Tools'});
  await expect(menu).toBeVisible();
  await menu.getByRole('button',{name:'Cut |',exact:true}).click();
  await expect(menu).toBeHidden();
  await more.click();
  await expect(menu.getByRole('button',{name:'Cut |',exact:true})).toHaveAttribute('aria-pressed','true');
  await page.keyboard.press('ArrowDown'); await page.keyboard.press('Escape');
  await expect(menu).toBeHidden(); await expect(more).toBeFocused();
  await more.click();
  await expect(menu.getByRole('button',{name:'Cut |',exact:true})).toBeFocused();
  await page.setViewportSize({width:1920,height:800});
  await expect(menu).toBeHidden(); await expect(more).toHaveCount(0);
  await expect(tools.getByRole('button',{name:'Cut |',exact:true})).toBeVisible();
  await expect(tools.getByRole('button',{name:'Cut |',exact:true})).toHaveAttribute('aria-pressed','true');
  await expect(tools.getByRole('button',{name:'Cut |',exact:true})).toBeFocused();
  await page.keyboard.press('ArrowRight');
  await expect(tools.getByRole('button',{name:'Cut —',exact:true})).toBeFocused();
  await page.setViewportSize({width:560,height:800});
  expect(await header.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
  await expect(tools.getByRole('button',{name:'More Tools',exact:true})).toBeFocused();
  await tools.getByRole('button',{name:'More Tools',exact:true}).click();
  await page.getByRole('button',{name:'Camera',exact:true}).click();
  await expect(menu).toBeHidden();
  await page.screenshot({path:'artifacts/ui/unified-toolbar-image.png'});
});

test('video overflow actions still export and configuration stays on the right', async ({page}) => {
  await page.setViewportSize({width:440,height:800});
  await page.goto('/');
  await page.getByRole('button',{name:/Recording 11:20/}).click();
  await page.waitForFunction(() => (document.querySelector('video')?.duration ?? 0)>0);
  const header = page.getByRole('banner',{name:'Main Toolbar'});
  const tools = header.getByRole('toolbar',{name:'Video Editing Tools'});
  await tools.getByRole('button',{name:'More Tools',exact:true}).click();
  const menu = tools.getByRole('group',{name:'More Tools'});
  await menu.getByRole('button',{name:'Export GIF…',exact:true}).click();
  await expect(page.getByRole('complementary',{name:'Video properties'})).toBeVisible();
  await expect(menu).toBeHidden();
  await tools.getByRole('button',{name:'More Tools',exact:true}).click();
  await menu.getByRole('button',{name:'Export GIF',exact:true}).click();
  await expect(page.locator('.gif-dialog')).toHaveCount(0);
  await expect(page.getByText(/GIF exported:/)).toBeVisible();
  expect(await header.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
  await page.setViewportSize({width:1280,height:800});
  await expect(tools.getByRole('button',{name:'Screenshot',exact:true})).toBeVisible();
  await page.screenshot({path:'artifacts/ui/unified-toolbar-video.png'});
});

test('macOS settings have no toolbar button and Command-comma opens the dialog', async ({page}) => {
  await page.addInitScript(() => Object.defineProperty(navigator,'platform',{get:()=>'MacIntel'}));
  await page.goto('/');
  await expect(page.getByRole('button',{name:'Settings',exact:true})).toHaveCount(0);
  await expect(page.getByRole('button',{name:/Screenshot 14:02/})).toBeVisible();
  await page.keyboard.press('Meta+,');
  await expect(page.locator('[data-settings-ready="true"]')).toBeVisible();
});
