import { ipcInvoke } from '$lib/ipc';
import { usesBrowserMedia } from '$lib/platform';

export type MediaDeviceOption = { kind: string; label: string };

async function browserDevices(): Promise<MediaDeviceOption[]> {
  if (!navigator.mediaDevices?.enumerateDevices) return [];
  try {
    const probe = await navigator.mediaDevices.getUserMedia({ audio: true, video: true });
    probe.getTracks().forEach((track) => track.stop());
  } catch {
    // Permission can be denied, or a machine may have only one device class.
    // enumerateDevices may still expose default devices.
  }
  const devices = await navigator.mediaDevices.enumerateDevices();
  return devices
    .filter((d) => d.kind === 'videoinput' || d.kind === 'audioinput')
    .map((d, i) => ({
      kind: d.kind,
      label: d.label || (d.kind === 'videoinput' ? `Camera ${i + 1}` : `Microphone ${i + 1}`),
    }));
}

export async function listMediaDevices(): Promise<MediaDeviceOption[]> {
  const backendDevices = (await ipcInvoke<MediaDeviceOption[]>('list_media_devices')) ?? [];
  if (backendDevices.length > 0 || !(await usesBrowserMedia())) {
    return backendDevices;
  }
  return browserDevices();
}

export async function deviceIdForLabel(kind: MediaDeviceKind, label: string): Promise<string | undefined> {
  if (!label || !navigator.mediaDevices?.enumerateDevices) return undefined;
  const devices = await navigator.mediaDevices.enumerateDevices();
  return devices.find((d) => d.kind === kind && d.label === label)?.deviceId;
}
