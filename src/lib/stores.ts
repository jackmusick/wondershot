import { writable, get } from 'svelte/store';
import type { Capture, RecordingState } from '$lib/types';
import { ipcInvoke, normalizeCaptures } from '$lib/ipc';

export type View = 'gallery' | 'editor' | 'video';

export const captures = writable<Capture[]>([]);
export const activeItem = writable<Capture | null>(null);
export const view = writable<View>('gallery');
export const recording = writable<RecordingState>({ status: 'idle' });
export const settingsOpen = writable<boolean>(false);
export const capturePanelOpen = writable<boolean>(false);
/** Pinned capture paths (filmstrip pin affordance). */
export const pinned = writable<string[]>([]);
/** Editor autosave status — drives the toolbar indicator ('error' = the last
 *  save failed and the on-disk file does NOT reflect the canvas). */
export const autosaveState = writable<'saved' | 'saving' | 'error'>('saved');

export async function loadLibrary(): Promise<void> {
  const caps = await ipcInvoke<Capture[]>('list_library');
  captures.set(await normalizeCaptures(caps));
  await loadPinned();
}

/** Refresh the pinned-paths list from the backend. */
export async function loadPinned(): Promise<void> {
  try {
    pinned.set((await ipcInvoke<string[]>('list_pinned')) ?? []);
  } catch (e) {
    console.error('loadPinned failed', e);
  }
}

/** Pin / unpin a capture and refresh the list. */
export async function togglePin(c: Capture): Promise<void> {
  const isPinned = get(pinned).includes(c.path);
  try {
    const list = await ipcInvoke<string[]>('set_pinned', { path: c.path, pinned: !isPinned });
    pinned.set(list ?? []);
  } catch (e) {
    console.error('togglePin failed', e);
  }
}

/** Move a library item to the trash (filmstrip hover-delete) + refresh. */
export async function trashItem(c: Capture): Promise<void> {
  try {
    await ipcInvoke('trash_item', { path: c.path });
    if (get(activeItem)?.id === c.id) activeItem.set(null);
    await loadLibrary();
  } catch (e) {
    console.error('trash failed', e);
  }
}

/** Open the editor on a library item by path (CLI `--edit FILE`). */
export async function openEditorByPath(path: string): Promise<void> {
  await loadLibrary();
  const item = get(captures).find((c) => c.path === path);
  if (item) {
    activeItem.set(item);
    view.set('editor');
  }
}

/** Copy files into the library and refresh (CLI `--import F…`). */
export async function importPaths(paths: string[]): Promise<void> {
  try {
    await ipcInvoke<string[]>('import_files', { paths });
    await loadLibrary();
  } catch (e) {
    console.error('import failed', e);
  }
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
