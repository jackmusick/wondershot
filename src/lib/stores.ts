import { writable, get } from 'svelte/store';
import type { Capture, RecordingState } from '$lib/types';
import { ipcInvoke, normalizeCaptures } from '$lib/ipc';

export type View = 'gallery' | 'editor' | 'video';

export const captures = writable<Capture[]>([]);
export const activeItem = writable<Capture | null>(null);
export const view = writable<View>('gallery');
export const recording = writable<RecordingState>({ status: 'idle' });

export async function loadLibrary(): Promise<void> {
  const caps = await ipcInvoke<Capture[]>('list_library');
  captures.set(await normalizeCaptures(caps));
}

export async function takeCapture(mode: 'region' | 'fullscreen' | 'window'): Promise<void> {
  const cmd = `capture_${mode}`;
  try {
    const path = await ipcInvoke<string>(cmd);
    await loadLibrary();
    // select the newest item (the one just captured), best-effort by path match
    const list = get(captures);
    const justTaken = list.find((c) => c.path === path) ?? list[0];
    if (justTaken) activeItem.set(justTaken);
  } catch (e) {
    console.error('capture failed', e);
  }
}
