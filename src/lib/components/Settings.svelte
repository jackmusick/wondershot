<script lang="ts">
  import { onMount } from 'svelte';
  import { ipcInvoke, ipcEmit } from '$lib/ipc';
  import { settingsOpen } from '$lib/stores';

  type Device = { id: string; label: string };
  let cameras = $state<Device[]>([]);
  let mics = $state<Device[]>([]);

  /** Enumerate webcam / mic inputs for the device dropdowns. Labels are only
   * populated once the user has granted camera/mic permission (e.g. after the
   * camera bubble has run once); until then we fall back to generic names. */
  async function enumerateDevices() {
    if (typeof navigator === 'undefined' || !navigator.mediaDevices?.enumerateDevices) return;
    try {
      // Device labels + stable ids are only exposed after a getUserMedia grant.
      // Probe briefly (cam + mic), then release — otherwise the dropdowns only
      // ever show generic "Camera 1 / Microphone 1" placeholders.
      try {
        const probe = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
        probe.getTracks().forEach((t) => t.stop());
      } catch {
        // permission denied / no device — fall back to generic names below
      }
      const devs = await navigator.mediaDevices.enumerateDevices();
      cameras = devs
        .filter((d) => d.kind === 'videoinput')
        .map((d, i) => ({ id: d.deviceId, label: d.label || `Camera ${i + 1}` }));
      mics = devs
        .filter((d) => d.kind === 'audioinput')
        .map((d, i) => ({ id: d.deviceId, label: d.label || `Microphone ${i + 1}` }));
    } catch {
      // ignore — selects fall back to the stored value
    }
  }

  let { open = false }: { open?: boolean } = $props();
  // `open` prop forces the modal open (harness/refshots); otherwise the store drives it.
  let visible = $derived(open || $settingsOpen);

  type Tab = 'general' | 'capture' | 'recording' | 'output' | 'sharing' | 'ai';
  let tab = $state<Tab>('general');

  type SettingsData = Record<string, unknown>;
  let s = $state<SettingsData>({});
  let loaded = $state(false);

  async function loadSettings() {
    const data = (await ipcInvoke<SettingsData>('get_settings')) ?? {};
    // extra_dirs is an array on the wire; edit it as a semicolon-joined string.
    const dirs = Array.isArray(data.extra_dirs) ? (data.extra_dirs as string[]) : [];
    s = { ...data, extra_dirs_text: dirs.join(';') };
    loaded = true;
    void enumerateDevices();
    void loadGraph();
  }

  onMount(() => {
    if (open) loadSettings();
  });

  // When opened via the store (gear), (re)load the form.
  let wasOpen = false;
  $effect(() => {
    if (visible && !wasOpen) loadSettings();
    wasOpen = visible;
  });

  function close() {
    settingsOpen.set(false);
  }

  // --- OneDrive / SharePoint (Graph) --------------------------------------
  let graphAccount = $state('');
  let defaultClientId = $state('');
  let connecting = $state(false);
  let connectMsg = $state('');
  let connectGen = 0;
  // Client ID: hidden behind "Wondershot Built-In" unless the user changes it.
  let clientCustom = $state(false);
  // Save-to: OneDrive vs a SharePoint library.
  let destMode = $state<'onedrive' | 'sharepoint'>('onedrive');
  let spQuery = $state('');
  let spSites = $state<Array<{ id: string; name: string; url: string }>>([]);
  let spSiteId = $state('');
  let spDrives = $state<Array<{ id: string; name: string }>>([]);
  let spBusy = $state('');

  async function loadGraph() {
    try {
      const r = (await ipcInvoke<{ account: string; default_client_id: string }>('graph_status')) ?? { account: '', default_client_id: '' };
      graphAccount = r.account ?? '';
      defaultClientId = r.default_client_id ?? '';
    } catch { graphAccount = ''; }
    const cid = String(s.graph_client_id ?? '');
    clientCustom = !!cid && cid !== defaultClientId;
    destMode = s.graph_drive_id ? 'sharepoint' : 'onedrive';
  }

  function clientId(): string {
    return clientCustom ? String(s.graph_client_id ?? '').trim() || defaultClientId : defaultClientId;
  }
  function toggleClient() {
    clientCustom = !clientCustom;
    if (!clientCustom) s.graph_client_id = '';
  }

  /** Primary sign-in: PKCE in the system browser; the redirect comes back as a
   *  wondershot://auth deep link (wonderblob's flow). The device-code path
   *  stays available via the "Use a device code instead" link. */
  async function graphConnect() {
    if (connecting) { connectGen++; connecting = false; connectMsg = ''; return; }   // cancel
    if (graphAccount) {                                                              // disconnect
      try { await ipcInvoke('graph_disconnect'); } catch {}
      graphAccount = '';
      return;
    }
    const gen = ++connectGen;
    connecting = true;
    connectMsg = 'Opening your browser — finish signing in there…';
    try {
      const account = await ipcInvoke<string>('graph_connect_interactive', { clientId: clientId() });
      if (connectGen !== gen) return;
      graphAccount = account || 'connected';
      connecting = false; connectMsg = '';
    } catch (e) {
      if (connectGen === gen) {
        const msg = e instanceof Error ? e.message : String(e);
        connectMsg = `${msg} — you can retry, or use a device code instead.`;
        connecting = false;
      }
    }
  }

  /** Fallback: OAuth device-code flow (no redirect URI / protocol handler
   *  needed — e.g. custom client ids without wondershot://auth registered). */
  async function graphConnectDeviceCode() {
    if (connecting || graphAccount) return;
    const gen = ++connectGen;
    connecting = true;
    connectMsg = 'Starting sign-in…';
    try {
      const start = await ipcInvoke<{ client_id: string; device_code: string; user_code: string; verification_uri: string; interval: number }>(
        'graph_connect_start', { clientId: clientId() }
      );
      connectMsg = `Enter code ${start.user_code} at ${start.verification_uri} (opening browser…)`;
      try { await ipcInvoke('open_url', { url: start.verification_uri }); } catch {}
      const interval = Math.max(2, Number(start.interval || 5));
      // Poll until connected / error / cancelled.
      while (connectGen === gen) {
        await new Promise((r) => setTimeout(r, interval * 1000));
        if (connectGen !== gen) return;
        const res = await ipcInvoke<{ status: string; account?: string }>('graph_connect_poll', {
          clientId: start.client_id, deviceCode: start.device_code,
        });
        if (res.status === 'connected') {
          graphAccount = res.account ?? 'connected';
          connecting = false; connectMsg = '';
          return;
        }
      }
    } catch (e) {
      if (connectGen === gen) { connectMsg = e instanceof Error ? e.message : String(e); connecting = false; }
    }
  }

  async function spFind() {
    if (!graphAccount) { spBusy = 'Connect first.'; return; }
    if (!spQuery.trim()) return;
    spBusy = 'Searching…';
    try {
      spSites = (await ipcInvoke('graph_sites_search', { query: spQuery.trim() })) ?? [];
      spBusy = spSites.length ? '' : 'No sites found.';
    } catch (e) { spBusy = e instanceof Error ? e.message : String(e); }
  }
  async function spSiteChosen(id: string) {
    spSiteId = id;
    spDrives = [];
    if (!id) return;
    spBusy = 'Loading libraries…';
    try {
      spDrives = (await ipcInvoke('graph_site_drives', { siteId: id })) ?? [];
      spBusy = '';
    } catch (e) { spBusy = e instanceof Error ? e.message : String(e); }
  }
  function spLibChosen(drive: { id: string; name: string }) {
    const site = spSites.find((x) => x.id === spSiteId);
    s.graph_drive_id = drive.id;
    s.graph_drive_label = site ? `${site.name} / ${drive.name}` : drive.name;
  }
  function destChanged(mode: 'onedrive' | 'sharepoint') {
    destMode = mode;
    if (mode === 'onedrive') { s.graph_drive_id = ''; s.graph_drive_label = ''; }
  }

  // AI endpoint connectivity test (AI tab).
  let aiTesting = $state(false);
  let aiResult = $state<{ ok: boolean; msg: string } | null>(null);
  async function testAi() {
    aiTesting = true;
    aiResult = null;
    try {
      const msg = await ipcInvoke<string>('test_ai_endpoint', {
        endpoint: String(s.ai_endpoint ?? ''),
        model: String(s.ai_model ?? ''),
        apiKey: String(s.ai_api_key ?? ''),
      });
      aiResult = { ok: true, msg };
    } catch (e) {
      aiResult = { ok: false, msg: e instanceof Error ? e.message : String(e) };
    } finally {
      aiTesting = false;
    }
  }

  async function save() {
    const snap = { ...$state.snapshot(s) } as SettingsData;
    // Map the edited semicolon string back to an extra_dirs array.
    const text = String(snap.extra_dirs_text ?? '');
    snap.extra_dirs = text
      .split(';')
      .map((x) => x.trim())
      .filter((x) => x.length > 0);
    delete snap.extra_dirs_text;
    await ipcInvoke('set_settings', { values: snap });
    // Tell the live camera bubble to re-init with the (possibly new) device.
    void ipcEmit('camera://changed', String(snap.camera_device ?? ''));
    close();
  }

  function onKey(e: KeyboardEvent) {
    if (e.key === 'Escape') close();
  }

  /** Portal folder picker → Library folder field. */
  async function browseLibrary() {
    try {
      const dir = await ipcInvoke<string | null>('pick_folder');
      if (dir) s.library_dir = dir;
    } catch (e) {
      console.error('pick_folder failed', e);
    }
  }

  /** Portal folder picker → appended to the semicolon-separated extra dirs. */
  async function addExtraFolder() {
    try {
      const dir = await ipcInvoke<string | null>('pick_folder');
      if (!dir) return;
      const cur = String(s.extra_dirs_text ?? '').trim();
      s.extra_dirs_text = cur ? `${cur};${dir}` : dir;
    } catch (e) {
      console.error('pick_folder failed', e);
    }
  }

  let shortcutsErr = $state('');
  async function openShortcuts() {
    shortcutsErr = '';
    try {
      await ipcInvoke('open_shortcut_settings');
    } catch (e) {
      shortcutsErr = String(e);
    }
  }

  // Typed accessors keep bind:value happy with the loose record.
  function num(k: string): number {
    return Number(s[k] ?? 0);
  }
  function setNum(k: string, v: number) {
    s[k] = v;
  }
</script>

<svelte:window on:keydown={onKey} />

{#if visible && loaded}
  <div class="overlay" role="dialog" aria-modal="true" aria-label="Settings">
    <button class="backdrop" aria-label="Close settings" onclick={close}></button>
    <div class="panel" data-settings-ready="true">
      <div class="head">
        <h2>Settings</h2>
      </div>

      <div class="tabs" role="tablist">
        <button class="tab" class:active={tab === 'general'} role="tab" onclick={() => (tab = 'general')}>General</button>
        <button class="tab" class:active={tab === 'capture'} role="tab" onclick={() => (tab = 'capture')}>Capture</button>
        <button class="tab" class:active={tab === 'recording'} role="tab" onclick={() => (tab = 'recording')}>Recording</button>
        <button class="tab" class:active={tab === 'output'} role="tab" onclick={() => (tab = 'output')}>Output</button>
        <button class="tab" class:active={tab === 'sharing'} role="tab" onclick={() => (tab = 'sharing')}>Sharing</button>
        <button class="tab" class:active={tab === 'ai'} role="tab" onclick={() => (tab = 'ai')}>AI</button>
      </div>

      <div class="body">
        {#if tab === 'general'}
          <label class="field">
            <span>Library folder</span>
            <span class="withbtn">
              <input type="text" bind:value={s.library_dir} />
              <button class="btn" onclick={browseLibrary}>Browse…</button>
            </span>
            <small>Where screenshots and recordings are saved.</small>
          </label>
          <label class="field">
            <span>Extra folders</span>
            <span class="withbtn">
              <input type="text" bind:value={s.extra_dirs_text} placeholder="/path/one;/path/two" />
              <button class="btn" onclick={addExtraFolder}>Add…</button>
            </span>
            <small>Semicolon-separated extra folders to show in the library.</small>
          </label>
          <label class="check"><input type="checkbox" bind:checked={s.copy_after_capture} /> Copy to clipboard after capture</label>
          <label class="check"><input type="checkbox" bind:checked={s.show_gallery_after_capture} /> Show gallery after capture</label>
          <label class="check"><input type="checkbox" bind:checked={s.pin_on_top} /> Pin window on top</label>
          <label class="check"><input type="checkbox" bind:checked={s.quick_bar_enabled} /> Enable quick bar</label>
          <label class="field row">
            <span>Quick bar timeout (s)</span>
            <input type="number" min="2" max="60" value={num('quick_bar_timeout')} oninput={(e) => setNum('quick_bar_timeout', e.currentTarget.valueAsNumber)} />
          </label>
          <label class="field">
            <span>Capture hotkey</span>
            <input type="text" bind:value={s.hotkey_capture} />
            <small>On Linux, bind this manually in KDE settings — shown here for reference.</small>
          </label>
          <fieldset class="group">
            <legend>Global capture hotkey</legend>
            <small>
              Bind a key (e.g. <b>Meta+Shift+S</b>) to the command below in your desktop's
              shortcut settings. It reaches the running Wondershot instantly.
            </small>
            <input type="text" readonly value="wondershot --capture" onfocus={(e) => e.currentTarget.select()} />
            <button class="btn wide" onclick={openShortcuts}>Open KDE Shortcuts settings</button>
            {#if shortcutsErr}<small class="err">{shortcutsErr}</small>{/if}
          </fieldset>
        {:else if tab === 'capture'}
          <label class="field row">
            <span>Backend</span>
            <select bind:value={s.backend}>
              <option value="auto">Auto</option>
              <option value="spectacle">Spectacle</option>
              <option value="portal">Portal</option>
            </select>
          </label>
          <label class="check"><input type="checkbox" bind:checked={s.capture_cursor} /> Capture cursor</label>
          <label class="field row">
            <span>Capture delay (s)</span>
            <input type="number" min="0" max="10" value={num('capture_delay')} oninput={(e) => setNum('capture_delay', e.currentTarget.valueAsNumber)} />
          </label>
        {:else if tab === 'recording'}
          <label class="check"><input type="checkbox" bind:checked={s.mic_enabled} /> Record microphone</label>
          <label class="field">
            <span>Microphone device</span>
            <!-- Stored value is the device LABEL (description), not the webview
                 deviceId: ids are origin-scoped hashes that change across app
                 restarts, and the shared wondershot.conf is also read by the
                 Python app, which stores Qt device descriptions. -->
            <select bind:value={s.mic_device}>
              <option value="">Default</option>
              {#each mics as d (d.id)}
                <option value={d.label}>{d.label}</option>
              {/each}
              {#if s.mic_device && !mics.some((d) => d.label === s.mic_device)}
                <option value={s.mic_device}>{s.mic_device}</option>
              {/if}
            </select>
          </label>
          <label class="check"><input type="checkbox" bind:checked={s.noise_suppression} /> Noise suppression</label>
          <label class="field row">
            <span>Countdown (s, 0 = off)</span>
            <input type="number" min="0" max="10" value={num('record_countdown')} oninput={(e) => setNum('record_countdown', e.currentTarget.valueAsNumber)} />
          </label>
          <label class="field">
            <span>Camera device</span>
            <select bind:value={s.camera_device}>
              <option value="">None / default</option>
              {#each cameras as d (d.id)}
                <option value={d.label}>{d.label}</option>
              {/each}
              {#if s.camera_device && !cameras.some((d) => d.label === s.camera_device)}
                <option value={s.camera_device}>{s.camera_device}</option>
              {/if}
            </select>
            <small>Drives the camera bubble. Names appear after granting camera access once.</small>
          </label>
          <label class="check"><input type="checkbox" bind:checked={s.record_cursor_halo} disabled /> Cursor halo <small class="inline">(coming soon)</small></label>
          <label class="field row">
            <span>Video blur strength</span>
            <input type="number" min="1" max="60" value={num('video_blur_strength')} oninput={(e) => setNum('video_blur_strength', e.currentTarget.valueAsNumber)} />
          </label>
          <label class="field row">
            <span>GIF fps</span>
            <input type="number" min="4" max="30" value={num('gif_fps')} oninput={(e) => setNum('gif_fps', e.currentTarget.valueAsNumber)} />
          </label>
          <label class="field row">
            <span>GIF max width</span>
            <input type="number" min="160" max="1920" value={num('gif_max_width')} oninput={(e) => setNum('gif_max_width', e.currentTarget.valueAsNumber)} />
          </label>
        {:else if tab === 'output'}
          <label class="check"><input type="checkbox" bind:checked={s.effect_rounded} /> Rounded corners</label>
          <label class="field row">
            <span>Corner radius</span>
            <input type="number" min="2" max="64" value={num('effect_corner_radius')} oninput={(e) => setNum('effect_corner_radius', e.currentTarget.valueAsNumber)} />
          </label>
          <label class="check"><input type="checkbox" bind:checked={s.effect_fade} /> Fade edges</label>
          <label class="field row">
            <span>Fade height</span>
            <input type="number" min="8" max="512" value={num('effect_fade_height')} oninput={(e) => setNum('effect_fade_height', e.currentTarget.valueAsNumber)} />
          </label>
          <div class="divider"></div>
          <label class="field row">
            <span>Editor stroke width</span>
            <input type="number" min="1" max="32" value={num('stroke_width')} oninput={(e) => setNum('stroke_width', e.currentTarget.valueAsNumber)} />
          </label>
          <label class="field row">
            <span>Editor font size</span>
            <input type="number" min="6" max="96" value={num('font_size')} oninput={(e) => setNum('font_size', e.currentTarget.valueAsNumber)} />
          </label>
          <label class="field row">
            <span>Tool color</span>
            <input type="color" bind:value={s.tool_color} />
          </label>
        {:else if tab === 'sharing'}
          <p class="note">
            Upload a capture to a cloud target and copy a share link. Credentials are
            shared with the previous Wondershot, so an existing sign-in carries over.
          </p>
          <label class="field row">
            <span>Default provider</span>
            <select bind:value={s.share_provider}>
              <option value="onedrive">OneDrive / SharePoint</option>
              <option value="s3">S3-compatible</option>
              <option value="azure">Azure Blob</option>
            </select>
          </label>
          <label class="field row">
            <span>Link expiry (days)</span>
            <input type="number" min="0" max="365" value={num('share_expiry_days')} oninput={(e) => setNum('share_expiry_days', e.currentTarget.valueAsNumber)} />
          </label>
          <div class="divider"></div>
          <div class="group-label">S3-compatible (AWS, MinIO, B2, R2…)</div>
          <label class="field"><span>Endpoint</span><input type="text" bind:value={s.s3_endpoint} placeholder="https://s3.amazonaws.com" /></label>
          <label class="field"><span>Bucket</span><input type="text" bind:value={s.s3_bucket} /></label>
          <label class="field"><span>Region</span><input type="text" bind:value={s.s3_region} /></label>
          <label class="field"><span>Access key</span><input type="text" bind:value={s.s3_access_key} /></label>
          <label class="field"><span>Secret key</span><input type="password" bind:value={s.s3_secret_key} /></label>
          <div class="divider"></div>
          <div class="group-label">Azure Blob Storage</div>
          <label class="field"><span>Account</span><input type="text" bind:value={s.azure_account} /></label>
          <label class="field"><span>Container</span><input type="text" bind:value={s.azure_container} /></label>
          <label class="field"><span>Key</span><input type="password" bind:value={s.azure_key} /></label>
          <div class="divider"></div>
          <div class="group-label">OneDrive / SharePoint (Microsoft account)</div>

          <div class="od">
            <div class="od-row">
              <span class="od-label">Status</span>
              <span class="status" class:connected={graphAccount}>
                {graphAccount ? `Connected as ${graphAccount}` : 'Not connected'}
              </span>
              <button class="btn ghost od-connect" onclick={graphConnect}>
                {connecting ? 'Cancel' : graphAccount ? 'Disconnect' : 'Connect…'}
              </button>
            </div>
            {#if connectMsg}<div class="connect-msg">{connectMsg}</div>{/if}
            {#if !graphAccount && !connecting}
              <button class="linklike" onclick={graphConnectDeviceCode}>Use a device code instead</button>
            {/if}

            <div class="od-row">
              <span class="od-label">Save to</span>
              <select value={destMode} onchange={(e) => destChanged(e.currentTarget.value as 'onedrive' | 'sharepoint')}>
                <option value="onedrive">My OneDrive</option>
                <option value="sharepoint">A SharePoint site</option>
              </select>
            </div>

            {#if destMode === 'sharepoint'}
              <div class="sp-box">
                <div class="od-row">
                  <span class="od-label">Site</span>
                  <input class="grow" type="text" bind:value={spQuery} placeholder="search site name…"
                    onkeydown={(e) => e.key === 'Enter' && spFind()} />
                  <button class="btn ghost" onclick={spFind}>Find</button>
                </div>
                {#if spSites.length}
                  <div class="od-row">
                    <span class="od-label"></span>
                    <select class="grow" value={spSiteId} onchange={(e) => spSiteChosen(e.currentTarget.value)}>
                      <option value="">Select a site…</option>
                      {#each spSites as site (site.id)}<option value={site.id}>{site.name}</option>{/each}
                    </select>
                  </div>
                {/if}
                {#if spDrives.length}
                  <div class="od-row">
                    <span class="od-label">Library</span>
                    <select class="grow" onchange={(e) => { const d = spDrives.find((x) => x.id === e.currentTarget.value); if (d) spLibChosen(d); }}>
                      <option value="">Select a library…</option>
                      {#each spDrives as d (d.id)}<option value={d.id}>{d.name}</option>{/each}
                    </select>
                  </div>
                {/if}
                {#if s.graph_drive_label}<div class="selected">Selected: {s.graph_drive_label}</div>{/if}
                {#if spBusy}<div class="connect-msg">{spBusy}</div>{/if}
              </div>
            {/if}

            <div class="od-row">
              <span class="od-label">App</span>
              {#if clientCustom}
                <input class="grow" type="text" bind:value={s.graph_client_id} placeholder="your Azure app client ID" />
                <button class="btn ghost" onclick={toggleClient}>Use default</button>
              {:else}
                <span class="builtin grow">Wondershot Built-In</span>
                <button class="btn ghost" onclick={toggleClient}>Change</button>
              {/if}
            </div>
          </div>
        {:else if tab === 'ai'}
          <p class="note">
            Used by AI Redact / Simplify and the bg-removal helpers. OpenAI-compatible
            endpoint. The inference wiring is in progress; the endpoint is stored for parity.
          </p>
          <label class="field"><span>Endpoint</span><input type="text" bind:value={s.ai_endpoint} placeholder="https://openrouter.ai/api" /></label>
          <label class="field"><span>Model</span><input type="text" bind:value={s.ai_model} placeholder="google/gemini-2.5-flash" /></label>
          <label class="field"><span>API key</span><input type="password" bind:value={s.ai_api_key} /></label>
          <div class="ai-test">
            <button class="btn ghost ai-btn" class:ok={aiResult?.ok} class:err={aiResult && !aiResult.ok} onclick={testAi} disabled={aiTesting}>
              {#if aiTesting}<span class="spin" aria-hidden="true"></span> Testing…
              {:else if aiResult?.ok}<span class="mark">✓</span> Connected
              {:else if aiResult}<span class="mark">✕</span> Failed
              {:else}Test connection{/if}
            </button>
          </div>
          {#if aiResult && !aiResult.ok}
            <small class="ai-result err">{aiResult.msg}</small>
          {/if}
        {/if}
      </div>

      <div class="foot">
        <button class="btn ghost" onclick={close}>Cancel</button>
        <button class="btn primary" onclick={save}>Save</button>
      </div>
    </div>
  </div>
{/if}

<style>
  .overlay {
    position: fixed;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 100;
  }
  .backdrop {
    position: absolute;
    inset: 0;
    border: none;
    padding: 0;
    background: rgba(0, 0, 0, 0.3);
    cursor: default;
  }
  .panel {
    position: relative;
    width: 480px;
    max-height: 80vh;
    display: flex;
    flex-direction: column;
    background: var(--bg-elevated);
    border: 1px solid var(--border-strong);
    border-radius: 10px;
    box-shadow: 0 16px 44px rgba(0, 0, 0, 0.45);
    padding: 16px;
    color: var(--fg-primary);
    font-family: var(--font-ui);
    font-size: var(--text-base);
  }
  .head h2 {
    margin: 0 0 12px;
    font-size: 15px;
    font-weight: 600;
  }
  .tabs {
    display: flex;
    gap: 2px;
    border-bottom: 1px solid var(--border);
    margin-bottom: 12px;
  }
  .tab {
    border: none;
    background: transparent;
    color: var(--fg-secondary);
    padding: 6px 10px;
    border-radius: var(--radius) var(--radius) 0 0;
    cursor: default;
    font-size: var(--text-base);
  }
  .tab:hover {
    background: var(--bg-hover);
    color: var(--fg-primary);
  }
  .tab.active {
    color: var(--fg-primary);
    box-shadow: inset 0 -2px 0 var(--accent);
  }
  .body {
    flex: 1;
    overflow-y: auto;
    /* Reserve the scrollbar gutter so it never overlaps the inputs. */
    scrollbar-gutter: stable;
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 2px 12px 4px 2px;
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 4px;
  }
  .field span {
    color: var(--fg-secondary);
    font-size: var(--text-small);
  }
  .field.row {
    flex-direction: row;
    align-items: center;
    justify-content: space-between;
  }
  .field.row input {
    width: 100px;
  }
  small {
    color: var(--fg-secondary);
    font-size: var(--text-small);
  }
  small.inline {
    margin-left: 4px;
  }
  input[type='text'],
  input[type='number'],
  select {
    height: 28px;
    background: var(--bg-field);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    color: var(--fg-primary);
    padding: 0 8px;
    font-size: var(--text-base);
    font-family: var(--font-ui);
  }
  input[type='color'] {
    height: 28px;
    width: 48px;
    padding: 0 2px;
    background: var(--bg-field);
    border: 1px solid var(--border);
    border-radius: var(--radius);
  }
  .check {
    display: flex;
    align-items: center;
    gap: 8px;
    color: var(--fg-primary);
  }
  .check input[disabled] {
    opacity: 0.5;
  }
  .divider {
    height: 1px;
    background: var(--border);
    margin: 4px 0;
  }
  .note {
    margin: 0;
    color: var(--fg-secondary);
    font-size: var(--text-small);
    line-height: 1.4;
  }
  .withbtn {
    display: flex;
    gap: 6px;
    align-items: center;
  }
  .withbtn input { flex: 1; min-width: 0; }
  .btn {
    height: 28px;
    padding: 0 12px;
    border: 1px solid var(--border);
    background: var(--bg-field);
    color: var(--fg-primary);
    border-radius: var(--radius);
    cursor: pointer;
    font-size: var(--text-small);
    white-space: nowrap;
    flex-shrink: 0;
  }
  .btn:hover { background: var(--bg-hover); }
  .btn.wide { width: 100%; margin-top: 6px; }
  .group {
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 10px 12px 12px;
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin: 4px 0 0;
  }
  .group legend {
    font-weight: 600;
    font-size: var(--text-small);
    color: var(--fg-primary);
    padding: 0 4px;
  }
  .group small { color: var(--fg-secondary); line-height: 1.4; }
  .group input[readonly] {
    font-family: monospace;
    color: var(--fg-primary);
    background: var(--bg-field);
  }
  .err { color: var(--danger); }
  .linklike {
    background: none;
    border: none;
    padding: 0;
    color: var(--accent);
    font-size: var(--text-small);
    cursor: pointer;
    text-align: left;
    text-decoration: underline;
  }
  .group-label {
    font-weight: 600;
    color: var(--fg-primary);
    font-size: var(--text-small);
  }
  .ai-test {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-top: 4px;
  }
  .ai-result {
    font-size: var(--text-small);
    line-height: 1.3;
  }
  .ai-result.ok { color: var(--accent); }
  .ai-result.err { color: var(--danger); }
  .ai-btn { display: inline-flex; align-items: center; gap: 7px; min-width: 132px; justify-content: center; }
  .ai-btn.ok { border-color: var(--accent); color: var(--accent); }
  .ai-btn.err { border-color: var(--danger); color: var(--danger); }
  .ai-btn .mark { font-weight: 700; }
  .spin {
    width: 12px; height: 12px; border-radius: 50%;
    border: 2px solid var(--fg-secondary); border-top-color: transparent;
    display: inline-block; animation: spin 0.7s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  /* OneDrive group: left-aligned label + control rows (not space-between). */
  .od { display: flex; flex-direction: column; gap: 9px; }
  .od-row { display: flex; align-items: center; gap: 8px; }
  .od-label { flex: 0 0 64px; color: var(--fg-secondary); font-size: var(--text-small); }
  .od-row .grow { flex: 1 1 auto; min-width: 0; }
  .od-row select { min-width: 180px; }
  .od-connect { margin-left: auto; }
  .status { color: var(--fg-secondary); font-size: var(--text-base); }
  .status.connected { color: var(--accent); }
  .connect-msg { color: var(--fg-secondary); font-size: var(--text-small); line-height: 1.4; word-break: break-word; }
  .selected { color: var(--accent); font-size: var(--text-small); }
  .builtin { color: var(--fg-secondary); font-size: var(--text-base); }
  .sp-box {
    display: flex; flex-direction: column; gap: 8px;
    padding: 10px; border: 1px solid var(--border); border-radius: var(--radius);
    background: var(--bg-field);
  }
  .foot {
    display: flex;
    justify-content: flex-end;
    gap: 8px;
    margin-top: 14px;
  }
  .btn {
    height: 28px;
    padding: 0 14px;
    border-radius: var(--radius);
    border: 1px solid transparent;
    cursor: default;
    font-size: var(--text-base);
    font-family: var(--font-ui);
  }
  .btn.primary {
    background: var(--accent);
    color: #fff;
  }
  .btn.primary:hover {
    background: var(--accent-strong);
  }
  .btn.ghost {
    background: transparent;
    border-color: var(--border);
    color: var(--fg-primary);
  }
  .btn.ghost:hover {
    background: var(--bg-hover);
  }
</style>
