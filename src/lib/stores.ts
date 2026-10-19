import { writable, get } from 'svelte/store';
import type { Capture, CaptureOutcome, RecordingState } from '$lib/types';
import { ipcInvoke, normalizeCaptures } from '$lib/ipc';

export type View = 'gallery' | 'editor' | 'video';

export const captures = writable<Capture[]>([]);
export const activeItem = writable<Capture | null>(null);
export const view = writable<View>('gallery');
export const recording = writable<RecordingState>({ status: 'idle' });
export const recordingError = writable('');
export const settingsOpen = writable<boolean>(false);
export const capturePanelOpen = writable<boolean>(false);
export const captureError = writable<string>('');
/** Paths selected in the filmstrip. Kept separate from activeItem so a group
 * can be operated on while one member remains the editor preview. */
export const selectedCapturePaths = writable<string[]>([]);
/** Pinned capture paths (filmstrip pin affordance). */
export const pinned = writable<string[]>([]);
/** Editor autosave status — drives the toolbar indicator ('error' = the last
 *  save failed and the on-disk file does NOT reflect the canvas). */
export const autosaveState = writable<'saved' | 'saving' | 'error'>('saved');

export async function loadLibrary(): Promise<void> {
  const before = new Set(get(captures).map(c => c.path));
  const caps = await ipcInvoke<Capture[]>('list_library');
  const normalized = await normalizeCaptures(caps);
  // A capture may complete while a watcher scan is in flight. Preserve files
  // inserted after this scan began so stale results cannot remove the new shot.
  const inserted = get(captures).filter(c => !before.has(c.path) && !normalized.some(n => n.path === c.path));
  captures.set([...inserted, ...normalized]);
  const available = new Set(get(captures).map((c) => c.path));
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

export const importBusy = writable(false);
export const importError = writable('');

/** Import a private library copy and open it for editing. */
export async function importPaths(paths: string[]): Promise<void> {
  if (!paths.length || get(importBusy)) return;
  importBusy.set(true);
  importError.set('');
  try {
    const imported = await ipcInvoke<string[]>('import_files', { paths });
    await loadLibrary();
    const items = get(captures).filter(c => imported.includes(c.path));
    const first = get(captures).find(c => c.path === imported[0]);
    if (first) {
      activeItem.set(first);
      view.set(first.kind === 'video' ? 'video' : 'editor');
      selectedCapturePaths.set(items.map(c => c.path));
    }
  } catch (e) {
    importError.set(e instanceof Error ? e.message : String(e));
  } finally {
    importBusy.set(false);
  }
}

export async function chooseImport(): Promise<void> {
  if (get(importBusy)) return;
  try {
    await importPaths(await ipcInvoke<string[]>('pick_import_files'));
  } catch (e) {
    importError.set(e instanceof Error ? e.message : String(e));
  }
}

// All modern capture entry points share the same completion path. Selection
// and the editor target must agree before clipboard work starts.
let completionQueue: Promise<void> = Promise.resolve();
export function completeCapture(outcome: CaptureOutcome): Promise<void> {
  const complete = async () => {
    const [justTaken] = await normalizeCaptures([outcome.capture]);
    if (!justTaken) return;
    captures.update((items) => [justTaken, ...items.filter((c) => c.path !== justTaken.path)]);
    activeItem.set(justTaken);
    selectedCapturePaths.set([justTaken.path]);
    view.set(outcome.showPreview ? 'editor' : 'gallery');
    if (outcome.copyAfterCapture) {
      try {
        const copied = await ipcInvoke<boolean>('copy_image', { path: justTaken.path });
        if (!copied) throw new Error('clipboard did not accept the image');
      } catch (e) {
        captureError.set(`Screenshot saved, but copying to the clipboard failed: ${String(e)}`);
      }
    }
  };
  completionQueue = completionQueue.then(complete, complete);
  return completionQueue;
}

export async function takeCapture(mode: 'region' | 'fullscreen' | 'window'): Promise<void> {
  const cmd = `capture_${mode}`;
  captureError.set('');
  try {
    const outcome = await ipcInvoke<CaptureOutcome>(cmd);
    await completeCapture(outcome);
  } catch (e) {
    const message = e instanceof Error ? e.message : String(e);
    if (/cancel(?:led|ed)?/i.test(message)) return;
    console.error('capture failed', e);
    captureError.set(message);
  }
}
