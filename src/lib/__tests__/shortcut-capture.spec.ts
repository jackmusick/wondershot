import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { get } from 'svelte/store';

const { invoke, platform } = vi.hoisted(() => ({ invoke: vi.fn(), platform: vi.fn() }));
vi.mock('$lib/ipc', () => ({ ipcInvoke: invoke }));
vi.mock('$lib/platform', () => ({ currentPlatform: platform }));

describe('shortcut capture routing', () => {
  test('global capture shortcuts use the same direct picker route as the header button', () => {
    const page = readFileSync('src/routes/+page.svelte', 'utf8');
    const header = readFileSync('src/lib/components/CaptureHeader.svelte', 'utf8');

    expect(page).toContain("import { openCapturePicker } from '$lib/capture/openCapture'");
    expect(page).toContain("ipcListen('cli://capture', () => void openCapturePicker())");
    expect(page).not.toContain("ipcListen('cli://capture', () => void ipcInvoke('show_capture_window'))");

    expect(header).toContain("import { openCapturePicker } from '$lib/capture/openCapture'");
    expect(header).toContain('onclick={openCapturePicker}');
  });

});

describe('capture permission and backend routing', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.stubGlobal('__TAURI_INTERNALS__', {});
    invoke.mockReset();
    platform.mockReset();
    platform.mockResolvedValue('macos');
    invoke.mockResolvedValue({ required: true, granted: true, canRequest: true });
  });

  afterEach(() => vi.unstubAllGlobals());

  test('macOS validates permission before opening the unified backend picker', async () => {
    const { openCapturePicker } = await import('$lib/capture/openCapture');
    await openCapturePicker();

    expect(invoke.mock.calls.map(([command]) => command)).toEqual([
      'screen_capture_permission_status',
      'show_capture_window',
    ]);
  });

  test('denied macOS permission opens the permission panel without starting capture', async () => {
    invoke.mockResolvedValue({ required: true, granted: false, canRequest: true });
    const { openCapturePicker } = await import('$lib/capture/openCapture');
    const { capturePanelOpen } = await import('$lib/stores');
    await openCapturePicker();

    expect(get(capturePanelOpen)).toBe(true);
    expect(invoke.mock.calls.map(([command]) => command)).toEqual(['screen_capture_permission_status']);
  });

  test.each(['linux', 'windows'])('%s uses the backend capture flow directly', async (os) => {
    platform.mockResolvedValue(os);
    const { openCapturePicker } = await import('$lib/capture/openCapture');
    await openCapturePicker();

    expect(invoke.mock.calls.map(([command]) => command)).toEqual(['show_capture_window']);
  });

  test('browser preview opens the capture panel without invoking native commands', async () => {
    vi.stubGlobal('__TAURI_INTERNALS__', undefined);
    const { openCapturePicker } = await import('$lib/capture/openCapture');
    const { capturePanelOpen } = await import('$lib/stores');
    await openCapturePicker();

    expect(get(capturePanelOpen)).toBe(true);
    expect(invoke).not.toHaveBeenCalled();
  });
});
