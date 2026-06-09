import { writable } from 'svelte/store';

/**
 * Zoom controls bridge. EditorCanvas owns the Konva stage and registers its
 * zoom functions here on mount (and clears them on destroy); the EditorToolbar
 * reads the store and calls them. Null when no canvas is mounted, so the toolbar
 * buttons no-op gracefully (e.g. before the editor has loaded).
 */
export interface ZoomApi {
  zoomIn: () => void;
  zoomOut: () => void;
  zoomActual: () => void;
  zoomFit: () => void;
}

export const zoomApi = writable<ZoomApi | null>(null);

/**
 * Save bridge, mirroring zoomApi. EditorCanvas registers its async `save()`
 * here on mount; the EditorToolbar's Save button calls it. Null when no canvas
 * is mounted, so the button no-ops gracefully.
 */
export const saveApi = writable<(() => Promise<void>) | null>(null);
