from datetime import datetime, timezone

from grabbit.share import (
    azure_sas_url,
    configured_providers,
    presign_s3_url,
    s3_object_url,
)


def test_presign_matches_aws_sigv4_test_vector():
    """Official example from 'Authenticating Requests: Using Query
    Parameters (AWS Signature Version 4)' in the S3 API docs."""
    url = presign_s3_url(
        "https://examplebucket.s3.amazonaws.com/test.txt",
        region="us-east-1",
        access_key="AKIAIOSFODNN7EXAMPLE",
        secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        expires=86400,
        now=datetime(2013, 5, 24, tzinfo=timezone.utc),
    )
    assert url.endswith(
        "X-Amz-Signature=aeeed9bbccd4d02ee5c0109b86d86835f"
        "995330da4c265957d157751f604d404")
    assert "X-Amz-Credential=AKIAIOSFODNN7EXAMPLE%2F20130524%2F" \
           "us-east-1%2Fs3%2Faws4_request" in url
    assert "X-Amz-Expires=86400" in url


def test_s3_object_url_path_style():
    assert (s3_object_url("https://minio.local:9000/", "shots", "a b.png")
            == "https://minio.local:9000/shots/a%20b.png")


def test_azure_sas_url_shape():
    url = azure_sas_url(
        "myaccount", "shots", "grabbit/x.png",
        account_key="0123456789abcdef0123456789abcdef",  # base64-decodable
        now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert url.startswith(
        "https://myaccount.blob.core.windows.net/shots/grabbit/x.png?")
    for param in ("sv=", "se=2026-01-08", "sr=b", "sp=r", "sig="):
        assert param in url
    # deterministic given fixed inputs
    again = azure_sas_url(
        "myaccount", "shots", "grabbit/x.png",
        account_key="0123456789abcdef0123456789abcdef",
        now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    assert url == again


class _S(dict):
    def __getattr__(self, k):
        return self.get(k, "")


def test_configured_providers():
    assert configured_providers(_S()) == []
    s3 = _S(s3_endpoint="https://x", s3_bucket="b",
            s3_access_key="a", s3_secret_key="s")
    assert configured_providers(s3) == ["s3"]
    both = _S(**s3, azure_account="acc", azure_container="c", azure_key="k")
    assert configured_providers(both) == ["s3", "azure"]
