# Wondershot M1 — Foundation + UI-Review Harness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up the SvelteKit 2 / Svelte 5 / Tauri 2 app shell on branch `tauri-rewrite` with wonderblob's design language, a mockable IPC seam, and an autonomous screenshot→vision-critique UI-review harness that every later milestone reuses.

**Architecture:** Plain-web SvelteKit frontend (runs in a browser without Tauri via a mocked IPC seam) + a thin Tauri 2 Rust shell. All UI renders from mock data in M1; real backends arrive in M2+. The screenshot harness drives the dev server with Playwright and a vision subagent critiques the PNGs against `tokens.css` and a wonderblob reference.

**Tech Stack:** SvelteKit 2.9, Svelte 5, Vite 6, TypeScript, Tauri 2 (Rust edition 2021), Playwright, Vitest. Mirrors `../wonderblob` exactly.

---

## File Structure

```
wondershot/
  package.json                       # frontend deps + scripts
  svelte.config.js                   # adapter-static, SPA fallback
  vite.config.ts                     # Vitest config + VITE_MOCK_IPC env
  playwright.config.ts               # screenshot harness config
  src/
    app.html
    lib/styles/tokens.css            # copied from wonderblob, retinted
    lib/styles/global.css
    lib/ipc.ts                       # invoke/listen seam (real + mock)
    lib/ipc.mock.ts                  # canned data + scripted events
    lib/types.ts                     # Capture, LibraryGroup, RecordingState
    lib/stores.ts                    # captures, view, activeItem, recording, settings
    lib/library.ts                   # groupByDate() pure util
    lib/components/LibrarySidebar.svelte
    lib/components/CaptureHeader.svelte
    lib/components/ContentView.svelte
    routes/+layout.svelte            # theme apply
    routes/+page.svelte              # shell: sidebar + header + content
    routes/screen/+page.svelte       # ?screen= harness mount point
  src/lib/__tests__/                 # Vitest specs
  tests-ui/
    capture.spec.ts                  # Playwright screenshot harness
    refshots.spec.ts                 # captures wonderblob reference
  workflows/ui-review.mjs            # vision-critique workflow script
  artifacts/ui/                      # screenshot output (gitignored)
  src-tauri/
    Cargo.toml
    tauri.conf.json
    src/main.rs                      # app setup, single-instance, tray stub
    src/commands.rs                  # health command
```

---

## Task 0: Verify toolchain

**Files:** none (environment check)

- [ ] **Step 1: Confirm node, rust, and tauri CLI are present**

Run:
```bash
node --version && npm --version && rustc --version && cargo --version
cargo tauri --version 2>/dev/null || echo "tauri-cli MISSING"
```
Expected: node ≥ 20, rust ≥ 1.77. If `tauri-cli MISSING`, install it:
```bash
cargo install tauri-cli --version "^2" --locked
```

- [ ] **Step 2: Confirm we are on the rewrite branch**

Run: `git branch --show-current`
Expected: `tauri-rewrite`. If not: `git checkout tauri-rewrite`.

---

## Task 1: Scaffold frontend without clobbering the Python tree

**Files:**
- Create: `package.json`, `svelte.config.js`, `vite.config.ts`, `src/app.html`, `tsconfig.json`
- Modify: `.gitignore`

The existing `wondershot/` Python package and `tests/` stay untouched. We add web files at the repo root and the Rust shell under `src-tauri/`.

- [ ] **Step 1: Create `package.json`**

```json
{
  "name": "wondershot",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite dev",
    "build": "vite build",
    "preview": "vite preview",
    "check": "svelte-kit sync && svelte-check --tsconfig ./tsconfig.json",
    "test": "vitest run",
    "test:ui": "playwright test",
    "tauri": "tauri"
  },
  "devDependencies": {
    "@sveltejs/adapter-static": "^3.0.6",
    "@sveltejs/kit": "^2.9.0",
    "@sveltejs/vite-plugin-svelte": "^5.0.0",
    "@playwright/test": "^1.49.0",
    "svelte": "^5.0.0",
    "svelte-check": "^4.1.0",
    "typescript": "^5.6.0",
    "vite": "^6.0.3",
    "vitest": "^4.1.8"
  },
  "dependencies": {
    "@tauri-apps/api": "^2.0.0",
    "konva": "^9.3.0",
    "svelte-konva": "^1.0.0"
  }
}
```

- [ ] **Step 2: Create `svelte.config.js`**

```javascript
import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

export default {
  preprocess: vitePreprocess(),
  kit: {
    adapter: adapter({ fallback: 'index.html' }),
    alias: { $lib: 'src/lib' }
  }
};
```

- [ ] **Step 3: Create `vite.config.ts`**

```typescript
import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [sveltekit()],
  clearScreen: false,
  server: { port: 1420, strictPort: true },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.{test,spec}.{js,ts}']
  }
});
```

- [ ] **Step 4: Create `src/app.html`**

```html
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    %sveltekit.head%
  </head>
  <body data-sveltekit-preload-data="hover">
    <div style="display: contents">%sveltekit.body%</div>
  </body>
</html>
```

- [ ] **Step 5: Create `tsconfig.json`**

```json
{
  "extends": "./.svelte-kit/tsconfig.json",
  "compilerOptions": {
    "strict": true,
    "moduleResolution": "bundler"
  }
}
```

- [ ] **Step 6: Append to `.gitignore`**

```
node_modules/
.svelte-kit/
build/
artifacts/
src-tauri/target/
test-results/
```

- [ ] **Step 7: Install and verify the scaffold builds**

Run:
```bash
npm install && npx playwright install chromium && npm run build
```
Expected: `vite build` completes with no errors and writes `build/`.

- [ ] **Step 8: Commit**

```bash
git add package.json package-lock.json svelte.config.js vite.config.ts src/app.html tsconfig.json .gitignore
git commit -m "M1: scaffold SvelteKit 2 + Svelte 5 + Vite frontend"
```

---

## Task 2: Design tokens + theme apply

**Files:**
- Create: `src/lib/styles/tokens.css`, `src/lib/styles/global.css`, `src/routes/+layout.svelte`
- Test: `src/lib/__tests__/tokens.spec.ts`

- [ ] **Step 1: Write the failing test for token presence**

`src/lib/__tests__/tokens.spec.ts`:
```typescript
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';

const css = readFileSync('src/lib/styles/tokens.css', 'utf8');

describe('design tokens', () => {
  it('defines the two-plane dark backgrounds', () => {
    expect(css).toContain('--bg-sidebar: #141416');
    expect(css).toContain('--bg-content: #29292c');
  });
  it('defines the accent and radius', () => {
    expect(css).toMatch(/--accent:\s*#3b82f6/);
    expect(css).toContain('--radius: 6px');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- tokens`
Expected: FAIL — cannot read `tokens.css` (file missing).

- [ ] **Step 3: Copy wonderblob's tokens and retint**

Copy the source then keep the values:
```bash
cp ../wonderblob/src/lib/styles/tokens.css src/lib/styles/tokens.css
```
Confirm the dark block contains exactly (edit to match if upstream drifted):
```css
:root[data-theme="dark"], :root:not([data-theme="light"]) {
  --bg-app: #19191b;
  --bg-sidebar: #141416;
  --bg-content: #29292c;
  --bg-elevated: #18181a;
  --bg-field: #2a2a2e;
  --bg-hover: rgba(255, 255, 255, 0.06);
  --bg-selected: rgba(59, 130, 246, 0.22);
  --fg-primary: #f4f4f7;
  --fg-secondary: #c4c4cc;
  --border: rgba(255, 255, 255, 0.08);
  --border-strong: rgba(255, 255, 255, 0.16);
  --accent: #3b82f6;
  --accent-strong: #5b9bff;
  --danger: #ff6b66;
  --success: #32d74b;
  --radius: 6px;
}
```
(The light block and `--font-*`, `--text-*`, `--row-height` tokens come over unchanged.)

- [ ] **Step 4: Create `src/lib/styles/global.css`**

```css
* { box-sizing: border-box; }
html, body { margin: 0; height: 100%; }
body {
  font-family: var(--font-ui);
  font-size: var(--text-base);
  color: var(--fg-primary);
  background: var(--bg-app);
  -webkit-font-smoothing: antialiased;
}
:focus { outline: none; }
:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
```

- [ ] **Step 5: Create `src/routes/+layout.svelte`**

```svelte
<script lang="ts">
  import '$lib/styles/tokens.css';
  import '$lib/styles/global.css';
  let { children } = $props();
</script>

<svelte:head>
  <script>
    document.documentElement.setAttribute('data-theme', 'dark');
  </script>
</svelte:head>

{@render children()}
```

- [ ] **Step 6: Run test to verify it passes**

Run: `npm run test -- tokens`
Expected: PASS (2 tests).

- [ ] **Step 7: Commit**

```bash
git add src/lib/styles src/routes/+layout.svelte src/lib/__tests__/tokens.spec.ts
git commit -m "M1: design tokens (wonderblob clone) + dark theme apply"
```

---

## Task 3: Domain types + library grouping util

**Files:**
- Create: `src/lib/types.ts`, `src/lib/library.ts`
- Test: `src/lib/__tests__/library.spec.ts`

- [ ] **Step 1: Create `src/lib/types.ts`**

```typescript
export type CaptureKind = 'image' | 'video';

export interface Capture {
  id: string;
  path: string;
  kind: CaptureKind;
  thumbnail: string;   // data URL or file src
  createdAt: number;   // epoch ms
  title: string;
}

export interface LibraryGroup {
  label: string;       // "Today", "Yesterday", or a date
  items: Capture[];
}

export type RecordingState =
  | { status: 'idle' }
  | { status: 'recording'; elapsedMs: number; paused: boolean };
```

- [ ] **Step 2: Write the failing test for `groupByDate`**

`src/lib/__tests__/library.spec.ts`:
```typescript
import { describe, it, expect } from 'vitest';
import { groupByDate } from '$lib/library';
import type { Capture } from '$lib/types';

const cap = (id: string, createdAt: number): Capture => ({
  id, createdAt, path: `/x/${id}.png`, kind: 'image',
  thumbnail: '', title: id
});

describe('groupByDate', () => {
  it('buckets Today and Yesterday relative to a reference time', () => {
    const now = new Date('2026-06-08T12:00:00Z').getTime();
    const today = new Date('2026-06-08T09:00:00Z').getTime();
    const yest = new Date('2026-06-07T22:00:00Z').getTime();
    const groups = groupByDate([cap('a', today), cap('b', yest)], now);
    expect(groups[0].label).toBe('Today');
    expect(groups[0].items.map(i => i.id)).toEqual(['a']);
    expect(groups[1].label).toBe('Yesterday');
    expect(groups[1].items.map(i => i.id)).toEqual(['b']);
  });
  it('sorts items newest-first within a group', () => {
    const now = new Date('2026-06-08T12:00:00Z').getTime();
    const g = groupByDate([cap('old', now - 3000), cap('new', now - 1000)], now);
    expect(g[0].items.map(i => i.id)).toEqual(['new', 'old']);
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `npm run test -- library`
Expected: FAIL — `groupByDate` is not defined.

- [ ] **Step 4: Implement `src/lib/library.ts`**

```typescript
import type { Capture, LibraryGroup } from '$lib/types';

const DAY = 86_400_000;

function startOfDay(ms: number): number {
  const d = new Date(ms);
  d.setHours(0, 0, 0, 0);
  return d.getTime();
}

export function groupByDate(captures: Capture[], now: number): LibraryGroup[] {
  const todayStart = startOfDay(now);
  const buckets = new Map<number, Capture[]>();
  for (const c of captures) {
    const key = startOfDay(c.createdAt);
    (buckets.get(key) ?? buckets.set(key, []).get(key)!).push(c);
  }
  const keys = [...buckets.keys()].sort((a, b) => b - a);
  return keys.map((key) => {
    const items = buckets.get(key)!.sort((a, b) => b.createdAt - a.createdAt);
    let label: string;
    if (key === todayStart) label = 'Today';
    else if (key === todayStart - DAY) label = 'Yesterday';
    else label = new Date(key).toLocaleDateString();
    return { label, items };
  });
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npm run test -- library`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add src/lib/types.ts src/lib/library.ts src/lib/__tests__/library.spec.ts
git commit -m "M1: domain types + groupByDate library util"
```

---

## Task 4: Mockable IPC seam

**Files:**
- Create: `src/lib/ipc.ts`, `src/lib/ipc.mock.ts`
- Test: `src/lib/__tests__/ipc.spec.ts`

- [ ] **Step 1: Create the mock backend `src/lib/ipc.mock.ts`**

```typescript
import type { Capture } from '$lib/types';

const PIXEL =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==';

export const MOCK_CAPTURES: Capture[] = [
  { id: 'c1', path: '/lib/Screenshot_20260608_140200.png', kind: 'image',
    thumbnail: PIXEL, createdAt: new Date('2026-06-08T14:02:00').getTime(), title: 'Screenshot 14:02' },
  { id: 'c2', path: '/lib/Screenshot_20260608_135100.png', kind: 'image',
    thumbnail: PIXEL, createdAt: new Date('2026-06-08T13:51:00').getTime(), title: 'Screenshot 13:51' },
  { id: 'c3', path: '/lib/Recording_20260608_112000.mp4', kind: 'video',
    thumbnail: PIXEL, createdAt: new Date('2026-06-08T11:20:00').getTime(), title: 'Recording 11:20' },
  { id: 'c4', path: '/lib/Screenshot_20260607_184400.png', kind: 'image',
    thumbnail: PIXEL, createdAt: new Date('2026-06-07T18:44:00').getTime(), title: 'Screenshot 18:44' }
];

export async function mockInvoke(cmd: string, _args?: unknown): Promise<unknown> {
  switch (cmd) {
    case 'health': return 'ok';
    case 'list_library': return MOCK_CAPTURES;
    default: throw new Error(`mockInvoke: unhandled command ${cmd}`);
  }
}
```

- [ ] **Step 2: Write the failing test `src/lib/__tests__/ipc.spec.ts`**

```typescript
import { describe, it, expect } from 'vitest';
import { ipcInvoke } from '$lib/ipc';

describe('ipc seam (mock mode)', () => {
  it('routes list_library to the mock backend', async () => {
    const caps = await ipcInvoke<{ id: string }[]>('list_library');
    expect(caps.length).toBe(4);
    expect(caps[0].id).toBe('c1');
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `npm run test -- ipc`
Expected: FAIL — `ipcInvoke` is not exported.

- [ ] **Step 4: Implement `src/lib/ipc.ts`**

```typescript
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npm run test -- ipc`
Expected: PASS. (Under Vitest there is no `__TAURI_INTERNALS__`, so mock mode is on.)

- [ ] **Step 6: Commit**

```bash
git add src/lib/ipc.ts src/lib/ipc.mock.ts src/lib/__tests__/ipc.spec.ts
git commit -m "M1: mockable IPC seam (browser runs without Tauri)"
```

---

## Task 5: Stores

**Files:**
- Create: `src/lib/stores.ts`
- Test: `src/lib/__tests__/stores.spec.ts`

- [ ] **Step 1: Write the failing test `src/lib/__tests__/stores.spec.ts`**

```typescript
import { describe, it, expect } from 'vitest';
import { get } from 'svelte/store';
import { loadLibrary, captures, view } from '$lib/stores';

describe('stores', () => {
  it('loadLibrary populates captures from ipc', async () => {
    await loadLibrary();
    expect(get(captures).length).toBe(4);
  });
  it('view defaults to gallery', () => {
    expect(get(view)).toBe('gallery');
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run test -- stores`
Expected: FAIL — module `$lib/stores` not found.

- [ ] **Step 3: Implement `src/lib/stores.ts`**

```typescript
import { writable } from 'svelte/store';
import type { Capture, RecordingState } from '$lib/types';
import { ipcInvoke } from '$lib/ipc';

export type View = 'gallery' | 'editor' | 'video';

export const captures = writable<Capture[]>([]);
export const activeItem = writable<Capture | null>(null);
export const view = writable<View>('gallery');
export const recording = writable<RecordingState>({ status: 'idle' });

export async function loadLibrary(): Promise<void> {
  const caps = await ipcInvoke<Capture[]>('list_library');
  captures.set(caps);
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run test -- stores`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/lib/stores.ts src/lib/__tests__/stores.spec.ts
git commit -m "M1: svelte stores (captures, view, activeItem, recording)"
```

---

## Task 6: Shell components

**Files:**
- Create: `src/lib/components/LibrarySidebar.svelte`, `src/lib/components/CaptureHeader.svelte`, `src/lib/components/ContentView.svelte`, `src/routes/+page.svelte`

- [ ] **Step 1: Create `src/lib/components/LibrarySidebar.svelte`**

```svelte
<script lang="ts">
  import { captures, activeItem } from '$lib/stores';
  import { groupByDate } from '$lib/library';
  import type { Capture } from '$lib/types';
  let now = Date.now();
  let groups = $derived(groupByDate($captures, now));
  function select(c: Capture) { activeItem.set(c); }
</script>

<aside class="sidebar">
  <div class="list">
    {#each groups as g}
      <div class="group-label">{g.label}</div>
      {#each g.items as c}
        <button class="row" class:selected={$activeItem?.id === c.id} onclick={() => select(c)}>
          <img class="thumb" src={c.thumbnail} alt="" />
          <span class="title">{c.title}</span>
          <span class="kind">{c.kind === 'video' ? '▶' : ''}</span>
        </button>
      {/each}
    {/each}
  </div>
  <button class="settings">⚙ Settings</button>
</aside>

<style>
  .sidebar {
    width: 240px; flex-shrink: 0; display: flex; flex-direction: column;
    background: var(--bg-sidebar); padding: 8px; overflow-y: auto;
  }
  .list { flex: 1; display: flex; flex-direction: column; gap: 1px; }
  .group-label {
    font-size: var(--text-small); color: var(--fg-secondary);
    padding: 8px 8px 4px; text-transform: none;
  }
  .row {
    display: flex; align-items: center; gap: 8px; height: var(--row-height);
    padding: 0 8px; border: none; background: transparent; border-radius: var(--radius);
    color: var(--fg-primary); font-size: var(--text-base); cursor: default; text-align: left;
  }
  .row:hover { background: var(--bg-hover); }
  .row.selected { background: var(--bg-selected); box-shadow: inset 2px 0 0 var(--accent); }
  .thumb { width: 28px; height: 18px; object-fit: cover; border-radius: 3px; background: var(--bg-field); }
  .title { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .kind { color: var(--fg-secondary); }
  .settings {
    height: 30px; border: none; background: transparent; color: var(--fg-secondary);
    text-align: left; padding: 0 8px; border-radius: var(--radius); cursor: default;
  }
  .settings:hover { background: var(--bg-hover); color: var(--fg-primary); }
</style>
```

- [ ] **Step 2: Create `src/lib/components/CaptureHeader.svelte`**

```svelte
<script lang="ts">
  import { recording } from '$lib/stores';
  const modes = ['Region', 'Full screen', 'Window', 'Scrolling'];
  function fmt(ms: number) {
    const s = Math.floor(ms / 1000);
    return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
  }
</script>

<header class="header">
  <div class="modes">
    {#each modes as m}
      <button class="mode">{m}</button>
    {/each}
  </div>
  <div class="spacer"></div>
  <button class="record" class:active={$recording.status === 'recording'}>
    ● Record
    {#if $recording.status === 'recording'}
      <span class="timer">{fmt($recording.elapsedMs)}</span>
    {/if}
  </button>
</header>

<style>
  .header {
    height: 44px; display: flex; align-items: center; gap: 8px; padding: 0 10px;
    border-bottom: 1px solid var(--border); background: var(--bg-content); flex-shrink: 0;
  }
  .modes { display: flex; gap: 2px; }
  .mode {
    height: 28px; padding: 0 12px; border: none; background: transparent;
    color: var(--fg-primary); border-radius: var(--radius); font-size: var(--text-base); cursor: default;
  }
  .mode:hover { background: var(--bg-hover); }
  .spacer { flex: 1; }
  .record {
    height: 28px; padding: 0 14px; border: none; border-radius: var(--radius);
    background: var(--accent); color: #fff; font-size: var(--text-base); cursor: default;
    display: inline-flex; align-items: center; gap: 8px;
  }
  .record:hover { filter: brightness(1.08); }
  .record.active { background: var(--danger); }
  .timer { font-variant-numeric: tabular-nums; }
</style>
```

- [ ] **Step 3: Create `src/lib/components/ContentView.svelte`**

```svelte
<script lang="ts">
  import { activeItem, view } from '$lib/stores';
</script>

<div class="content-body">
  {#if $activeItem}
    {#if $view === 'gallery'}
      <img class="preview" src={$activeItem.thumbnail} alt={$activeItem.title} />
    {:else}
      <div class="placeholder">{$view} view — built in a later milestone</div>
    {/if}
  {:else}
    <div class="placeholder">Select or take a capture</div>
  {/if}
</div>

<style>
  .content-body { flex: 1; display: flex; align-items: center; justify-content: center; overflow: auto; }
  .preview { max-width: 90%; max-height: 90%; border-radius: var(--radius); box-shadow: 0 8px 24px rgba(0,0,0,0.4); }
  .placeholder { color: var(--fg-secondary); font-size: var(--text-small); }
</style>
```

- [ ] **Step 4: Create `src/routes/+page.svelte`**

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { loadLibrary } from '$lib/stores';
  import LibrarySidebar from '$lib/components/LibrarySidebar.svelte';
  import CaptureHeader from '$lib/components/CaptureHeader.svelte';
  import ContentView from '$lib/components/ContentView.svelte';
  onMount(loadLibrary);
</script>

<div class="shell">
  <LibrarySidebar />
  <main class="content">
    <CaptureHeader />
    <ContentView />
  </main>
</div>

<style>
  .shell { display: flex; height: 100vh; }
  .content { flex: 1; display: flex; flex-direction: column; background: var(--bg-content); min-width: 0; }
</style>
```

- [ ] **Step 5: Verify the shell renders in the browser**

Run: `npm run dev` then open `http://localhost:1420`.
Expected: dark two-plane shell — sidebar lists "Today" (2 shots) and "Yesterday" (1 shot) plus a video row, header with capture modes + Record, empty content placeholder. Stop the server (Ctrl-C).

- [ ] **Step 6: Commit**

```bash
git add src/lib/components src/routes/+page.svelte
git commit -m "M1: app shell — library sidebar, capture header, content view"
```

---

## Task 7: Screenshot harness mount + Playwright

**Files:**
- Create: `src/routes/screen/+page.svelte`, `playwright.config.ts`, `tests-ui/capture.spec.ts`

- [ ] **Step 1: Create the harness mount `src/routes/screen/+page.svelte`**

Renders a single component by `?screen=` so screenshots are deterministic and isolated.

```svelte
<script lang="ts">
  import { page } from '$app/state';
  import { onMount } from 'svelte';
  import { loadLibrary } from '$lib/stores';
  import LibrarySidebar from '$lib/components/LibrarySidebar.svelte';
  import CaptureHeader from '$lib/components/CaptureHeader.svelte';
  let screen = $derived(page.url.searchParams.get('screen') ?? 'shell');
  onMount(loadLibrary);
</script>

{#if screen === 'sidebar'}
  <div style="height:100vh;display:flex"><LibrarySidebar /></div>
{:else if screen === 'header'}
  <div style="background:var(--bg-content)"><CaptureHeader /></div>
{:else}
  <a href="/">full shell at /</a>
{/if}
```

- [ ] **Step 2: Create `playwright.config.ts`**

```typescript
import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: 'tests-ui',
  use: { baseURL: 'http://localhost:1420', viewport: { width: 1280, height: 800 } },
  webServer: {
    command: 'VITE_MOCK_IPC=1 npm run dev',
    url: 'http://localhost:1420',
    reuseExistingServer: true,
    timeout: 60_000
  }
});
```

- [ ] **Step 3: Write the screenshot harness `tests-ui/capture.spec.ts`**

```typescript
import { test, expect } from '@playwright/test';
import { existsSync, statSync } from 'node:fs';

const SCREENS = ['shell', 'sidebar', 'header'];
const THEMES = ['dark', 'light'] as const;

for (const screen of SCREENS) {
  for (const theme of THEMES) {
    test(`shot ${screen} ${theme}`, async ({ page }) => {
      const url = screen === 'shell' ? '/' : `/screen?screen=${screen}`;
      await page.goto(url);
      await page.evaluate((t) => document.documentElement.setAttribute('data-theme', t), theme);
      await page.waitForTimeout(150);
      const out = `artifacts/ui/${screen}-${theme}.png`;
      await page.screenshot({ path: out });
      expect(existsSync(out) && statSync(out).size > 0).toBe(true);
    });
  }
}
```

- [ ] **Step 4: Run the harness**

Run: `npm run test:ui -- capture`
Expected: 6 PASS; PNGs in `artifacts/ui/` (shell/sidebar/header × dark/light).

- [ ] **Step 5: Commit**

```bash
git add src/routes/screen/+page.svelte playwright.config.ts tests-ui/capture.spec.ts
git commit -m "M1: Playwright screenshot harness (per-component, light+dark)"
```

---

## Task 8: Wonderblob reference shots

**Files:**
- Create: `tests-ui/refshots.spec.ts`

- [ ] **Step 1: Write `tests-ui/refshots.spec.ts`**

Captures wonderblob's running shell as the parity anchor. Skips cleanly if wonderblob's
dev server is not reachable, so CI never hard-fails on it.

```typescript
import { test, expect } from '@playwright/test';
import { existsSync } from 'node:fs';

const REF_URL = process.env.WONDERBLOB_URL ?? 'http://localhost:1430';

test('reference: wonderblob shell', async ({ page }) => {
  let up = true;
  await page.goto(REF_URL).catch(() => { up = false; });
  test.skip(!up, 'wonderblob dev server not running on ' + REF_URL);
  await page.waitForTimeout(300);
  await page.screenshot({ path: 'artifacts/ui/ref/wonderblob-shell.png' });
  expect(existsSync('artifacts/ui/ref/wonderblob-shell.png')).toBe(true);
});
```

- [ ] **Step 2: Capture the reference once**

Run (in a separate terminal, from `../wonderblob`): `npm run dev -- --port 1430`
Then run: `npm run test:ui -- refshots`
Expected: PASS — `artifacts/ui/ref/wonderblob-shell.png` exists (or SKIP if not running).

- [ ] **Step 3: Commit**

```bash
git add tests-ui/refshots.spec.ts
git commit -m "M1: wonderblob reference screenshot capture (parity anchor)"
```

---

## Task 9: Vision-critique workflow stage

**Files:**
- Create: `workflows/ui-review.mjs`

This is the reusable "review the UI as you go" stage. It is a Workflow script: it reads the
screenshot PNGs and dispatches a vision subagent per shot to score it against the tokens
and the wonderblob reference, returning structured findings. Later milestones call it after
each UI task.

- [ ] **Step 1: Write `workflows/ui-review.mjs`**

```javascript
export const meta = {
  name: 'wondershot-ui-review',
  description: 'Vision-critique Wondershot UI screenshots against tokens.css + wonderblob reference',
  phases: [{ title: 'Critique' }]
};

// args: { shots: string[] }  — absolute or repo-relative PNG paths to review.
const shots = (args && args.shots) || [
  'artifacts/ui/shell-dark.png',
  'artifacts/ui/sidebar-dark.png',
  'artifacts/ui/header-dark.png'
];

const FINDINGS = {
  type: 'object',
  required: ['shot', 'pass', 'findings'],
  properties: {
    shot: { type: 'string' },
    pass: { type: 'boolean' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['severity', 'area', 'issue', 'fix'],
        properties: {
          severity: { type: 'string', enum: ['blocker', 'major', 'minor', 'nit'] },
          area: { type: 'string' },
          issue: { type: 'string' },
          fix: { type: 'string' }
        }
      }
    }
  }
};

phase('Critique');
const results = await parallel(shots.map((shot) => () =>
  agent(
    `Read the screenshot at ${shot}. Also read src/lib/styles/tokens.css and, if present, ` +
    `the reference artifacts/ui/ref/wonderblob-shell.png. Critique the screenshot for ` +
    `fidelity to the design language: correct two-plane backgrounds (sidebar #141416, ` +
    `content #29292c), 6px radii, 28px control heights, --text-base/--text-small ` +
    `typography, hover/selected states (inset 2px accent bar), spacing scale, and focus ` +
    `rings. Report concrete, fixable findings. Set pass=false if any blocker/major exists.`,
    { label: `critique:${shot.split('/').pop()}`, schema: FINDINGS, agentType: 'general-purpose' }
  )
));

const reviewed = results.filter(Boolean);
const failures = reviewed.filter((r) => !r.pass);
log(`UI review: ${reviewed.length} shots, ${failures.length} need work`);
return { reviewed, failures };
```

- [ ] **Step 2: Smoke-test the workflow against the M1 shots**

This step is run by the orchestrator (the main agent), not inside the plan executor:
invoke the Workflow tool with `{ scriptPath: 'workflows/ui-review.mjs', args: { shots: ['artifacts/ui/shell-dark.png'] } }`.
Expected: returns `{ reviewed: [...], failures: [...] }` with at least one structured
critique object. Address any `blocker`/`major` findings on the shell before closing M1.

- [ ] **Step 3: Commit**

```bash
git add workflows/ui-review.mjs
git commit -m "M1: vision-critique UI-review workflow stage (reused by M2/M3/M5)"
```

---

## Task 10: Tauri Rust shell

**Files:**
- Create: `src-tauri/Cargo.toml`, `src-tauri/tauri.conf.json`, `src-tauri/src/main.rs`, `src-tauri/src/commands.rs`, `src-tauri/build.rs`

- [ ] **Step 1: Create `src-tauri/Cargo.toml`**

```toml
[package]
name = "wondershot"
version = "0.1.0"
edition = "2021"

[build-dependencies]
tauri-build = { version = "2", features = [] }

[dependencies]
tauri = { version = "2", features = ["tray-icon"] }
tauri-plugin-single-instance = "2"
serde = { version = "1", features = ["derive"] }
serde_json = "1"

[lib]
name = "wondershot_lib"
crate-type = ["staticlib", "cdylib", "rlib"]
```

- [ ] **Step 2: Create `src-tauri/build.rs`**

```rust
fn main() {
    tauri_build::build();
}
```

- [ ] **Step 3: Create `src-tauri/src/commands.rs`**

```rust
#[tauri::command]
pub fn health() -> String {
    "ok".to_string()
}
```

- [ ] **Step 4: Create `src-tauri/src/main.rs`**

```rust
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod commands;

use tauri::tray::TrayIconBuilder;

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            use tauri::Manager;
            if let Some(w) = app.get_webview_window("main") {
                let _ = w.set_focus();
            }
        }))
        .setup(|app| {
            TrayIconBuilder::new()
                .tooltip("Wondershot")
                .build(app)?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![commands::health])
        .run(tauri::generate_context!())
        .expect("error while running wondershot");
}
```

- [ ] **Step 5: Create `src-tauri/tauri.conf.json`**

```json
{
  "$schema": "https://schema.tauri.app/config/2",
  "productName": "Wondershot",
  "version": "0.1.0",
  "identifier": "io.github.jackmusick.wondershot",
  "build": {
    "frontendDist": "../build",
    "devUrl": "http://localhost:1420",
    "beforeDevCommand": "npm run dev",
    "beforeBuildCommand": "npm run build"
  },
  "app": {
    "windows": [
      { "label": "main", "title": "Wondershot", "width": 1100, "height": 720 }
    ],
    "security": { "csp": null }
  },
  "bundle": { "active": true, "targets": ["appimage", "rpm"], "icon": ["icons/icon.png"] }
}
```

- [ ] **Step 6: Provide a placeholder icon**

Run:
```bash
mkdir -p src-tauri/icons
cp wondershot/data/wondershot.png src-tauri/icons/icon.png 2>/dev/null || \
  cargo tauri icon wondershot/data/wondershot.png 2>/dev/null || true
```
Expected: `src-tauri/icons/icon.png` exists (any 256×256+ PNG is fine for M1).

- [ ] **Step 7: Build and launch the Tauri shell**

Run: `cargo tauri dev`
Expected: a native window opens showing the same shell, a tray icon appears, and launching
a second instance focuses the existing window instead of opening a new one. Close it.

- [ ] **Step 8: Verify the real IPC path with a health call**

Temporarily add to `src/routes/+page.svelte` `onMount`:
```typescript
import { ipcInvoke } from '$lib/ipc';
ipcInvoke<string>('health').then((r) => console.log('health:', r));
```
Run `cargo tauri dev`, confirm the devtools console logs `health: ok` (proves the seam hits
Rust when Tauri is present), then revert that temporary line.

- [ ] **Step 9: Commit**

```bash
git add src-tauri
git commit -m "M1: Tauri 2 Rust shell — health command, tray stub, single-instance"
```

---

## Task 11: M1 exit verification

**Files:** none (gate)

- [ ] **Step 1: Full test + build sweep**

Run:
```bash
npm run test && npm run build && npm run test:ui -- capture
```
Expected: Vitest green (tokens, library, ipc, stores), `vite build` writes `build/`, 6
Playwright shots pass.

- [ ] **Step 2: Run the UI-review workflow on the shell and clear blockers**

Orchestrator invokes `workflows/ui-review.mjs` over `artifacts/ui/shell-dark.png` and
`artifacts/ui/shell-light.png`. Fix any `blocker`/`major` findings, re-shoot, re-review
until `failures` is empty.

- [ ] **Step 3: Tag the milestone**

```bash
git tag m1-foundation
git commit --allow-empty -m "M1 complete: foundation + UI-review harness green"
```

---

## Self-Review notes (author)

- **Spec coverage:** shell layout (corrected: sidebar=library list, header=capture
  actions) ✓; tokens clone ✓; mockable IPC seam ✓; screenshot harness (light+dark) ✓;
  wonderblob reference ✓; vision-critique workflow ✓; single-instance + tray ✓; Vitest ✓.
  Deferred to later milestones by design: real capture/record/editor/video/settings/
  bg-removal/packaging (M2–M6).
- **No placeholders:** every code step contains complete, runnable content.
- **Type consistency:** `Capture`/`LibraryGroup`/`RecordingState` defined in Task 3 and
  used unchanged in Tasks 4–6; `ipcInvoke`/`ipcListen` defined in Task 4 and used in Task
  5; `groupByDate(captures, now)` signature consistent between Task 3 and LibrarySidebar.
