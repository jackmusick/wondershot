import { ipcInvoke } from '$lib/ipc';

export type ScreenCapturePermission = {
  required: boolean;
  granted: boolean;
  canRequest: boolean;
};

export async function screenCapturePermissionStatus(): Promise<ScreenCapturePermission> {
  return ipcInvoke<ScreenCapturePermission>('screen_capture_permission_status');
}

export async function requestScreenCapturePermission(): Promise<ScreenCapturePermission> {
  return ipcInvoke<ScreenCapturePermission>('request_screen_capture_permission');
}

export async function openScreenCaptureSettings(): Promise<void> {
  await ipcInvoke('open_screen_capture_settings');
}

export function screenCaptureBlocked(permission: ScreenCapturePermission | null): boolean {
  return permission?.required === true && permission.granted !== true;
}
