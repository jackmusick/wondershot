"""Upload-and-share: S3-compatible and Azure Blob, stdlib only.

Share links are presigned GET URLs (S3, SigV4 query auth) or read-only
SAS URIs (Azure). Uploads use a presigned PUT (S3) / write SAS (Azure),
so no SDK and no header signing is needed — everything is HMAC over
urllib. Credentials live in QSettings (plaintext; the settings dialog
says so).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import mimetypes
import os
from datetime import datetime, timedelta, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen

from PySide6.QtCore import QObject, QRunnable, Signal

S3_MAX_EXPIRY = 604800  # 7 days — SigV4's hard cap

AZURE_SAS_VERSION = "2021-08-06"


# -- S3 (SigV4 query-string auth) -------------------------------------------


def _sigv4_key(secret: str, date: str, region: str) -> bytes:
    k = hmac.new(f"AWS4{secret}".encode(), date.encode(), hashlib.sha256)
    k = hmac.new(k.digest(), region.encode(), hashlib.sha256)
    k = hmac.new(k.digest(), b"s3", hashlib.sha256)
    return hmac.new(k.digest(), b"aws4_request", hashlib.sha256).digest()


def presign_s3_url(url: str, region: str, access_key: str, secret_key: str,
                   method: str = "GET", expires: int = S3_MAX_EXPIRY,
                   now: datetime | None = None) -> str:
    """Presign an absolute S3 object URL (SigV4 query parameters)."""
    if now is None:
        now = datetime.now(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    scope = f"{datestamp}/{region}/s3/aws4_request"

    scheme, rest = url.split("://", 1)
    host, _, path = rest.partition("/")
    path = "/" + path

    params = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": f"{access_key}/{scope}",
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(expires),
        "X-Amz-SignedHeaders": "host",
    }
    canonical_query = "&".join(
        f"{quote(k, safe='')}={quote(v, safe='')}"
        for k, v in sorted(params.items()))
    canonical_request = "\n".join([
        method, quote(path, safe="/"), canonical_query,
        f"host:{host}", "", "host", "UNSIGNED-PAYLOAD"])
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256", amz_date, scope,
        hashlib.sha256(canonical_request.encode()).hexdigest()])
    signature = hmac.new(_sigv4_key(secret_key, datestamp, region),
                         string_to_sign.encode(), hashlib.sha256).hexdigest()
    return f"{url}?{canonical_query}&X-Amz-Signature={signature}"


def s3_object_url(endpoint: str, bucket: str, key: str) -> str:
    """Path-style URL — works on AWS and every S3-compatible store."""
    return f"{endpoint.rstrip('/')}/{bucket}/{quote(key)}"


# -- Azure Blob (account-key SAS) --------------------------------------------


def azure_sas_url(account: str, container: str, blob: str, account_key: str,
                  permissions: str = "r", expires_days: int = 7,
                  now: datetime | None = None) -> str:
    """Blob URL with a service SAS signed by the account key."""
    if now is None:
        now = datetime.now(timezone.utc)
    expiry = (now + timedelta(days=expires_days)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")
    resource = f"/blob/{account}/{container}/{blob}"
    string_to_sign = "\n".join([
        permissions, "", expiry, resource,
        "",            # signed identifier
        "",            # IP range
        "https",       # protocol
        AZURE_SAS_VERSION,
        "b",           # resource type: blob
        "",            # snapshot time
        "",            # encryption scope
        "", "", "", "", "",  # rscc, rscd, rsce, rscl, rsct
    ])
    sig = base64.b64encode(
        hmac.new(base64.b64decode(account_key), string_to_sign.encode(),
                 hashlib.sha256).digest()).decode()
    qs = "&".join([
        f"sv={AZURE_SAS_VERSION}", "spr=https",
        f"se={quote(expiry, safe='')}", "sr=b", f"sp={permissions}",
        f"sig={quote(sig, safe='')}"])
    return (f"https://{account}.blob.core.windows.net/"
            f"{container}/{quote(blob)}?{qs}")


# -- upload + share orchestration --------------------------------------------


def s3_configured(settings) -> bool:
    return all(getattr(settings, k, "") for k in
               ("s3_endpoint", "s3_bucket", "s3_access_key", "s3_secret_key"))


def azure_configured(settings) -> bool:
    return all(getattr(settings, k, "") for k in
               ("azure_account", "azure_container", "azure_key"))


def configured_providers(settings) -> list[str]:
    out = []
    if s3_configured(settings):
        out.append("s3")
    if azure_configured(settings):
        out.append("azure")
    return out


def _put(url: str, path: str, headers: dict) -> None:
    with open(path, "rb") as f:
        data = f.read()
    req = Request(url, data=data, method="PUT", headers={
        "Content-Type": (mimetypes.guess_type(path)[0]
                         or "application/octet-stream"),
        "Content-Length": str(len(data)),
        **headers,
    })
    with urlopen(req, timeout=120) as resp:
        if resp.status not in (200, 201):
            raise OSError(f"upload failed: HTTP {resp.status}")


def share_file(settings, path: str, provider: str) -> str:
    """Upload `path` and return a time-limited share URL."""
    name = os.path.basename(path)
    key = f"grabbit/{name}"
    days = max(1, min(7, int(settings.share_expiry_days)))
    if provider == "s3":
        url = s3_object_url(settings.s3_endpoint, settings.s3_bucket, key)
        creds = (settings.s3_region or "us-east-1",
                 settings.s3_access_key, settings.s3_secret_key)
        _put(presign_s3_url(url, *creds, method="PUT", expires=3600),
             path, {})
        return presign_s3_url(url, *creds, expires=days * 86400)
    if provider == "azure":
        upload = azure_sas_url(settings.azure_account,
                               settings.azure_container, key,
                               settings.azure_key, permissions="cw",
                               expires_days=1)
        _put(upload, path, {"x-ms-blob-type": "BlockBlob"})
        return azure_sas_url(settings.azure_account,
                             settings.azure_container, key,
                             settings.azure_key, expires_days=days)
    raise ValueError(f"unknown share provider: {provider}")


class _ShareSignal(QObject):
    done = Signal(str, str)  # (url, error) — exactly one is non-empty


class ShareJob(QRunnable):
    """Background upload; emitter.done fires on the GUI thread."""

    def __init__(self, settings, path: str, provider: str):
        super().__init__()
        self.settings = settings
        self.path = path
        self.provider = provider
        self.emitter = _ShareSignal()

    def run(self) -> None:
        try:
            url = share_file(self.settings, self.path, self.provider)
            self.emitter.done.emit(url, "")
        except Exception as e:  # noqa: BLE001 — surface anything to the UI
            self.emitter.done.emit("", str(e))
