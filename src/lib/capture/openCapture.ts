import { screenCaptureBlocked, screenCapturePermissionStatus } from '$lib/capture/permissions';
import { ipcInvoke } from '$lib/ipc';
import { currentPlatform } from '$lib/platform';
import { capturePanelOpen } from '$lib/stores';

const USE_MOCK = typeof (globalThis as any).__TAURI_INTERNALS__ === 'undefined';

export async function openCapturePicker() {
  if (USE_MOCK) {
    capturePanelOpen.set(true);
    return;
  }
  try {
    if ((await currentPlatform()) === 'macos') {
      const permission = await screenCapturePermissionStatus();
      if (screenCaptureBlocked(permission)) {
        capturePanelOpen.set(true);
        return;
      }
    }
    await ipcInvoke('show_capture_window');
  } catch (e) {
    console.error('capture failed', e);
  }
}
