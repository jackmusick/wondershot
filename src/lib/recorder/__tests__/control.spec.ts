import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { get } from 'svelte/store';
import { recording, captures, loadLibrary } from '$lib/stores';
import {
  startRecording,
  stopRecording,
  pauseRecording,
  resumeRecording,
  toggleRecording,
  parseElapsed
} from '$lib/recorder/control';

describe('parseElapsed', () => {
  it('parses M:SS', () => expect(parseElapsed('1:05')).toBe(65_000));
  it('parses H:MM:SS', () => expect(parseElapsed('1:00:00')).toBe(3_600_000));
  it('returns 0 for garbage', () => expect(parseElapsed('--')).toBe(0));
});

describe('recording control (mock mode)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    recording.set({ status: 'idle' });
  });
  afterEach(async () => {
    // ensure timer cleared between tests
    await stopRecording();
    vi.useRealTimers();
  });

  it('start → live timer → pause/resume → stop', async () => {
    await startRecording();
    expect(get(recording)).toEqual({ status: 'recording', elapsedMs: 0, paused: false });

    vi.advanceTimersByTime(2000);
    expect(get(recording)).toMatchObject({ elapsedMs: 2000 });

    await pauseRecording();
    expect(get(recording)).toMatchObject({ paused: true, elapsedMs: 2000 });

    // paused: timer does not advance
    vi.advanceTimersByTime(3000);
    expect(get(recording)).toMatchObject({ elapsedMs: 2000 });

    await resumeRecording();
    vi.advanceTimersByTime(1000);
    expect(get(recording)).toMatchObject({ paused: false, elapsedMs: 3000 });

    await loadLibrary();
    const before = get(captures).length;
    await stopRecording();
    expect(get(recording)).toEqual({ status: 'idle' });
    expect(get(captures).length).toBe(before + 1);
    expect(get(captures)[0].kind).toBe('video');
  });

  it('toggleRecording starts when idle, stops when recording', async () => {
    await toggleRecording();
    expect(get(recording).status).toBe('recording');
    await toggleRecording();
    expect(get(recording).status).toBe('idle');
  });
});
