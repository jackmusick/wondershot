/**
 * Recording orchestration: countdown → start → pause/resume → stop.
 *
 * Real mode drives the Rust backend via IPC commands and shows the countdown /
 * camera-bubble webview windows. Mock mode (browser dev, VITE_MOCK_IPC=1) skips
 * all Tauri windows and runs a local timer that updates the `recording` store
 * directly so the header is fully interactive without a backend.
 */
import { get } from 'svelte/store';
import { recording, loadLibrary } from '$lib/stores';
import { ipcInvoke } from '$lib/ipc';
import { pushMockRecording } from '$lib/ipc.mock';
import { USE_MOCK, usesBrowserMedia } from '$lib/platform';
import { startBrowserRecording, type BrowserRecordingSession } from '$lib/media/browserRecorder';
import {
  selectNativeRegionRect,
  selectNativeScreenRect,
  supportsNativeScreenPicker,
  supportsNativeRegionPicker,
  type NativeRect
} from '$lib/capture/nativeRegion';

interface RecorderSettings {
  record_countdown?: number;
  camera_device?: string;
  mic_enabled?: boolean;
  mic_device?: string;
}

let starting = false;
let cancelCountdown: (() => void) | undefined;
let browserSession: BrowserRecordingSession | undefined;

// --- mock simulation state ---
let mockTimer: ReturnType<typeof setInterval> | undefined;

function mockTick() {
  const cur = get(recording);
  if (cur.status !== 'recording' || cur.paused) return;
  recording.set({ status: 'recording', elapsedMs: cur.elapsedMs + 1000, paused: false });
}

function startMockTimer() {
  recording.set({ status: 'recording', elapsedMs: 0, paused: false });
  mockTimer = setInterval(mockTick, 1000);
}

function stopMockTimer() {
  if (mockTimer) clearInterval(mockTimer);
  mockTimer = undefined;
}

async function readSettings(): Promise<RecorderSettings> {
  try {
    return (await ipcInvoke<RecorderSettings>('get_settings')) ?? {};
  } catch {
    return {};
  }
}

/** Show the camera bubble (real mode only) — via the backend so the camera
 * stream starts with it. Direct window.show() gives a bubble with no feed. */
async function showBubble() {
  if (USE_MOCK) return;
  try {
    await ipcInvoke('set_camera_bubble', { visible: true });
  } catch (e) {
    console.error('bubble show failed', e);
  }
}

/** Hide the camera bubble (real mode only) — via the backend so the camera
 * stream is released with it. */
async function hideBubble() {
  if (USE_MOCK) return;
  try {
    await ipcInvoke('set_camera_bubble', { visible: false });
  } catch (e) {
    console.error('bubble hide failed', e);
  }
}

/**
 * Show the fullscreen countdown window with `secs`. The pre-created window has a
 * static `/countdown` URL (no secs), so we recreate it at runtime to inject the
 * query param the countdown page reads at mount. Resolves once the countdown
 * settles: `done` → begin recording, `cancel` → abort.
 */
async function runCountdown(secs: number): Promise<'done' | 'cancel'> {
  if (USE_MOCK) return 'done';
  const { WebviewWindow } = await import('@tauri-apps/api/webviewWindow');
  const { listen } = await import('@tauri-apps/api/event');

  // Drop any pre-created/static countdown window so the fresh one carries ?secs.
  const existing = await WebviewWindow.getByLabel('countdown');
  if (existing) {
    try {
      await existing.close();
    } catch {
      /* ignore */
    }
  }

  return new Promise<'done' | 'cancel'>((resolve) => {
    let settled = false;
    const unlisteners: Array<() => void> = [];
    const finish = (kind: 'done' | 'cancel') => {
      if (settled) return;
      settled = true;
      unlisteners.forEach((u) => u());
      cancelCountdown = undefined;
      resolve(kind);
    };

    cancelCountdown = () => finish('cancel');

    const win = new WebviewWindow('countdown', {
      url: `/countdown?secs=${secs}`,
      fullscreen: true,
      transparent: true,
      decorations: false,
      alwaysOnTop: true,
      skipTaskbar: true,
      shadow: false,
      visible: true
    });
    win.once('tauri://error', (e) => {
      console.error('countdown window error', e);
      finish('cancel');
    });

    listen('countdown://done', () => finish('done')).then((u) => unlisteners.push(u));
    listen('countdown://cancel', () => finish('cancel')).then((u) => unlisteners.push(u));
  });
}

/** Issue the actual start (bubble + backend command, or mock timer). */
async function doStart(cameraEnabled: boolean, rect?: NativeRect) {
  if (USE_MOCK) {
    startMockTimer();
    return;
  }
  const settings = await readSettings();
  if (await usesBrowserMedia()) {
    browserSession = await startBrowserRecording(
      settings,
      startMockTimer,
      () => {
        browserSession = undefined;
        stopMockTimer();
      },
      loadLibrary,
      (e) => {
        console.error('save browser recording failed', e);
        recording.set({ status: 'idle' });
      }
    );
    return;
  }
  if (cameraEnabled) await showBubble();
  await ipcInvoke('start_recording', rect ? { rect } : {});
}

export async function startRecording(mode: 'screen' | 'region' | 'display' = 'screen'): Promise<void> {
  if (starting) return;
  if (get(recording).status !== 'idle') return;
  starting = true;
  try {
    const s = await readSettings();
    const countdown = Math.max(0, Number(s.record_countdown ?? 0) || 0);
    const cameraEnabled = !!(s.camera_device && s.camera_device.length > 0);
    let rect: NativeRect | undefined;
    if (mode === 'region' && (await supportsNativeRegionPicker())) {
      rect = await selectNativeRegionRect();
      if (!rect) return;
    } else if (mode === 'display' && (await supportsNativeScreenPicker())) {
      rect = await selectNativeScreenRect();
      if (!rect) return;
    }

    if (countdown > 0) {
      const result = await runCountdown(countdown);
      if (result === 'cancel') return;
    }
    await doStart(cameraEnabled, rect);
  } catch (e) {
    console.error('startRecording failed', e);
  } finally {
    starting = false;
  }
}

export async function startRecordingRect(rect: NativeRect): Promise<void> {
  if (starting) return;
  if (get(recording).status !== 'idle') return;
  starting = true;
  try {
    const s = await readSettings();
    const countdown = Math.max(0, Number(s.record_countdown ?? 0) || 0);
    const cameraEnabled = !!(s.camera_device && s.camera_device.length > 0);
    if (countdown > 0) {
      const result = await runCountdown(countdown);
      if (result === 'cancel') return;
    }
    await doStart(cameraEnabled, rect);
  } catch (e) {
    console.error('startRecordingRect failed', e);
  } finally {
    starting = false;
  }
}

export async function stopRecording(): Promise<void> {
  cancelCountdown?.();
  if (USE_MOCK) {
    stopMockTimer();
    recording.set({ status: 'idle' });
    pushMockRecording();
    await loadLibrary();
    return;
  }
  if (await usesBrowserMedia()) {
    if (browserSession) {
      recording.set({ status: 'idle' });
      browserSession.stop();
    }
    return;
  }
  try {
    await ipcInvoke('stop_recording');
  } catch (e) {
    console.error('stopRecording failed', e);
  }
  await hideBubble();
}

export async function pauseRecording(): Promise<void> {
  const cur = get(recording);
  if (cur.status !== 'recording' || cur.paused) return;
  if (USE_MOCK) {
    recording.set({ ...cur, paused: true });
    return;
  }
  if (await usesBrowserMedia()) {
    browserSession?.pause();
    recording.set({ ...cur, paused: true });
    return;
  }
  try {
    await ipcInvoke('pause_recording');
  } catch (e) {
    console.error('pauseRecording failed', e);
  }
}

export async function resumeRecording(): Promise<void> {
  const cur = get(recording);
  if (cur.status !== 'recording' || !cur.paused) return;
  if (USE_MOCK) {
    recording.set({ ...cur, paused: false });
    return;
  }
  if (await usesBrowserMedia()) {
    browserSession?.resume();
    recording.set({ ...cur, paused: false });
    return;
  }
  try {
    await ipcInvoke('resume_recording');
  } catch (e) {
    console.error('resumeRecording failed', e);
  }
}

/** Tray toggle: start if idle, otherwise stop. */
export async function toggleRecording(): Promise<void> {
  if (get(recording).status === 'idle') await startRecording();
  else await stopRecording();
}

/**
 * Wire backend recording events to the store. Returns an unsubscribe fn.
 * No-op effect in mock mode (mock ipcListen is a no-op; the timer drives state),
 * but still safe to call.
 */
export async function initRecordingEvents(): Promise<() => void> {
  const { ipcListen } = await import('$lib/ipc');

  const unlisteners = await Promise.all([
    ipcListen<{ status: 'recording' | 'stopping' | 'idle'; paused: boolean }>(
      'recording://state',
      (p) => {
        if (p.status === 'recording') {
          const cur = get(recording);
          const elapsedMs = cur.status === 'recording' ? cur.elapsedMs : 0;
          recording.set({ status: 'recording', elapsedMs, paused: !!p.paused });
        } else {
          // stopping / idle
          recording.set({ status: 'idle' });
        }
      }
    ),
    ipcListen<string>('recording://tick', (elapsed) => {
      const cur = get(recording);
      if (cur.status !== 'recording') return;
      recording.set({ ...cur, elapsedMs: parseElapsed(elapsed) });
    }),
    ipcListen<string>('recording://done', async () => {
      recording.set({ status: 'idle' });
      await hideBubble();
      await loadLibrary();
    }),
    ipcListen<string>('recording://failed', async (msg) => {
      console.error('recording failed:', msg);
      recording.set({ status: 'idle' });
      await hideBubble();
    }),
    ipcListen('tray://record-toggle', () => {
      void toggleRecording();
    })
  ]);

  return () => unlisteners.forEach((u) => u());
}

/** Parse "M:SS" (or "H:MM:SS") elapsed string into milliseconds. */
export function parseElapsed(s: string): number {
  const parts = s.split(':').map((p) => parseInt(p, 10));
  if (parts.some((n) => !Number.isFinite(n))) return 0;
  let secs = 0;
  for (const p of parts) secs = secs * 60 + p;
  return secs * 1000;
}
