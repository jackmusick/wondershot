import { writable } from 'svelte/store';
import type { Capture, RecordingState } from '$lib/types';
import { ipcInvoke } from '$lib/ipc';

export type View = 'gallery' | 'editor' | 'video';

export const captures = writable<Capture[]>([]);
export const activeItem = writable<Capture | null>(null);
export const view = writable<View>('gallery');
export const recording = writable<RecordingState>({ status: 'idle' });

export async function loadLibrary(): Promise<void> {
  const caps = await ipcInvoke<Capture[]>('list_library');
  captures.set(caps);
}
