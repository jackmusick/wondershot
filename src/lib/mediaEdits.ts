/** Output actions must consume rendered media, never an editable draft. */
type Prepare = () => Promise<string>;
type Invoke = <T>(command: string, args?: Record<string, unknown>) => Promise<T>;
const editors = new Map<string, Prepare>();
const pending = new Map<string, Promise<unknown>>();

export function registerMediaEditor(path: string, prepare: Prepare): () => void {
  editors.set(path, prepare);
  return () => { if (editors.get(path) === prepare) editors.delete(path); };
}

export function waitForMediaSave(path: string): Promise<unknown> {
  return pending.get(path) ?? Promise.resolve();
}

export function trackMediaSave(path: string, save: Promise<unknown>): void {
  pending.set(path, save);
  // Keep failures registered so an output action fails instead of leaking the
  // original. A successful retry replaces the failed promise.
  void save.then(() => { if (pending.get(path) === save) pending.delete(path); }, () => {});
}

export type VideoRedaction = { x: number; y: number; w: number; h: number; start: number; end: number; blur?: number };
export function loadVideoDraft(path: string): VideoRedaction[] {
  if (typeof localStorage === 'undefined') return [];
  const saved = JSON.parse(localStorage.getItem(`wondershot-video-blurs:${path}`) ?? '[]');
  if (!Array.isArray(saved)) throw new Error('Invalid video blur draft');
  if (!saved.every(r => r && ['x','y','w','h','start','end'].every(k => Number.isFinite(r[k])) && r.w > 0 && r.h > 0 && r.start >= 0 && r.end > r.start && (r.blur == null || (Number.isFinite(r.blur) && r.blur >= 1 && r.blur <= 60)))) {
    throw new Error('Invalid video blur draft');
  }
  return saved;
}

const videoRenders = new Map<string, { key: string; result: Promise<string> }>();
export async function renderVideoDraft(path: string, redactions: VideoRedaction[], blur: number, invoke: Invoke): Promise<string> {
  if (!redactions.length) return path;
  const snapshot = redactions.map(r => ({ ...r }));
  const key = JSON.stringify([snapshot, blur]);
  let render = videoRenders.get(path);
  if (!render || render.key !== key) {
    const previous = render?.result ?? Promise.resolve();
    const result = previous.catch(() => {}).then(() => invoke<string>('apply_blur', { path, redactions: snapshot, blur }));
    render = { key, result };
    videoRenders.set(path, render);
    void result.catch(() => { if (videoRenders.get(path)?.result === result) videoRenders.delete(path); });
  }
  return render.result;
}

export async function prepareMediaOutput(path: string, invoke: Invoke): Promise<string> {
  const editor = editors.get(path);
  if (editor) return editor();
  await pending.get(path);
  if (/\.(mp4|m4v|mov|mkv|avi|webm)$/i.test(path)) {
    return renderVideoDraft(path, loadVideoDraft(path), 30, invoke);
  }
  return path;
}
