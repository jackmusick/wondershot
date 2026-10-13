import { ipcInvoke } from '$lib/ipc';
import { currentPlatform, USE_MOCK } from '$lib/platform';

export type NativeRect = [number, number, number, number];

type NativeCaptureFrame = {
  width: number;
  height: number;
  monitors?: Array<{ id: number; x: number; y: number; width: number; height: number }>;
  windows?: Array<{ id: number; title: string; x: number; y: number; width: number; height: number }>;
  pngB64: string;
};

type ScreenCapturePermission = {
  required: boolean;
  granted: boolean;
};

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
  const permission = await ipcInvoke<ScreenCapturePermission>('screen_capture_permission_status');
  if (permission.required && !permission.granted) return undefined;
  const platform = await currentPlatform();

  if (platform === 'macos' && isMacosNativeCaptureMode(mode)) {
    const result = await ipcInvoke<T | null>('macos_native_capture_picker', { mode });
    return result ?? undefined;
  }

  const { WebviewWindow } = await import('@tauri-apps/api/webviewWindow');
  const { emit, listen } = await import('@tauri-apps/api/event');

  await ipcInvoke('prepare_native_capture_picker');
  let frame: NativeCaptureFrame;
  try {
    frame = await ipcInvoke<NativeCaptureFrame>('native_capture_frame_b64');
  } catch (error) {
    await ipcInvoke('finish_native_capture_picker').catch(() => undefined);
    throw error;
  }
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
      unReady?.();
      unPainted?.();
      void ipcInvoke('finish_native_capture_picker');
      resolve(payload);
    };
    let unDone: (() => void) | undefined;
    let unRect: (() => void) | undefined;
    let unCancel: (() => void) | undefined;
    let unReady: (() => void) | undefined;
    let unPainted: (() => void) | undefined;
    listen<string>('region://done', (e) => finish(e.payload as T)).then((un) => (unDone = un));
    listen<NativeRect>('region://rect', (e) => finish(e.payload as T)).then((un) => (unRect = un));
    listen('region://cancel', () => finish()).then((un) => (unCancel = un));
    listen('region://ready', () => {
      void emit('region://frame', frame);
    }).then((un) => (unReady = un));
    listen('region://painted', () => {
      void win.show();
      void win.setFocus();
    }).then((un) => (unPainted = un));

    const win = new WebviewWindow('region-picker', {
      url: `/region-picker?mode=${mode}`,
      maximized: true,
      decorations: false,
      alwaysOnTop: true,
      skipTaskbar: true,
      shadow: false,
      visible: false,
    });
    win.once('tauri://error', (e) => {
      console.error('region picker window error', e);
      finish();
    });
  });
}

function isMacosNativeCaptureMode(
  mode: 'capture' | 'rect' | 'screen-capture' | 'screen-rect' | 'window-capture' | 'window-rect'
): boolean {
  return mode === 'capture' || mode === 'screen-capture' || mode === 'window-capture';
}
