import { mockInvoke } from '$lib/ipc.mock';

const USE_MOCK =
  import.meta.env.VITE_MOCK_IPC === '1' ||
  typeof (globalThis as any).__TAURI_INTERNALS__ === 'undefined';

export async function ipcInvoke<T>(cmd: string, args?: Record<string, unknown>): Promise<T> {
  if (USE_MOCK) return mockInvoke(cmd, args) as Promise<T>;
  const { invoke } = await import('@tauri-apps/api/core');
  return invoke<T>(cmd, args);
}

export async function ipcListen<T>(event: string, cb: (payload: T) => void): Promise<() => void> {
  if (USE_MOCK) return () => {};
  const { listen } = await import('@tauri-apps/api/event');
  const un = await listen<T>(event, (e) => cb(e.payload));
  return un;
}
