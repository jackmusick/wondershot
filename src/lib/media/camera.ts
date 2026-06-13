import { ipcInvoke } from '$lib/ipc';
import { deviceIdForLabel } from '$lib/media/devices';
import { usesBrowserMedia } from '$lib/platform';

export type CameraSource =
  | { type: 'url'; src: string }
  | { type: 'stream'; stream: MediaStream }
  | { type: 'none' };

export async function openCameraSource(label: string): Promise<CameraSource> {
  if (await usesBrowserMedia()) {
    if (!navigator.mediaDevices?.getUserMedia) return { type: 'none' };
    const deviceId = await deviceIdForLabel('videoinput', label);
    const stream = await navigator.mediaDevices.getUserMedia({
      video: deviceId ? { deviceId: { exact: deviceId } } : true,
      audio: false,
    });
    return { type: 'stream', stream };
  }

  const port = await ipcInvoke<number>('media_server_port');
  if (!port) return { type: 'none' };
  return {
    type: 'url',
    src: `http://127.0.0.1:${port}/camera?label=${encodeURIComponent(label)}&t=${Date.now()}`,
  };
}
