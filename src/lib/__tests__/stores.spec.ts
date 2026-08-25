import { beforeEach, describe, it, expect } from 'vitest';
import { get } from 'svelte/store';
import { loadLibrary, takeCapture, captures, activeItem, view } from '$lib/stores';
import { getMockInvocationCount, resetMockInvocationCounts, setMockSettings } from '$lib/ipc.mock';

describe('stores', () => {
  beforeEach(() => resetMockInvocationCounts());

  it('loadLibrary populates captures from ipc', async () => {
    await loadLibrary();
    expect(get(captures).length).toBe(4);
  });
  it('view defaults to gallery', () => {
    view.set('gallery');
    expect(get(view)).toBe('gallery');
  });

  it('inserts a completed capture without rescanning the library', async () => {
    setMockSettings({ copy_after_capture: true, show_gallery_after_capture: true });
    await loadLibrary();
    resetMockInvocationCounts();

    await takeCapture('region');

    expect(getMockInvocationCount('capture_region')).toBe(1);
    expect(getMockInvocationCount('list_library')).toBe(0);
    expect(getMockInvocationCount('copy_image')).toBe(1);
    expect(get(captures)[0].path).toBe(get(activeItem)?.path);
    expect(get(view)).toBe('editor');
  });

  it('honors capture completion preferences without extra work', async () => {
    setMockSettings({ copy_after_capture: false, show_gallery_after_capture: false });
    await loadLibrary();
    resetMockInvocationCounts();

    await takeCapture('window');

    expect(getMockInvocationCount('capture_window')).toBe(1);
    expect(getMockInvocationCount('list_library')).toBe(0);
    expect(getMockInvocationCount('copy_image')).toBe(0);
    expect(get(view)).toBe('gallery');
  });
});
