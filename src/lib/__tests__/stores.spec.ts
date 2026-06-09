import { describe, it, expect } from 'vitest';
import { get } from 'svelte/store';
import { loadLibrary, captures, view } from '$lib/stores';

describe('stores', () => {
  it('loadLibrary populates captures from ipc', async () => {
    await loadLibrary();
    expect(get(captures).length).toBe(4);
  });
  it('view defaults to gallery', () => {
    expect(get(view)).toBe('gallery');
  });
});
