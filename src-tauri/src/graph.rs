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
