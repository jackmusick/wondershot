import { beforeEach, describe, expect, it, vi } from 'vitest';
import { get } from 'svelte/store';
import type { Capture, CaptureOutcome } from '$lib/types';

const { invoke } = vi.hoisted(() => ({ invoke: vi.fn() }));
vi.mock('$lib/ipc', () => ({ ipcInvoke: invoke, normalizeCaptures: async (items: Capture[]) => items }));
import { activeItem, captures, captureError, completeCapture, loadLibrary, selectedCapturePaths } from '$lib/stores';

const shot = (path: string): Capture => ({ path, id: path, kind: 'image', thumbnail: path, createdAt: 1, title: path });
const outcome = (path: string, copy = true): CaptureOutcome => ({ capture: shot(path), operationId: path,
  backend: 'test', captureElapsedMs: 1, copyAfterCapture: copy, showPreview: true });

describe('capture completion', () => {
  beforeEach(() => {
    captures.set([shot('/old.png')]); activeItem.set(shot('/old.png'));
    selectedCapturePaths.set(['/old.png']); captureError.set('');
    invoke.mockReset().mockResolvedValue(true);
  });

  it('updates the editor and gallery without scanning, then waits for clipboard completion', async () => {
    let copied!: (value: boolean) => void;
    invoke.mockReturnValue(new Promise<boolean>(resolve => { copied = resolve; }));
    const completed = completeCapture(outcome('/new.png'));
    await vi.waitFor(() => expect(invoke).toHaveBeenCalledWith('copy_image', { path: '/new.png' }));
    expect(get(activeItem)?.path).toBe('/new.png');
    expect(get(selectedCapturePaths)).toEqual(['/new.png']);
    let finished = false; void completed.then(() => { finished = true; });
    await Promise.resolve(); expect(finished).toBe(false);
    copied(true); await completed;
    expect(invoke).toHaveBeenCalledTimes(1);
  });

  it('reports clipboard failure while keeping the saved screenshot selected', async () => {
    invoke.mockRejectedValue(new Error('pasteboard unavailable'));
    await completeCapture(outcome('/saved.png'));
    expect(get(selectedCapturePaths)).toEqual(['/saved.png']);
    expect(get(captureError)).toContain('copying to the clipboard failed');
  });

  it('keeps a just-completed capture when an older library scan finishes', async () => {
    let scanned!: (items: Capture[]) => void;
    invoke.mockImplementation((command: string) => command === 'list_library'
      ? new Promise<Capture[]>(resolve => { scanned = resolve; }) : Promise.resolve([]));
    const scan = loadLibrary();
    await completeCapture(outcome('/new.png', false));
    scanned([shot('/old.png')]); await scan;
    expect(get(captures)[0].path).toBe('/new.png');
    expect(get(selectedCapturePaths)).toEqual(['/new.png']);
  });
});
