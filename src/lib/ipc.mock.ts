import type { Capture } from '$lib/types';

const PIXEL =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';

/** A 1×1 solid gray PNG, base64 body only (no `data:` prefix). The redact tool
 *  stretches it to fill the region, giving dev/browser a visible placeholder. */
const GRAY_PNG_B64 =
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNgaGD4DwABBQEAwj2hKQAAAABJRU5ErkJggg==';

export const MOCK_CAPTURES: Capture[] = [
  {
    id: 'c1',
    path: '/lib/Screenshot_20260608_140200.png',
    kind: 'image',
    thumbnail: PIXEL,
    createdAt: new Date('2026-06-08T14:02:00').getTime(),
    title: 'Screenshot 14:02'
  },
  {
    id: 'c2',
    path: '/lib/Screenshot_20260608_135100.png',
    kind: 'image',
    thumbnail: PIXEL,
    createdAt: new Date('2026-06-08T13:51:00').getTime(),
    title: 'Screenshot 13:51'
  },
  {
    id: 'c3',
    path: '/lib/Recording_20260608_112000.mp4',
    kind: 'video',
    thumbnail: PIXEL,
    createdAt: new Date('2026-06-08T11:20:00').getTime(),
    title: 'Recording 11:20'
  },
  {
    id: 'c4',
    path: '/lib/Screenshot_20260607_184400.png',
    kind: 'image',
    thumbnail: PIXEL,
    createdAt: new Date('2026-06-07T18:44:00').getTime(),
    title: 'Screenshot 18:44'
  }
];

let mockList: Capture[] = [...MOCK_CAPTURES];
let mockPinned: string[] = [];
let counter = 0;

/** Prepend a fake new screen recording (used by the mock record simulation). */
export function pushMockRecording(): void {
  counter += 1;
  const now = new Date();
  const hh = String(now.getHours()).padStart(2, '0');
  const mm = String(now.getMinutes()).padStart(2, '0');
  const cap: Capture = {
    id: `rec${counter}`,
    path: `/mock/Recording_${counter}.mp4`,
    kind: 'video',
    thumbnail: MOCK_CAPTURES[0].thumbnail,
    createdAt: Date.now() + counter,
    title: `Recording ${hh}:${mm}`
  };
  mockList = [cap, ...mockList];
}

export async function mockInvoke(cmd: string, _args?: unknown): Promise<unknown> {
  switch (cmd) {
    case 'health':
      return 'ok';
    case 'debug_log':
      return null;
    case 'log_path':
      return '/mock/wondershot.log';
    case 'list_library':
      return mockList;
    case 'get_settings':
      return {
        library_dir: '/mock/Screenshots',
        backend: 'auto',
        capture_cursor: false,
        capture_delay: 0,
        extra_dirs: [],
        mic_enabled: true,
        mic_device: '',
        noise_suppression: true,
        record_cursor_halo: false,
        record_countdown: 0,
        camera_device: '',
        hotkey_capture: 'Ctrl+Shift+Print',
        copy_after_capture: true,
        show_gallery_after_capture: true,
        auto_share_after_capture: false,
        pin_on_top: false,
        quick_bar_enabled: true,
        quick_bar_timeout: 8,
        stroke_width: 10,
        font_size: 24,
        tool_color: '#e3242b',
        video_blur_strength: 14,
        gif_fps: 12,
        gif_max_width: 720,
        effect_rounded: false,
        effect_corner_radius: 16,
        effect_fade: false,
        effect_fade_height: 96
      };
    case 'set_settings':
      // No persistence in browser dev; accept and resolve.
      return null;
    case 'load_sidecar':
      return null;
    case 'save_sidecar':
      return true;
    case 'flatten_save':
    case 'write_base':
      // No-op in the mock: there is no real library image / sidecar dir to
      // write. Return ok so save() in the editor resolves cleanly in browser dev.
      return null;
    case 'read_base':
      // No persisted base in the mock; open falls back to the library PNG.
      return null;
    case 'copy_image':
      return true;
    case 'list_pinned':
      return mockPinned;
    case 'set_pinned': {
      const a = _args as { path?: string; pinned?: boolean } | undefined;
      const path = a?.path ?? '';
      mockPinned = mockPinned.filter((p) => p !== path);
      if (a?.pinned) mockPinned = [...mockPinned, path];
      return mockPinned;
    }
    case 'save_image_as':
      // No file dialog in browser dev; pretend the user picked a path.
      return (_args as { path?: string } | undefined)?.path ?? null;
    case 'show_in_folder':
    case 'show_capture_window':
    case 'open_url':
      return null;
    case 'graph_status':
      return { account: '', default_client_id: 'cf7aef3a-2dc5-4b58-b247-2e61fe6a98cc' };
    case 'graph_connect_start':
      return { client_id: 'mock', device_code: 'mock', user_code: 'ABCD-EFGH', verification_uri: 'https://microsoft.com/devicelogin', interval: 5 };
    case 'graph_connect_poll':
      return { status: 'connected', account: 'mock@example.com' };
    case 'graph_disconnect':
      return null;
    case 'graph_sites_search':
      return [{ id: 'site1', name: 'Contoso Team', url: '' }];
    case 'graph_site_drives':
      return [{ id: 'drive1', name: 'Documents' }];
    case 'test_ai_endpoint': {
      const a = _args as { endpoint?: string } | undefined;
      if (!a?.endpoint) throw new Error('No endpoint set');
      return 'Connected (mock)';
    }
    case 'install_desktop':
    case 'trash_item':
      return null;
    case 'import_files':
      // Echo back the requested paths; no real copy in browser dev.
      return (_args as { paths?: string[] } | undefined)?.paths ?? [];
    case 'grab_frame':
    case 'apply_blur':
    case 'export_gif':
    case 'trim_video': {
      // No ffmpeg in browser dev: echo back a plausible output path so the
      // player's success paths (loadLibrary + select) resolve without crashing.
      const p = (_args as { path?: string } | undefined)?.path ?? '/mock/video.mp4';
      return p;
    }
    case 'bg_model_available':
      // No u2net model in browser dev → the Remove BG button stays disabled.
      return false;
    case 'remove_background':
      // The button is disabled in the mock; if invoked anyway, mirror the real
      // backend's "model/runtime unavailable" error.
      throw new Error('background removal runtime not available');
    case 'pixelate_patch':
    case 'blur_patch':
      // The real backend reads the base image + processes the region; the mock
      // just returns a solid gray PNG (base64 body, no prefix — the canvas adds
      // it) so the redact tool can render a placeholder without a real backend.
      return GRAY_PNG_B64;
    case 'capture_region':
    case 'capture_fullscreen':
    case 'capture_window': {
      counter += 1;
      const cap: Capture = {
        id: `new${counter}`,
        path: `/mock/new${counter}.png`,
        kind: 'image',
        thumbnail: MOCK_CAPTURES[0].thumbnail,
        createdAt: 1_760_000_000_000 + counter,
        title: `Capture ${counter}`
      };
      mockList = [cap, ...mockList];
      return cap.path;
    }
    default:
      throw new Error(`mockInvoke: unhandled command ${cmd}`);
  }
}
