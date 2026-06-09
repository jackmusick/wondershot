import { describe, it, expect } from 'vitest';
import { ipcInvoke } from '$lib/ipc';

describe('ipc seam (mock mode)', () => {
  it('routes list_library to the mock backend', async () => {
    const caps = await ipcInvoke<{ id: string }[]>('list_library');
    expect(caps.length).toBe(4);
    expect(caps[0].id).toBe('c1');
  });
});
