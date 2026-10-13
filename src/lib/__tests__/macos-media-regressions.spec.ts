import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, test } from 'vitest';

describe('macOS media regressions', () => {
  test('bundle declares camera and microphone privacy usage strings', () => {
    expect(existsSync('src-tauri/Info.plist')).toBe(true);
    const plist = readFileSync('src-tauri/Info.plist', 'utf8');

    expect(plist).toContain('NSCameraUsageDescription');
    expect(plist).toContain('NSMicrophoneUsageDescription');
  });

  test('camera bubble has a transparent native window background on macOS', () => {
    const source = readFileSync('src-tauri/src/lib.rs', 'utf8');
    const bubble = readFileSync('src/routes/bubble/+page.svelte', 'utf8');

    expect(source).toContain('configure_camera_bubble_window');
    expect(source).toContain('set_background_color(Some(tauri::utils::config::Color(0, 0, 0, 0)))');
    expect(source).toContain('set_shadow(false)');
    expect(bubble).toContain(':global(body > div)');
    expect(bubble).toContain('background: transparent !important');
  });

  test('macOS recorder drains ffmpeg stderr and includes it in failure output', () => {
    const source = readFileSync('crates/wondershot-core/src/record/recorder_macos.rs', 'utf8');

    expect(source).toContain('stderr(Stdio::piped())');
    expect(source).toContain('spawn_stderr_reader');
    expect(source).toContain('stderr_tail');
    expect(source).toContain('recording failed:');
  });

  test('browser media recording still manages the camera bubble lifecycle', () => {
    const source = readFileSync('src/lib/recorder/control.ts', 'utf8');
    const browserIndex = source.indexOf('if (!(await usesNativeRecorder()) && await usesBrowserMedia())');

    expect(source.indexOf('if (cameraEnabled) await showBubble()', browserIndex)).toBeGreaterThan(browserIndex);
    expect(source.indexOf('void hideBubble()', browserIndex)).toBeGreaterThan(browserIndex);
  });

  test('settings opens before probing AVFoundation devices', () => {
    const source = readFileSync('src/lib/components/Settings.svelte', 'utf8');
    const loadSettings = source.slice(source.indexOf('async function loadSettings()'), source.indexOf('onMount'));

    expect(loadSettings).not.toContain('enumerateDevices');
    expect(source).toContain("if (visible && loaded && tab === 'recording')");
    expect(source).toContain('devicesLoaded');
  });
});
