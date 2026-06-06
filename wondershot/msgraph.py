"""OneDrive / SharePoint sharing via Microsoft Graph — stdlib only.

Auth is the OAuth2 device-code flow against a public client (no secret,
no redirect URI involved): the app registration just needs "Allow
public client flows" enabled. Tokens (refresh + access) are cached in
a 0600 JSON file; uploads go to the signed-in account's OneDrive under
/Wondershot, links come from createLink (anonymous, falling back to
organization scope when the tenant forbids anonymous links).
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_CLIENT_ID = "cf7aef3a-2dc5-4b58-b247-2e61fe6a98cc"
AUTH_BASE = "https://login.microsoftonline.com/common/oauth2/v2.0"
GRAPH = "https://graph.microsoft.com/v1.0"
SCOPE = "Files.ReadWrite offline_access openid profile"
REDIRECT_URI = "wondershot://auth"


# -- authorization-code + PKCE (browser redirect, no secret) -----------------


def make_pkce() -> tuple[str, str]:
    """(code_verifier, code_challenge) for an S256 PKCE exchange."""
    verifier = base64.urlsafe_b64encode(
        secrets.token_bytes(64)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def new_state() -> str:
    return secrets.token_urlsafe(16)


def build_auth_url(client_id: str, code_challenge: str, state: str,
                   redirect_uri: str = REDIRECT_URI) -> str:
    return f"{AUTH_BASE}/authorize?" + urllib.parse.urlencode({
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": SCOPE,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    })


def exchange_code(client_id: str, code: str, code_verifier: str,
                  redirect_uri: str = REDIRECT_URI) -> dict:
    out = _post_form(f"{AUTH_BASE}/token", {
        "client_id": client_id,
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
    })
    if "access_token" not in out:
        raise OSError(out.get("error_description",
                              out.get("error", "token exchange failed")))
    return out
_SIMPLE_UPLOAD_LIMIT = 4 * 1024 * 1024
_CHUNK = 10 * 1024 * 1024  # upload-session chunk (multiple of 320 KiB)


def token_path() -> str:
    base = os.environ.get(
        "WONDERSHOT_DATA_DIR",
        os.path.join(os.path.expanduser("~/.local/share"), "wondershot"))
    return os.path.join(base, "graph_token.json")


def _post_form(url: str, fields: dict) -> dict:
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        return json.load(e)  # OAuth errors come back as JSON bodies


def request_device_code(client_id: str) -> dict:
    """Start the flow: returns user_code / verification_uri / interval."""
    out = _post_form(f"{AUTH_BASE}/devicecode",
                     {"client_id": client_id, "scope": SCOPE})
    if "device_code" not in out:
        raise OSError(out.get("error_description",
                              out.get("error", "device code request failed")))
    return out


def poll_token(client_id: str, device_code: str) -> dict | None:
    """One poll. Returns tokens when signed in, None while pending."""
    out = _post_form(f"{AUTH_BASE}/token", {
        "client_id": client_id,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        "device_code": device_code,
    })
    if "access_token" in out:
        return out
    if out.get("error") in ("authorization_pending", "slow_down"):
        return None
    raise OSError(out.get("error_description", out.get("error", "auth failed")))


def save_tokens(tokens: dict, client_id: str, account: str = "") -> None:
    path = token_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    payload = {
        "client_id": client_id,
        "account": account,
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token", ""),
        "expires_at": time.time() + int(tokens.get("expires_in", 3600)) - 60,
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(payload, f)


def load_tokens() -> dict | None:
    try:
        with open(token_path()) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def disconnect() -> None:
    try:
        os.unlink(token_path())
    except OSError:
        pass


def connected_account() -> str:
    """'' when not connected, else the account label saved at connect."""
    t = load_tokens()
    return t.get("account", "connected") if t else ""


def ensure_access_token() -> str:
    t = load_tokens()
    if t is None:
        raise OSError("OneDrive is not connected (Settings → Sharing)")
    if time.time() < t["expires_at"]:
        return t["access_token"]
    out = _post_form(f"{AUTH_BASE}/token", {
        "client_id": t["client_id"],
        "grant_type": "refresh_token",
        "refresh_token": t["refresh_token"],
        "scope": SCOPE,
    })
    if "access_token" not in out:
        raise OSError("OneDrive session expired — reconnect in Settings")
    save_tokens(out, t["client_id"], t.get("account", ""))
    return out["access_token"]


def _graph(method: str, url: str, token: str, data: bytes | None = None,
           content_type: str = "application/json",
           extra: dict | None = None) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    if data is not None:
        headers["Content-Type"] = content_type
    headers.update(extra or {})
    req = urllib.request.Request(url, data=data, method=method,
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = resp.read()
    return json.loads(body) if body else {}


def whoami(token: str) -> str:
    me = _graph("GET", f"{GRAPH}/me", token)
    return me.get("userPrincipalName") or me.get("displayName", "connected")


def _drive_base(drive_id: str) -> str:
    """'' = the signed-in account's own OneDrive (personal or business);
    a drive id targets a specific SharePoint document library."""
    return f"{GRAPH}/drives/{drive_id}" if drive_id else f"{GRAPH}/me/drive"


def sites_search(token: str, query: str) -> list[dict]:
    out = _graph("GET", f"{GRAPH}/sites?search={urllib.parse.quote(query)}",
                 token)
    return [{"id": s["id"], "name": s.get("displayName", s.get("name", "?")),
             "url": s.get("webUrl", "")} for s in out.get("value", [])]


def site_drives(token: str, site_id: str) -> list[dict]:
    out = _graph("GET", f"{GRAPH}/sites/{site_id}/drives", token)
    return [{"id": d["id"], "name": d.get("name", "Documents")}
            for d in out.get("value", [])]


def upload(path: str, token: str, drive_id: str = "") -> str:
    """Upload to /Wondershot/<name>; returns item id."""
    name = urllib.parse.quote(os.path.basename(path))
    base = f"{_drive_base(drive_id)}/root:/Wondershot/{name}:"
    size = os.path.getsize(path)
    if size <= _SIMPLE_UPLOAD_LIMIT:
        with open(path, "rb") as f:
            item = _graph("PUT", f"{base}/content", token, f.read(),
                          "application/octet-stream")
        return item["id"]
    session = _graph("POST", f"{base}/createUploadSession", token,
                     json.dumps({"item": {
                         "@microsoft.graph.conflictBehavior": "replace"
                     }}).encode())
    url = session["uploadUrl"]
    item: dict = {}
    with open(path, "rb") as f:
        offset = 0
        while offset < size:
            chunk = f.read(_CHUNK)
            end = offset + len(chunk) - 1
            req = urllib.request.Request(url, data=chunk, method="PUT",
                                         headers={
                "Content-Length": str(len(chunk)),
                "Content-Range": f"bytes {offset}-{end}/{size}",
            })
            with urllib.request.urlopen(req, timeout=300) as resp:
                body = resp.read()
                item = json.loads(body) if body else {}
            offset += len(chunk)
    return item["id"]


def create_link(item_id: str, token: str, drive_id: str = "") -> str:
    """View link; anonymous when the tenant allows it, else org-scoped."""
    for scope in ("anonymous", "organization"):
        try:
            out = _graph("POST",
                         f"{_drive_base(drive_id)}/items/{item_id}/createLink",
                         token, json.dumps({"type": "view",
                                            "scope": scope}).encode())
            return out["link"]["webUrl"]
        except urllib.error.HTTPError as e:
            if scope == "organization":
                raise OSError(f"createLink failed: HTTP {e.code}") from e
    raise OSError("createLink failed")  # unreachable


def share(path: str, drive_id: str = "") -> str:
    token = ensure_access_token()
    return create_link(upload(path, token, drive_id), token, drive_id)
