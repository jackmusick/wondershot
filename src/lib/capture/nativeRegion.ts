import { listen } from '@tauri-apps/api/event';
import { ipcInvoke } from '$lib/ipc';
import { USE_MOCK } from '$lib/platform';

export type NativeRect = [number, number, number, number];

type NativeCaptureCapabilities = {
  regionSelector?: boolean;
  screenSelector?: boolean;
  windowSelector?: boolean;
};

let cachedCapabilities: NativeCaptureCapabilities | undefined;

async function nativeCaptureCapabilities(): Promise<NativeCaptureCapabilities> {
  if (USE_MOCK) return {};
  if (!cachedCapabilities) {
    try {
      cachedCapabilities = await ipcInvoke<NativeCaptureCapabilities>('native_capture_capabilities');
    } catch {
      cachedCapabilities = {};
    }
  }
  return cachedCapabilities;
}

export async function supportsNativeRegionPicker(): Promise<boolean> {
  if (USE_MOCK) return false;
  return (await nativeCaptureCapabilities()).regionSelector === true;
}

export async function supportsNativeScreenPicker(): Promise<boolean> {
  if (USE_MOCK) return false;
  return (await nativeCaptureCapabilities()).screenSelector === true;
}

export async function supportsNativeWindowPicker(): Promise<boolean> {
  if (USE_MOCK) return false;
  return (await nativeCaptureCapabilities()).windowSelector === true;
}

export async function selectNativeRegion(): Promise<string | undefined> {
  return openNativeRegionPicker<string>('capture');
}

export async function selectNativeRegionRect(): Promise<NativeRect | undefined> {
  return openNativeRegionPicker<NativeRect>('rect');
}

export async function selectNativeScreen(): Promise<string | undefined> {
  return openNativeRegionPicker<string>('screen-capture');
}

export async function selectNativeScreenRect(): Promise<NativeRect | undefined> {
  return openNativeRegionPicker<NativeRect>('screen-rect');
}

export async function selectNativeWindow(): Promise<string | undefined> {
  return openNativeRegionPicker<string>('window-capture');
}

export async function selectNativeWindowRect(): Promise<NativeRect | undefined> {
  return openNativeRegionPicker<NativeRect>('window-rect');
}

async function openNativeRegionPicker<T>(
  mode: 'capture' | 'rect' | 'screen-capture' | 'screen-rect' | 'window-capture' | 'window-rect'
): Promise<T | undefined> {
  const { WebviewWindow } = await import('@tauri-apps/api/webviewWindow');
  const existing = await WebviewWindow.getByLabel('region-picker');
  if (existing) {
    try {
      await existing.close();
    } catch {
      // ignore stale selector cleanup
    }
  }

  return new Promise<T | undefined>((resolve) => {
    let settled = false;
    const finish = (payload?: T) => {
      if (settled) return;
      settled = true;
      unDone?.();
      unRect?.();
      unCancel?.();
      resolve(payload);
    };
    let unDone: (() => void) | undefined;
    let unRect: (() => void) | undefined;
    let unCancel: (() => void) | undefined;
    listen<string>('region://done', (e) => finish(e.payload as T)).then((un) => (unDone = un));
    listen<NativeRect>('region://rect', (e) => finish(e.payload as T)).then((un) => (unRect = un));
    listen('region://cancel', () => finish()).then((un) => (unCancel = un));

    const win = new WebviewWindow('region-picker', {
      url: `/region-picker?mode=${mode}`,
      fullscreen: true,
      decorations: false,
      alwaysOnTop: true,
      skipTaskbar: true,
      shadow: false,
      visible: true,
    });
    win.once('tauri://error', () => finish());
  });
}
