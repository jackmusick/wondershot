import { mockInvoke } from '$lib/ipc.mock';
import type { Capture } from '$lib/types';

const USE_MOCK =
  import.meta.env.VITE_MOCK_IPC === '1' ||
  typeof (globalThis as any).__TAURI_INTERNALS__ === 'undefined';

/** A webview-loadable src for a file path. Real mode → tauri asset URL; mock → the path as-is. */
export async function assetSrc(path: string): Promise<string> {
  if (USE_MOCK) return path;
  const { convertFileSrc } = await import('@tauri-apps/api/core');
  return convertFileSrc(path);
}

/**
 * A canvas-safe (same-origin) src for an image file: a `data:` URL read via the
 * backend in real mode, the path as-is in mock. The editor must NOT use
 * `assetSrc` for its base image — WebKit treats `asset.localhost` as
 * cross-origin (a plain `Image` never makes a CORS fetch), which taints the
 * Konva canvas and silently breaks `stage.toDataURL()`, and with it save.
 */
export async function imageDataSrc(path: string): Promise<string> {
  if (USE_MOCK) return path;
  const b64 = await ipcInvoke<string>('read_image_b64', { path });
  return `data:image/png;base64,${b64}`;
}

/** Ensure every capture has a loadable `thumbnail` (real list_library omits it). */
export async function normalizeCaptures(caps: Capture[]): Promise<Capture[]> {
  return Promise.all(
    caps.map(async (c) => (c.thumbnail ? c : { ...c, thumbnail: await assetSrc(c.path) }))
  );
}

export async function ipcInvoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  if (USE_MOCK) return mockInvoke(cmd, args) as Promise<T>;
  const { invoke } = await import('@tauri-apps/api/core');
  return invoke<T>(cmd, args);
}

export async function ipcListen<T>(event: string, cb: (payload: T) => void): Promise<() => void> {
  if (USE_MOCK) return () => {};
  const { listen } = await import('@tauri-apps/api/event');
  const un = await listen<T>(event, (e) => cb(e.payload));
  return un;
}

/** Emit an app event to the backend (no-op in mock/browser dev). */
export async function ipcEmit(event: string, payload?: unknown): Promise<void> {
  if (USE_MOCK) return;
  const { emit } = await import('@tauri-apps/api/event');
  await emit(event, payload);
}
