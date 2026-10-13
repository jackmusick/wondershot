import { readFileSync } from 'node:fs';
import { describe, expect, test } from 'vitest';

describe('native region picker orchestration', () => {
  test('routes macOS selections to the native backend picker before creating a webview overlay', () => {
    const source = readFileSync('src/lib/capture/nativeRegion.ts', 'utf8');
    const platformIndex = source.indexOf("await currentPlatform()");
    const nativeIndex = source.indexOf("'macos_native_capture_picker'");
    const windowIndex = source.indexOf("new WebviewWindow('region-picker'");

    expect(platformIndex).toBeGreaterThan(-1);
    expect(nativeIndex).toBeGreaterThan(-1);
    expect(windowIndex).toBeGreaterThan(-1);
    expect(platformIndex).toBeLessThan(windowIndex);
    expect(nativeIndex).toBeLessThan(windowIndex);
  });

  test('runs the macOS native picker from an async command so AppKit events are not blocked', () => {
    const commands = readFileSync('src-tauri/src/commands.rs', 'utf8');
    const commandIndex = commands.indexOf('pub async fn macos_native_capture_picker');
    const spawnIndex = commands.indexOf('tauri::async_runtime::spawn_blocking', commandIndex);
    const pickerIndex = commands.indexOf('crate::macos_picker::pick_action()', commandIndex);

    expect(commandIndex).toBeGreaterThan(-1);
    expect(spawnIndex).toBeGreaterThan(commandIndex);
    expect(pickerIndex).toBeGreaterThan(spawnIndex);
  });

  test('routes macOS native record selections into the existing recorder event path', () => {
    const commands = readFileSync('src-tauri/src/commands.rs', 'utf8');
    const picker = readFileSync('src-tauri/src/macos_picker.rs', 'utf8');

    expect(picker).toContain('PickerAction::Record');
    expect(commands).toContain('choice.action == crate::macos_picker::PickerAction::Record');
    expect(commands).toContain('region://record-rect');
    expect(commands.indexOf('region://record-rect')).toBeLessThan(
      commands.indexOf('capture_rgba_with_cursor')
    );
  });

  test('captures the picker frame before creating the overlay window', () => {
    const source = readFileSync('src/lib/capture/nativeRegion.ts', 'utf8');
    const prepareIndex = source.indexOf("ipcInvoke('prepare_native_capture_picker')");
    const captureIndex = source.indexOf("ipcInvoke<NativeCaptureFrame>('native_capture_frame_b64')");
    const windowIndex = source.indexOf("new WebviewWindow('region-picker'");

    expect(prepareIndex).toBeGreaterThan(-1);
    expect(captureIndex).toBeGreaterThan(-1);
    expect(windowIndex).toBeGreaterThan(-1);
    expect(prepareIndex).toBeLessThan(captureIndex);
    expect(captureIndex).toBeLessThan(windowIndex);
    expect(source).toContain('visible: false');
    expect(source).toContain("ipcInvoke('finish_native_capture_picker')");
  });

  test('reveals the picker only after the screenshot image has painted', () => {
    const opener = readFileSync('src/lib/capture/nativeRegion.ts', 'utf8');
    const page = readFileSync('src/routes/region-picker/+page.svelte', 'utf8');

    expect(opener).toContain("listen('region://painted'");
    expect(page).toContain("ipcListen<Frame>('region://frame'");
    expect(page).toContain("ipcEmit('region://painted')");
  });

  test('saves selected regions from the preloaded clean frame', () => {
    const page = readFileSync('src/routes/region-picker/+page.svelte', 'utf8');

    expect(page).toContain("ipcInvoke<string>('save_native_capture_frame_crop'");
    expect(page.indexOf("save_native_capture_frame_crop")).toBeLessThan(
      page.indexOf("save_native_capture_crop")
    );
  });
});
