import { readFileSync } from 'node:fs';
import { describe, expect, test } from 'vitest';

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

  test('macOS opens the native region picker directly after permission validation', () => {
    const source = readFileSync('src/lib/capture/openCapture.ts', 'utf8');
    const macosIndex = source.indexOf("currentPlatform()) === 'macos'");
    const permissionIndex = source.indexOf('screenCapturePermissionStatus()', macosIndex);
    const pickerIndex = source.indexOf("takeCapture('region')", permissionIndex);
    const fallbackIndex = source.indexOf("ipcInvoke('show_capture_window')", pickerIndex);

    expect(macosIndex).toBeGreaterThan(-1);
    expect(permissionIndex).toBeGreaterThan(macosIndex);
    expect(pickerIndex).toBeGreaterThan(permissionIndex);
    expect(fallbackIndex).toBeGreaterThan(pickerIndex);
  });
});
