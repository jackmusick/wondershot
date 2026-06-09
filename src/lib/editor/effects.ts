import { writable } from 'svelte/store';

/**
 * Image-level effects applied at save time (T14 writes these into the sidecar
 * `effects` dict). Held here as UI state by the EditorToolbar; live preview via
 * the Rust `apply_effects` is deferred — for now this only carries the values.
 */
export interface Effects {
  rounded: boolean;
  corner_radius: number;
  fade: boolean;
  fade_height: number;
}

export const effects = writable<Effects>({
  rounded: false,
  corner_radius: 12,
  fade: false,
  fade_height: 64,
});
