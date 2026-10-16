import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
const invoke = vi.hoisted(() => vi.fn());
vi.mock('$lib/ipc', () => ({ ipcInvoke: invoke, normalizeCaptures: async (caps: unknown) => caps }));
import { activeItem, captures, importBusy, importError, importPaths, selectedCapturePaths, view } from '$lib/stores';

describe('media import', () => {
  beforeEach(() => {
    invoke.mockReset();
    activeItem.set(null); captures.set([]); importBusy.set(false); importError.set('');
  });
  it('opens the backend destination and selects the imported batch', async () => {
    const image = { id: '1', path: '/library/photo-1.png', kind: 'image' };
    const video = { id: '2', path: '/library/obs-editable.mp4', kind: 'video' };
    invoke.mockImplementation(async (cmd: string) => {
      if (cmd === 'import_files') return [image.path, video.path];
      if (cmd === 'list_library') return [video, image];
      return [];
    });
    await importPaths(['/source/photo.png', '/source/obs.mkv']);
    expect(get(activeItem)).toEqual(image);
    expect(get(view)).toBe('editor');
    expect(get(selectedCapturePaths)).toEqual([video.path, image.path]);
    expect(get(importBusy)).toBe(false);
  });
  it('shows backend failures and preserves the current editor', async () => {
    const existing = { id: '1', path: '/library/photo.png', kind: 'image' as const, title: 'photo', createdAt: 0, thumbnail: '' };
    activeItem.set(existing);
    invoke.mockRejectedValue(new Error('Cannot read recording'));
    await importPaths(['/source/obs.mkv']);
    expect(get(importError)).toBe('Cannot read recording');
    expect(get(activeItem)).toEqual(existing);
    expect(get(importBusy)).toBe(false);
  });
  it('does nothing on picker cancellation', async () => {
    await importPaths([]);
    expect(invoke).not.toHaveBeenCalled();
  });
});
