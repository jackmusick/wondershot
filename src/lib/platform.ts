import { ipcInvoke } from '$lib/ipc';

export type PlatformName = 'linux' | 'windows' | 'macos' | 'unknown' | string;

let cachedPlatform: PlatformName | undefined;

export const USE_MOCK =
  import.meta.env.VITE_MOCK_IPC === '1' ||
  typeof (globalThis as any).__TAURI_INTERNALS__ === 'undefined';

export async function currentPlatform(): Promise<PlatformName> {
  if (USE_MOCK) return 'unknown';
  if (!cachedPlatform) {
    try {
      cachedPlatform = await ipcInvoke<string>('platform');
    } catch {
      cachedPlatform = 'unknown';
    }
  }
  return cachedPlatform;
}

export async function usesBrowserMedia(): Promise<boolean> {
  const platform = await currentPlatform();
  // Browser media prompts feel wrong in a desktop capture app. Windows uses a
  // native backend; macOS can opt in here only if we decide WebKit permission UI
  // is acceptable there.
  return shouldUseBrowserMedia(platform);
}

export async function usesNativeRecorder(): Promise<boolean> {
  const platform = await currentPlatform();
  return isNativeRecorderPlatform(platform);
}

export function shouldUseBrowserMedia(_platform: PlatformName): boolean {
  return false;
}

export function isNativeRecorderPlatform(platform: PlatformName): boolean {
  return platform === 'linux' || platform === 'windows';
}
