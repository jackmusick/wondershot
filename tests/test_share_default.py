import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest


@pytest.fixture(autouse=True)
def _no_onedrive(monkeypatch):
    # onedrive_configured() (share.py line 125) ignores `settings` and reads
    # the REAL user's Graph token via msgraph.connected_account() — on a
    # machine with OneDrive connected these tests would otherwise see a
    # phantom configured provider. Force it off; tests stay hermetic.
    monkeypatch.setattr("wondershot.share.onedrive_configured",
                        lambda s: False)


class _S:
    """Just enough settings for share-config checks."""
    def __init__(self, **kw):
        defaults = dict(share_provider="",
                        s3_endpoint="", s3_bucket="",
                        s3_access_key="", s3_secret_key="",
                        azure_account="", azure_container="", azure_key="")
        defaults.update(kw)
        self.__dict__.update(defaults)
        self.graph_client_id = "x"

    @property
    def _qsettings_stub(self):  # never used; here so nothing touches disk
        raise AssertionError


def _s3(**kw):
    return _S(s3_endpoint="https://s3.example", s3_bucket="b",
              s3_access_key="k", s3_secret_key="s", **kw)


def test_no_providers_gives_empty():
    from wondershot.share import default_provider
    assert default_provider(_S()) == ""


def test_single_provider_wins_even_if_default_unset():
    from wondershot.share import default_provider
    assert default_provider(_s3()) == "s3"


def test_configured_default_respected():
    from wondershot.share import default_provider
    s = _s3(azure_account="a", azure_container="c",
            azure_key="aGV5",  # base64-ish
            share_provider="azure")
    assert default_provider(s) == "azure"


def test_stale_default_falls_back_to_first_configured():
    from wondershot.share import default_provider
    s = _s3(share_provider="azure")  # azure not configured
    assert default_provider(s) == "s3"
