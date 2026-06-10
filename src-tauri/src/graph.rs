//! OneDrive / SharePoint via Microsoft Graph — a Rust port of the Python
//! `wondershot.msgraph` module so the Tauri app's Settings → Sharing → OneDrive
//! group works (Status / Connect / Save-to). Auth is the OAuth2 device-code flow
//! against a public client (no secret, no redirect URI). Tokens are cached in a
//! 0600 JSON file at the SAME path the Python app uses, so a sign-in in either
//! app carries over to the other.

use serde_json::{json, Value};
use std::path::PathBuf;

pub const DEFAULT_CLIENT_ID: &str = "cf7aef3a-2dc5-4b58-b247-2e61fe6a98cc";
const AUTH_BASE: &str = "https://login.microsoftonline.com/common/oauth2/v2.0";
const GRAPH: &str = "https://graph.microsoft.com/v1.0";
const SCOPE: &str = "Files.ReadWrite offline_access openid profile";

fn home() -> PathBuf {
    PathBuf::from(std::env::var("HOME").unwrap_or_default())
}

/// Where the cached tokens live — mirrors the Python `token_path()`. In a
/// Flatpak the real host `~/.local/share` is reachable via `--filesystem=home`,
/// so target it directly to share the sign-in with the host (pip/AppImage) app.
fn token_path() -> PathBuf {
    if std::env::var_os("FLATPAK_ID").is_some() {
        return home().join(".local/share/wondershot/graph_token.json");
    }
    let base = std::env::var_os("WONDERSHOT_DATA_DIR")
        .map(PathBuf::from)
        .or_else(|| std::env::var_os("XDG_DATA_HOME").map(PathBuf::from))
        .unwrap_or_else(|| home().join(".local/share"));
    base.join("wondershot/graph_token.json")
}

fn now_secs() -> f64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs_f64())
        .unwrap_or(0.0)
}

fn err_of(v: &Value, fallback: &str) -> String {
    v.get("error_description")
        .and_then(|x| x.as_str())
        .or_else(|| v.get("error").and_then(|x| x.as_str()))
        .unwrap_or(fallback)
        .to_string()
}

/// POST an x-www-form-urlencoded body; OAuth errors come back as JSON bodies
/// (HTTP 400), so decode those too rather than treating them as transport errors.
fn post_form(url: &str, fields: &[(&str, &str)]) -> Result<Value, String> {
    match ureq::post(url).send_form(fields) {
        Ok(resp) => resp.into_json::<Value>().map_err(|e| e.to_string()),
        Err(ureq::Error::Status(_, resp)) => resp.into_json::<Value>().map_err(|e| e.to_string()),
        Err(e) => Err(e.to_string()),
    }
}

fn graph_get(url: &str, token: &str) -> Result<Value, String> {
    match ureq::get(url)
        .set("Authorization", &format!("Bearer {token}"))
        .call()
    {
        Ok(resp) => resp.into_json::<Value>().map_err(|e| e.to_string()),
        Err(ureq::Error::Status(code, resp)) => {
            let body = resp.into_string().unwrap_or_default();
            Err(format!("Graph HTTP {code}: {}", body.chars().take(200).collect::<String>()))
        }
        Err(e) => Err(e.to_string()),
    }
}

// -- device code flow --------------------------------------------------------

/// Start the flow: returns user_code / verification_uri / device_code / interval.
pub fn request_device_code(client_id: &str) -> Result<Value, String> {
    let out = post_form(
        &format!("{AUTH_BASE}/devicecode"),
        &[("client_id", client_id), ("scope", SCOPE)],
    )?;
    if out.get("device_code").is_none() {
        return Err(err_of(&out, "device code request failed"));
    }
    Ok(out)
}

/// One poll. `Ok(Some(tokens))` when signed in, `Ok(None)` while pending.
pub fn poll_token(client_id: &str, device_code: &str) -> Result<Option<Value>, String> {
    let out = post_form(
        &format!("{AUTH_BASE}/token"),
        &[
            ("client_id", client_id),
            ("grant_type", "urn:ietf:params:oauth:grant-type:device_code"),
            ("device_code", device_code),
        ],
    )?;
    if out.get("access_token").is_some() {
        return Ok(Some(out));
    }
    match out.get("error").and_then(|e| e.as_str()) {
        Some("authorization_pending") | Some("slow_down") => Ok(None),
        _ => Err(err_of(&out, "auth failed")),
    }
}

// -- token cache -------------------------------------------------------------

pub fn save_tokens(tokens: &Value, client_id: &str, account: &str) -> Result<(), String> {
    let path = token_path();
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let expires_in = tokens.get("expires_in").and_then(|v| v.as_f64()).unwrap_or(3600.0);
    let payload = json!({
        "client_id": client_id,
        "account": account,
        "access_token": tokens.get("access_token").and_then(|v| v.as_str()).unwrap_or(""),
        "refresh_token": tokens.get("refresh_token").and_then(|v| v.as_str()).unwrap_or(""),
        "expires_at": now_secs() + expires_in - 60.0,
    });
    std::fs::write(&path, payload.to_string()).map_err(|e| e.to_string())?;
    // Best-effort 0600 (the file holds refresh tokens).
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let _ = std::fs::set_permissions(&path, std::fs::Permissions::from_mode(0o600));
    }
    Ok(())
}

fn load_tokens() -> Option<Value> {
    std::fs::read_to_string(token_path())
        .ok()
        .and_then(|s| serde_json::from_str::<Value>(&s).ok())
}

/// '' when not connected, else the account label saved at connect.
pub fn connected_account() -> String {
    load_tokens()
        .and_then(|t| t.get("account").and_then(|a| a.as_str()).map(String::from))
        .filter(|a| !a.is_empty())
        .unwrap_or_default()
}

pub fn disconnect() {
    let _ = std::fs::remove_file(token_path());
}

/// A valid access token, refreshing via the refresh_token when expired.
pub fn ensure_access_token() -> Result<String, String> {
    let t = load_tokens().ok_or("OneDrive is not connected (Settings → Sharing)")?;
    let expires_at = t.get("expires_at").and_then(|v| v.as_f64()).unwrap_or(0.0);
    let access = t.get("access_token").and_then(|v| v.as_str()).unwrap_or("");
    if now_secs() < expires_at && !access.is_empty() {
        return Ok(access.to_string());
    }
    let client_id = t.get("client_id").and_then(|v| v.as_str()).unwrap_or(DEFAULT_CLIENT_ID);
    let refresh = t.get("refresh_token").and_then(|v| v.as_str()).unwrap_or("");
    let out = post_form(
        &format!("{AUTH_BASE}/token"),
        &[
            ("client_id", client_id),
            ("grant_type", "refresh_token"),
            ("refresh_token", refresh),
            ("scope", SCOPE),
        ],
    )?;
    if out.get("access_token").is_none() {
        return Err("OneDrive session expired — reconnect in Settings".into());
    }
    let account = t.get("account").and_then(|v| v.as_str()).unwrap_or("");
    save_tokens(&out, client_id, account)?;
    Ok(out.get("access_token").and_then(|v| v.as_str()).unwrap_or("").to_string())
}

pub fn whoami(token: &str) -> Result<String, String> {
    let me = graph_get(&format!("{GRAPH}/me"), token)?;
    Ok(me
        .get("userPrincipalName")
        .and_then(|v| v.as_str())
        .or_else(|| me.get("displayName").and_then(|v| v.as_str()))
        .unwrap_or("connected")
        .to_string())
}

// -- SharePoint browse -------------------------------------------------------

pub fn sites_search(token: &str, query: &str) -> Result<Vec<Value>, String> {
    let q = urlencoding_minimal(query);
    let out = graph_get(&format!("{GRAPH}/sites?search={q}"), token)?;
    Ok(out
        .get("value")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .map(|s| {
                    json!({
                        "id": s.get("id").and_then(|v| v.as_str()).unwrap_or(""),
                        "name": s.get("displayName").or_else(|| s.get("name")).and_then(|v| v.as_str()).unwrap_or("?"),
                        "url": s.get("webUrl").and_then(|v| v.as_str()).unwrap_or(""),
                    })
                })
                .collect()
        })
        .unwrap_or_default())
}

pub fn site_drives(token: &str, site_id: &str) -> Result<Vec<Value>, String> {
    let out = graph_get(&format!("{GRAPH}/sites/{site_id}/drives"), token)?;
    Ok(out
        .get("value")
        .and_then(|v| v.as_array())
        .map(|arr| {
            arr.iter()
                .map(|d| {
                    json!({
                        "id": d.get("id").and_then(|v| v.as_str()).unwrap_or(""),
                        "name": d.get("name").and_then(|v| v.as_str()).unwrap_or("Documents"),
                    })
                })
                .collect()
        })
        .unwrap_or_default())
}

/// Minimal percent-encoding for the `search=` query value (spaces + a few
/// reserved chars); avoids pulling a urlencoding crate for one call site.
fn urlencoding_minimal(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => out.push(b as char),
            _ => out.push_str(&format!("%{b:02X}")),
        }
    }
    out
}

// -- interactive auth-code + PKCE flow (browser redirect) ---------------------
//
// Pattern ported from wonderblob's onedrive_auth.rs: open the system browser
// to the authorize URL with a CUSTOM-SCHEME redirect (`wondershot://auth`),
// catch the callback via the OS protocol handler (the .desktop registers
// x-scheme-handler/wondershot; the second invocation forwards the URL through
// the single-instance plugin), validate `state`, and exchange code+verifier.
// The redirect URI must be registered in the Entra app under "Mobile and
// desktop applications" for the client id in use.

/// The custom-scheme redirect registered in Entra.
pub const REDIRECT_URI: &str = "wondershot://auth";

/// A URL-safe random string (PKCE verifier / CSRF state) from the OS RNG.
fn random_urlsafe(len: usize) -> String {
    use base64::Engine;
    let mut bytes = vec![0u8; len];
    let _ = getrandom::getrandom(&mut bytes);
    let s = base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(&bytes);
    s.chars().take(len).collect()
}

/// (verifier, S256 challenge): challenge = base64url(SHA256(verifier)).
pub fn pkce() -> (String, String) {
    use base64::Engine;
    use sha2::Digest;
    let verifier = random_urlsafe(64);
    let challenge = base64::engine::general_purpose::URL_SAFE_NO_PAD
        .encode(sha2::Sha256::digest(verifier.as_bytes()));
    (verifier, challenge)
}

/// Build the authorize URL for the browser.
pub fn authorize_url(client_id: &str, challenge: &str, state: &str) -> String {
    format!(
        "{AUTH_BASE}/authorize?client_id={client_id}&response_type=code\
         &redirect_uri={}&response_mode=query&scope={}\
         &code_challenge={challenge}&code_challenge_method=S256&state={state}",
        urlencoding_minimal(REDIRECT_URI),
        urlencoding_minimal(SCOPE),
    )
}

/// Minimal x-www-form-urlencoded percent-decoder (also handles `+`).
fn percent_decode(s: &str) -> String {
    let bytes = s.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        match bytes[i] {
            b'%' if i + 3 <= bytes.len() => {
                if let Ok(b) = u8::from_str_radix(
                    std::str::from_utf8(&bytes[i + 1..i + 3]).unwrap_or(""),
                    16,
                ) {
                    out.push(b);
                    i += 3;
                    continue;
                }
                out.push(bytes[i]);
                i += 1;
            }
            b'+' => {
                out.push(b' ');
                i += 1;
            }
            b => {
                out.push(b);
                i += 1;
            }
        }
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// Extract `(code, state)` from a `wondershot://auth?code=…&state=…` callback.
/// An `error=` redirect surfaces as Err.
pub fn parse_callback(url: &str) -> Result<(String, String), String> {
    let query = url.split_once('?').map(|(_, q)| q).unwrap_or("");
    let (mut code, mut state, mut error, mut error_desc) = (None, None, None, None);
    for pair in query.split('&') {
        let (k, v) = pair.split_once('=').unwrap_or((pair, ""));
        let v = percent_decode(v);
        match k {
            "code" => code = Some(v),
            "state" => state = Some(v),
            "error" => error = Some(v),
            "error_description" => error_desc = Some(v),
            _ => {}
        }
    }
    if let Some(e) = error {
        return Err(format!(
            "authorization error: {e}{}",
            error_desc.map(|d| format!(": {d}")).unwrap_or_default()
        ));
    }
    match (code, state) {
        (Some(c), Some(s)) => Ok((c, s)),
        _ => Err("redirect missing code/state".into()),
    }
}

/// Exchange the auth code + PKCE verifier for tokens at the token endpoint.
pub fn exchange_code(client_id: &str, code: &str, verifier: &str) -> Result<Value, String> {
    let out = post_form(
        &format!("{AUTH_BASE}/token"),
        &[
            ("client_id", client_id),
            ("grant_type", "authorization_code"),
            ("code", code),
            ("redirect_uri", REDIRECT_URI),
            ("code_verifier", verifier),
            ("scope", SCOPE),
        ],
    )?;
    if out.get("access_token").is_none() {
        return Err(err_of(&out, "token exchange failed"));
    }
    Ok(out)
}

#[cfg(test)]
mod auth_tests {
    use super::*;

    #[test]
    fn pkce_challenge_is_s256() {
        use base64::Engine;
        use sha2::Digest;
        let (v, c) = pkce();
        assert_eq!(v.len(), 64);
        assert_eq!(
            c,
            base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(sha2::Sha256::digest(v.as_bytes()))
        );
    }

    #[test]
    fn authorize_url_params() {
        let url = authorize_url("CID", "CHAL", "STATE");
        assert!(url.contains("client_id=CID"));
        assert!(url.contains("code_challenge=CHAL"));
        assert!(url.contains("code_challenge_method=S256"));
        assert!(url.contains("redirect_uri=wondershot%3A%2F%2Fauth"));
        assert!(url.contains("response_type=code"));
    }

    #[test]
    fn callback_parses_and_surfaces_errors() {
        let (c, s) = parse_callback("wondershot://auth?code=abc&state=xyz&extra=1").unwrap();
        assert_eq!((c.as_str(), s.as_str()), ("abc", "xyz"));
        assert!(parse_callback("wondershot://auth?error=access_denied").is_err());
        assert!(parse_callback("wondershot://auth").is_err());
    }
}

// -- upload + share link (msgraph.py upload/create_link/share port) -----------

const SIMPLE_UPLOAD_LIMIT: u64 = 4 * 1024 * 1024;
const UPLOAD_CHUNK: usize = 10 * 1024 * 1024; // multiple of 320 KiB

fn drive_base(drive_id: &str) -> String {
    // '' = the signed-in account's own OneDrive; a drive id targets a
    // specific SharePoint document library.
    if drive_id.is_empty() {
        format!("{GRAPH}/me/drive")
    } else {
        format!("{GRAPH}/drives/{drive_id}")
    }
}

/// Authenticated Graph request with a byte body; OAuth/Graph errors surface
/// with their JSON detail.
fn graph_send(method: &str, url: &str, token: &str, body: &[u8], ctype: &str) -> Result<Value, String> {
    let req = ureq::request(method, url)
        .timeout(std::time::Duration::from_secs(300))
        .set("Authorization", &format!("Bearer {token}"))
        .set("Content-Type", ctype);
    match req.send_bytes(body) {
        Ok(resp) => resp.into_json::<Value>().map_err(|e| e.to_string()),
        Err(ureq::Error::Status(code, resp)) => {
            let body = resp.into_string().unwrap_or_default();
            Err(format!("Graph HTTP {code}: {}", body.chars().take(200).collect::<String>()))
        }
        Err(e) => Err(e.to_string()),
    }
}

/// Upload to `/Wondershot/<name>`; returns the item id. Small files go in one
/// PUT; larger ones through an upload session in 10 MiB chunks (videos).
pub fn upload(path: &str, token: &str, drive_id: &str) -> Result<String, String> {
    use std::io::Read;
    let name = std::path::Path::new(path)
        .file_name()
        .map(|n| urlencoding_minimal(&n.to_string_lossy()))
        .ok_or("bad file name")?;
    let base = format!("{}/root:/Wondershot/{name}:", drive_base(drive_id));
    let size = std::fs::metadata(path).map_err(|e| e.to_string())?.len();

    if size <= SIMPLE_UPLOAD_LIMIT {
        let data = std::fs::read(path).map_err(|e| e.to_string())?;
        let item = graph_send("PUT", &format!("{base}/content"), token, &data, "application/octet-stream")?;
        return item
            .get("id")
            .and_then(|v| v.as_str())
            .map(String::from)
            .ok_or("upload returned no item id".into());
    }

    let session = graph_send(
        "POST",
        &format!("{base}/createUploadSession"),
        token,
        json!({"item": {"@microsoft.graph.conflictBehavior": "replace"}})
            .to_string()
            .as_bytes(),
        "application/json",
    )?;
    let url = session
        .get("uploadUrl")
        .and_then(|v| v.as_str())
        .ok_or("createUploadSession returned no uploadUrl")?;

    let mut f = std::fs::File::open(path).map_err(|e| e.to_string())?;
    let mut offset: u64 = 0;
    let mut item = Value::Null;
    let mut buf = vec![0u8; UPLOAD_CHUNK];
    while offset < size {
        let n = f.read(&mut buf).map_err(|e| e.to_string())?;
        if n == 0 {
            break;
        }
        let end = offset + n as u64 - 1;
        // Session PUTs are unauthenticated (the URL is the credential).
        let resp = ureq::put(url)
            .timeout(std::time::Duration::from_secs(300))
            .set("Content-Length", &n.to_string())
            .set("Content-Range", &format!("bytes {offset}-{end}/{size}"))
            .send_bytes(&buf[..n]);
        match resp {
            Ok(r) => {
                item = r.into_json::<Value>().unwrap_or(Value::Null);
            }
            Err(ureq::Error::Status(code, _)) => {
                return Err(format!("chunk upload failed: HTTP {code}"));
            }
            Err(e) => return Err(e.to_string()),
        }
        offset += n as u64;
    }
    item.get("id")
        .and_then(|v| v.as_str())
        .map(String::from)
        .ok_or("upload session returned no item id".into())
}

/// View link; anonymous when the tenant allows it, else org-scoped.
pub fn create_link(item_id: &str, token: &str, drive_id: &str) -> Result<String, String> {
    let mut last_err = String::new();
    for scope in ["anonymous", "organization"] {
        match graph_send(
            "POST",
            &format!("{}/items/{item_id}/createLink", drive_base(drive_id)),
            token,
            json!({"type": "view", "scope": scope}).to_string().as_bytes(),
            "application/json",
        ) {
            Ok(out) => {
                if let Some(url) = out.pointer("/link/webUrl").and_then(|v| v.as_str()) {
                    return Ok(url.to_string());
                }
                last_err = "createLink returned no webUrl".into();
            }
            Err(e) => last_err = e,
        }
    }
    Err(format!("createLink failed: {last_err}"))
}

/// Upload + link in one call (msgraph.share parity).
pub fn share(path: &str, drive_id: &str) -> Result<String, String> {
    let token = ensure_access_token()?;
    create_link(&upload(path, &token, drive_id)?, &token, drive_id)
}
