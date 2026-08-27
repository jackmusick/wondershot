import { writable, get } from 'svelte/store';
import type { Capture, CaptureOutcome, RecordingState } from '$lib/types';
import { ipcInvoke, normalizeCaptures } from '$lib/ipc';

export type View = 'gallery' | 'editor' | 'video';

export const captures = writable<Capture[]>([]);
export const activeItem = writable<Capture | null>(null);
export const view = writable<View>('gallery');
export const recording = writable<RecordingState>({ status: 'idle' });
export const settingsOpen = writable<boolean>(false);
export const capturePanelOpen = writable<boolean>(false);
/** Paths selected in the filmstrip. Kept separate from activeItem so a group
 * can be operated on while one member remains the editor preview. */
export const selectedCapturePaths = writable<string[]>([]);
/** Pinned capture paths (filmstrip pin affordance). */
export const pinned = writable<string[]>([]);
/** Editor autosave status — drives the toolbar indicator ('error' = the last
 *  save failed and the on-disk file does NOT reflect the canvas). */
export const autosaveState = writable<'saved' | 'saving' | 'error'>('saved');

export async function loadLibrary(): Promise<void> {
  const caps = await ipcInvoke<Capture[]>('list_library');
  const normalized = await normalizeCaptures(caps);
  captures.set(normalized);
  const available = new Set(normalized.map((c) => c.path));
  selectedCapturePaths.update((paths) => paths.filter((path) => available.has(path)));
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
export async function trashItems(items: Capture[]): Promise<void> {
  if (items.length === 0) return;
  const removed = new Set<string>();
  const failures: unknown[] = [];
  for (const item of items) {
    try {
      await ipcInvoke('trash_item', { path: item.path });
      removed.add(item.path);
    } catch (e) {
      failures.push(e);
    }
  }

  const active = get(activeItem);
  if (active && removed.has(active.path)) activeItem.set(null);
  selectedCapturePaths.update((paths) => paths.filter((path) => !removed.has(path)));
  try {
    await loadLibrary();
  } catch (e) {
    failures.push(e);
  }
  if (failures.length > 0) console.error('trash failed', failures);
}

/** Move one library item to the trash (filmstrip hover-delete). */
export async function trashItem(c: Capture): Promise<void> {
  await trashItems([c]);
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
    const outcome = await ipcInvoke<CaptureOutcome>(cmd);
    const [justTaken] = await normalizeCaptures([outcome.capture]);
    if (!justTaken) return;

    // Capture completion is incremental: inserting one known file avoids two
    // immediate full directory scans (and the watcher provides reconciliation
    // for genuinely external changes).
    captures.update((items) => [justTaken, ...items.filter((c) => c.path !== justTaken.path)]);
    activeItem.set(justTaken);
    view.set(outcome.showPreview ? 'editor' : 'gallery');

    // Clipboard encoding can be comparatively expensive. It must not hold up
    // the first usable preview frame.
    if (outcome.copyAfterCapture) {
      void ipcInvoke('copy_image', { path: justTaken.path }).catch((e) => {
        console.error('copy-after-capture failed', e);
      });
    }
  } catch (e) {
    console.error('capture failed', e);
  }
}
