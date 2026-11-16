import { beforeEach, afterEach, describe, it, expect, vi } from 'vitest';
import { prepareMediaOutput, registerMediaEditor, trackMediaSave, renderVideoDraft } from '../mediaEdits';

beforeEach(() => {
  const values = new Map<string, string>();
  vi.stubGlobal('localStorage', {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
  });
});
afterEach(() => vi.unstubAllGlobals());

const region = { x: 5, y: 10, w: 30, h: 20, start: 0, end: 2, blur: 12 };

describe('rendered media output', () => {
  it('waits for a detached image save', async () => {
    let finish!: () => void;
    const write = new Promise<void>(resolve => { finish = resolve; });
    trackMediaSave('/pending.png', write);
    const done = vi.fn();
    const output = prepareMediaOutput('/pending.png', vi.fn()).then(done);
    await Promise.resolve();
    expect(done).not.toHaveBeenCalled();
    finish(); await output;
    expect(done).toHaveBeenCalledWith('/pending.png');
  });

  it('blocks output on save failure and lets the active editor retry', async () => {
    trackMediaSave('/failed.png', Promise.reject(new Error('disk full')));
    await expect(prepareMediaOutput('/failed.png', vi.fn())).rejects.toThrow('disk full');
    const unregister = registerMediaEditor('/failed.png', async () => '/recovered.png');
    expect(await prepareMediaOutput('/failed.png', vi.fn())).toBe('/recovered.png');
    unregister();
  });

  it('renders inactive video drafts and returns the edited file', async () => {
    localStorage.setItem('wondershot-video-blurs:/draft.mp4', JSON.stringify([region]));
    const invoke = vi.fn().mockResolvedValue('/draft-redacted.mp4');
    expect(await prepareMediaOutput('/draft.mp4', invoke)).toBe('/draft-redacted.mp4');
    expect(invoke).toHaveBeenCalledWith('apply_blur', { path: '/draft.mp4', redactions: [region], blur: 30 });
  });

  it('reuses an in-flight video render and rerenders changed layers', async () => {
    const invoke = vi.fn().mockResolvedValue('/cache-redacted.mp4');
    await Promise.all([1, 2].map(() => renderVideoDraft('/cache.mp4', [region], 30, invoke)));
    expect(invoke).toHaveBeenCalledTimes(1);
    await renderVideoDraft('/cache.mp4', [{ ...region, blur: 25 }], 30, invoke);
    expect(invoke).toHaveBeenCalledTimes(2);
  });

  it('retries failed video renders and rejects corrupt drafts', async () => {
    const invoke = vi.fn().mockRejectedValueOnce(new Error('encoder failed')).mockResolvedValue('/retry-redacted.mp4');
    await expect(renderVideoDraft('/retry.mp4', [region], 30, invoke)).rejects.toThrow('encoder failed');
    expect(await renderVideoDraft('/retry.mp4', [region], 30, invoke)).toBe('/retry-redacted.mp4');
    localStorage.setItem('wondershot-video-blurs:/corrupt.mp4', '{');
    await expect(prepareMediaOutput('/corrupt.mp4', invoke)).rejects.toThrow();
  });
});
