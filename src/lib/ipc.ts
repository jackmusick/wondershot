import { mockInvoke } from '$lib/ipc.mock';
import type { Capture } from '$lib/types';
import { prepareMediaOutput } from '$lib/mediaEdits';

const USE_MOCK =
  import.meta.env.VITE_MOCK_IPC === '1' ||
  typeof (globalThis as any).__TAURI_INTERNALS__ === 'undefined';

/** Keep file-backed previews tied to the on-disk revision. Data URLs already
 * contain their content and must not have a query string appended. */
function previewRevision(src: string, revision: number | string): string {
  if (/^(data|blob):/i.test(src)) return src;
  const hashIndex = src.indexOf('#');
  const url = hashIndex < 0 ? src : src.slice(0, hashIndex);
  const hash = hashIndex < 0 ? '' : src.slice(hashIndex);
  return `${url}${url.includes('?') ? '&' : '?'}revision=${encodeURIComponent(revision)}${hash}`;
}

let imageLoadRevision = 0;

/** A webview-loadable src for a file path. Real mode → tauri asset URL; mock → the path as-is. */
export async function assetSrc(path: string): Promise<string> {
  if (USE_MOCK) return path.startsWith("/mock/") || path.startsWith("/lib/") ? "/fixtures/editor-base.png" : path;
  const { convertFileSrc } = await import('@tauri-apps/api/core');
  return convertFileSrc(path);
}

/**
 * A canvas-safe src for an image file. Images are streamed from the existing
 * loopback server with CORS rather than copied through IPC and expanded by
 * base64. Callers must set `Image.crossOrigin = 'anonymous'` before `src`.
 */
export async function imageDataSrc(path: string): Promise<string> {
  // Editable bases are overwritten at the same path. Reopening an editor must
  // fetch those pixels again even if WebKit still holds the previous image.
  const revision = `${Date.now()}-${++imageLoadRevision}`;
  if (USE_MOCK) {
    const src = path.startsWith('/mock/') || path.startsWith('/lib/') ? '/fixtures/editor-base.png' : path;
    return previewRevision(src, revision);
  }
  const port = await ipcInvoke<number>('media_server_port');
  if (!port) throw new Error('image server unavailable');
  return previewRevision(`http://127.0.0.1:${port}/media?path=${encodeURIComponent(path)}`, revision);
}

/**
 * A `<video>`-playable src for a media file. NOT assetSrc: WebKitGTK plays
 * media through GStreamer, whose HTTP source can't read the asset:// custom
 * scheme (MEDIA_ERR_SRC_NOT_SUPPORTED) — so the backend streams media over a
 * loopback HTTP server with Range support and we point the player there.
 */
export async function mediaSrc(path: string): Promise<string> {
  if (USE_MOCK) return /\.(mp4|webm)$/i.test(path) ? "/fixtures/video.mp4" : path;
  const port = await ipcInvoke<number>('media_server_port');
  if (!port) return assetSrc(path); // server failed to start; degrade
  return `http://127.0.0.1:${port}/media?path=${encodeURIComponent(path)}`;
}

/** Ensure every capture has a loadable `thumbnail` (real list_library omits it).
 *  Images use the asset protocol; videos get an ffmpeg-extracted poster frame
 *  (backend-cached) — an <img> pointed at an .mp4 renders as a broken icon. */
export async function normalizeCaptures(caps: Capture[]): Promise<Capture[]> {
  return Promise.all(
    caps.map(async (c) => {
      if (c.thumbnail) return { ...c, thumbnail: previewRevision(c.thumbnail, c.createdAt) };
      if (c.kind === 'video' && !USE_MOCK) {
        try {
          const b64 = await ipcInvoke<string>('video_thumb', { path: c.path });
          return { ...c, thumbnail: `data:image/png;base64,${b64}` };
        } catch {
          return { ...c, thumbnail: '' }; // filmstrip falls back to a dark card
        }
      }
      return { ...c, thumbnail: previewRevision(await assetSrc(c.path), c.createdAt) };
    })
  );
}

export async function ipcInvoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  if (['copy_image', 'save_image_as', 'share_capture', 'show_in_folder'].includes(cmd) && typeof args?.path === 'string') {
    args = { ...args, path: await prepareMediaOutput(args.path, ipcInvoke) };
  } else if (cmd === 'copy_files' && Array.isArray(args?.paths)) {
    args = { ...args, paths: await Promise.all((args.paths as string[]).map(path => prepareMediaOutput(path, ipcInvoke))) };
  }
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
