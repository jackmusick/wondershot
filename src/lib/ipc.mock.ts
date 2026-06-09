import type { Capture } from '$lib/types';

const PIXEL =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';

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
let counter = 0;

export async function mockInvoke(cmd: string, _args?: unknown): Promise<unknown> {
  switch (cmd) {
    case 'health':
      return 'ok';
    case 'list_library':
      return mockList;
    case 'get_settings':
      return {
        library_dir: '/mock/Screenshots',
        backend: 'auto',
        capture_cursor: false,
        capture_delay: 0,
        extra_dirs: []
      };
    case 'load_sidecar':
      return null;
    case 'save_sidecar':
      return true;
    case 'copy_image':
      return true;
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
