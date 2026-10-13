import { beforeEach, describe, expect, test, vi } from 'vitest';
import { get } from 'svelte/store';
const invoke = vi.hoisted(() => vi.fn());
vi.mock('$lib/ipc', () => ({ ipcInvoke: invoke, normalizeCaptures: async (v: unknown) => v }));
vi.mock('$lib/platform', () => ({ USE_MOCK: false, usesBrowserMedia: async () => true, usesNativeRecorder: async () => true }));
vi.mock('$lib/media/browserRecorder', () => ({ startBrowserRecording: vi.fn(() => { throw new Error('browser recorder must not run'); }) }));
import { startRecordingRect } from '$lib/recorder/control';
import { recording, recordingError } from '$lib/stores';

describe('macOS native recording routing', () => {
  beforeEach(() => {
    recording.set({ status: 'idle' }); recordingError.set(''); invoke.mockReset();
    invoke.mockImplementation(async (cmd) => cmd === 'get_settings' ? { mic_enabled: false } : undefined);
  });
  test('native recording receives the selected region even when camera uses browser media', async () => {
    await startRecordingRect([10, 20, 640, 360]);
    expect(invoke).toHaveBeenCalledWith('start_recording', { rect: [10, 20, 640, 360] });
    expect(get(recordingError)).toBe('');
  });
  test('backend failure is visible and releases the camera bubble', async () => {
    invoke.mockImplementation(async (cmd) => {
      if (cmd === 'get_settings') return {};
      if (cmd === 'start_recording') throw new Error('Screen Recording access denied');
    });
    await startRecordingRect([10, 20, 640, 360]);
    expect(get(recordingError)).toContain('Screen Recording access denied');
    expect(invoke).toHaveBeenCalledWith('set_camera_bubble', { visible: false });
    expect(get(recording).status).toBe('idle');
  });
});
