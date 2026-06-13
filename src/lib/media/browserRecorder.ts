import { ipcInvoke } from '$lib/ipc';
import { deviceIdForLabel } from '$lib/media/devices';

export interface BrowserRecorderSettings {
  mic_enabled?: boolean;
  mic_device?: string;
}

export interface BrowserRecordingSession {
  pause(): void;
  resume(): void;
  stop(): void;
}

function blobToBase64(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(reader.error ?? new Error('could not read recording'));
    reader.onload = () => {
      const result = String(reader.result ?? '');
      resolve(result.includes(',') ? result.split(',')[1] : result);
    };
    reader.readAsDataURL(blob);
  });
}

function pickRecordingMime(): string | undefined {
  const candidates = [
    'video/webm;codecs=vp9,opus',
    'video/webm;codecs=vp8,opus',
    'video/webm',
  ];
  return candidates.find((m) => MediaRecorder.isTypeSupported(m));
}

export async function startBrowserRecording(
  settings: BrowserRecorderSettings,
  onStarted: () => void,
  onStopped: () => void,
  onSaved: () => Promise<void>,
  onError: (error: unknown) => void
): Promise<BrowserRecordingSession> {
  if (!navigator.mediaDevices?.getDisplayMedia) {
    throw new Error('screen recording is not available in this WebView');
  }

  const display = await navigator.mediaDevices.getDisplayMedia({
    video: true,
    audio: false,
  });
  const tracks = [...display.getVideoTracks()];

  if (settings.mic_enabled !== false && navigator.mediaDevices.getUserMedia) {
    try {
      const micDeviceId = await deviceIdForLabel('audioinput', String(settings.mic_device ?? ''));
      const mic = await navigator.mediaDevices.getUserMedia({
        audio: micDeviceId ? { deviceId: { exact: micDeviceId } } : true,
        video: false,
      });
      tracks.push(...mic.getAudioTracks());
    } catch (e) {
      console.warn('mic unavailable for browser recording; continuing without audio', e);
    }
  }

  const stream = new MediaStream(tracks);
  const chunks: Blob[] = [];
  const mimeType = pickRecordingMime();
  const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);

  recorder.ondataavailable = (event) => {
    if (event.data.size > 0) chunks.push(event.data);
  };
  recorder.onstop = async () => {
    stream.getTracks().forEach((track) => track.stop());
    onStopped();
    try {
      const blob = new Blob(chunks, { type: mimeType ?? 'video/webm' });
      const data = await blobToBase64(blob);
      await ipcInvoke('save_recording_b64', { dataB64: data, ext: 'webm' });
      await onSaved();
    } catch (e) {
      onError(e);
    }
  };
  stream.getVideoTracks()[0]?.addEventListener('ended', () => {
    if (recorder.state === 'recording') recorder.stop();
  });
  recorder.start(1000);
  onStarted();

  return {
    pause: () => {
      if (recorder.state === 'recording') recorder.pause();
    },
    resume: () => {
      if (recorder.state === 'paused') recorder.resume();
    },
    stop: () => {
      if (recorder.state !== 'inactive') recorder.stop();
    },
  };
}
