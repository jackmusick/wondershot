import { beforeEach, describe, expect, test, vi } from 'vitest';
const mocks = vi.hoisted(() => ({ invoke: vi.fn(), browser: vi.fn() }));
vi.mock('$lib/ipc', () => ({ ipcInvoke: mocks.invoke }));
vi.mock('$lib/platform', () => ({ currentPlatform: async () => 'macos', usesBrowserMedia: async () => true }));
import { openCameraSource } from '$lib/media/camera';

describe('macOS native camera', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.invoke.mockImplementation(async (command: string) => command === 'media_server_port' ? 1234 : undefined);
    Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: { getUserMedia: mocks.browser } });
  });
  test('requests app permission before opening the selected native camera stream', async () => {
    const source = await openCameraSource('External Camera');
    expect(mocks.invoke.mock.calls[0]).toEqual(['authorize_media_capture', { kind: 'camera' }]);
    expect(source).toMatchObject({ type: 'url' });
    if (source.type === 'url') expect(source.src).toContain('/camera?label=External%20Camera');
    expect(mocks.browser).not.toHaveBeenCalled();
  });
  test('permission refusal prevents starting the helper', async () => {
    mocks.invoke.mockRejectedValueOnce(new Error('camera access declined'));
    await expect(openCameraSource('Camera')).rejects.toThrow('camera access declined');
    expect(mocks.invoke).toHaveBeenCalledTimes(1);
  });
});
