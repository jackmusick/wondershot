import { describe, it, expect } from 'vitest';
import { ipcInvoke, imageDataSrc, normalizeCaptures } from '$lib/ipc';

describe('ipc seam (mock mode)', () => {
  it('routes list_library to the mock backend', async () => {
    const caps = await ipcInvoke<{ id: string }[]>('list_library');
    expect(caps.length).toBe(4);
    expect(caps[0].id).toBe('c1');
  });
});


describe('preview freshness', () => {
  const capture = { id: 'preview', path: '/lib/photo.png', kind: 'image' as const,
    thumbnail: '', createdAt: 100, title: 'photo' };

  it('changes a file thumbnail URL when the file modification time changes', async () => {
    const [before] = await normalizeCaptures([capture]);
    const [unchanged] = await normalizeCaptures([capture]);
    const [after] = await normalizeCaptures([{ ...capture, createdAt: 200 }]);
    expect(before.thumbnail).toContain('revision=100');
    expect(unchanged.thumbnail).toBe(before.thumbnail);
    expect(after.thumbnail).toContain('revision=200');
    expect(after.thumbnail).not.toBe(before.thumbnail);
  });

  it('versions supplied file thumbnails while preserving inline images', async () => {
    const data = 'data:image/png;base64,abc';
    const result = await normalizeCaptures([
      { ...capture, thumbnail: '/thumb.png?size=small' },
      { ...capture, thumbnail: data },
    ]);
    expect(result[0].thumbnail).toBe('/thumb.png?size=small&revision=100');
    expect(result[1].thumbnail).toBe(data);
  });

  it('reloads an editable base when its path is reused', async () => {
    const before = await imageDataSrc('/lib/photo.png');
    const after = await imageDataSrc('/lib/photo.png');
    expect(before).not.toBe(after);
    expect(before.split('?')[0]).toBe(after.split('?')[0]);
  });
});
