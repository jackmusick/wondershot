import { test, expect } from '@playwright/test';

for (const theme of ['dark', 'light'] as const) {
  for (const width of [1280, 560]) {
    test(`Bifrost ${theme} at ${width}: editor, focus, settings and capture`, async ({ page }) => {
      const errors: string[] = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.setViewportSize({ width, height: 800 });
      await page.addInitScript(() => Object.defineProperty(navigator, 'platform', { get: () => 'MacIntel' }));
      await page.goto('/');
      await expect(page).toHaveTitle('Wondershot');
      await page.getByRole('button', { name: /Screenshot 14:02/ }).click();
      await expect(page.locator('[data-editor-ready="true"]')).toBeVisible();
      await page.evaluate(t => document.documentElement.setAttribute('data-theme', t), theme);
      await page.evaluate(() => document.fonts.ready);
      expect(await page.evaluate(() => document.fonts.check('13px Inter'))).toBe(true);
      const primary = theme === 'dark' ? 'rgb(47, 212, 212)' : 'rgb(8, 127, 134)';
      const canvas = theme === 'dark' ? 'rgb(8, 9, 11)' : 'rgb(247, 249, 250)';
      const header = page.getByRole('banner', { name: 'Main Toolbar' });
      const capture = header.getByRole('button', { name: 'Capture', exact: true });
      await expect(capture).toHaveCSS('background-color', 'rgba(0, 0, 0, 0)');
      await expect(capture).toHaveCSS('color', primary);
      await expect(page.locator('body')).toHaveCSS('background-color', canvas);
      expect(await header.evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
      await page.keyboard.press('Tab');
      await capture.focus();
      await expect(capture).toHaveCSS('outline-width', '2px');
      await page.screenshot({ path: `artifacts/ui/bifrost-editor-${theme}-${width}.png` });
      await page.keyboard.press('Meta+,');
      const dialog = page.getByRole('dialog', { name: 'Settings', exact: true });
      await expect(dialog).toBeVisible();
      for (const tab of ['Capture', 'Recording', 'Output', 'Sharing', 'AI', 'General']) {
        await dialog.getByRole('tab', { name: tab, exact: true }).click();
        expect(await dialog.locator('.panel').evaluate(el => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
        if (tab === 'AI') await expect(dialog.locator('input[type="password"]')).toHaveCSS('height', '32px');
      }
      await expect(dialog.locator('input[type="text"]').first()).toHaveCSS('height', '32px');
      await dialog.getByRole('button', { name: 'Cancel', exact: true }).click();
      await expect(dialog).toBeHidden();
      await capture.click();
      await expect(page.getByRole('button', { name: 'Full screen', exact: true })).toBeVisible();
      await page.getByRole('button', { name: 'Full screen', exact: true }).click();
      await expect(page.locator('.card[aria-pressed="true"]')).toHaveCount(1);
      await expect(page.locator('[data-editor-ready="true"]')).toBeVisible();
      expect(errors).toEqual([]);
      await page.emulateMedia({ reducedMotion: 'reduce' });
      expect(await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue('--bf-motion-disclosure').trim())).toBe('0ms');
    });
  }
}
