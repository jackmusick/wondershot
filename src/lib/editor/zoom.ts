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
 * Live view info for the zoom bar below the canvas: the base image's pixel
 * resolution and the current zoom factor. EditorCanvas updates it on load and
 * on every zoom/fit; null when no canvas is mounted.
 */
export interface ViewInfo {
  width: number;
  height: number;
  zoom: number;
}

export const viewInfo = writable<ViewInfo | null>(null);

/**
 * Save bridge, mirroring zoomApi. EditorCanvas registers its async `save()`
 * here on mount; the EditorToolbar's Save button calls it. Null when no canvas
 * is mounted, so the button no-ops gracefully.
 */
export const saveApi = writable<(() => Promise<void>) | null>(null);

/**
 * Background-removal bridge, mirroring saveApi. EditorCanvas registers its async
 * `removeBackground()` here on mount; the EditorToolbar's "Remove BG" button
 * calls it. `available` reflects whether the u2net model is installed (gates the
 * button). Null when no canvas is mounted, so the button no-ops gracefully.
 */
export interface BgApi {
  removeBackground: () => Promise<void>;
  available: boolean;
}

export const bgApi = writable<BgApi | null>(null);
