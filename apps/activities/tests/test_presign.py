"""The presigned-URL helpers.

R2 is unconfigured on the development machine, which is the intended state rather
than a gap — `docs/plan.md` puts children's photographs in a private bucket, and a
bucket that is not there is safer than one wired up by accident. So these tests prove
two things without credentials:

1. Absent configuration, every helper raises `NotConfigured` rather than returning
   something falsy that a caller might render into a page as a broken image.
2. With a stub client, each helper asks for the operation, key and expiry it claims
   to — a `get_object` presign that quietly asked for `put_object` would hand every
   parent a write URL.

The round trip against real R2 is still unverified. That is the first thing to check
when the bucket exists, per the phase's own ordering.
"""

import pytest
from django.test import override_settings

from integrations import storage_r2


@override_settings(R2_ACCESS_KEY_ID="", R2_BUCKET="")
def test_every_helper_refuses_loudly_when_r2_is_absent():
    """A backup that silently no-ops is worse than one that fails; a presign that
    silently returns nothing is worse still, because it reaches a parent's browser."""
    assert storage_r2.is_configured() is False

    for call in (
        lambda: storage_r2.presign_put(key="photos/x.webp"),
        lambda: storage_r2.presign_get(key="photos/x.webp"),
        lambda: storage_r2.exists(key="photos/x.webp"),
    ):
        with pytest.raises(storage_r2.NotConfigured):
            call()


class _StubClient:
    """Records what boto3 was asked for, so the assertions are about our call rather
    than about botocore's signing."""

    def __init__(self):
        self.calls = []

    def generate_presigned_url(self, operation, Params, ExpiresIn):  # noqa: N803
        self.calls.append((operation, Params, ExpiresIn))
        return f"https://r2.example/{operation}"


@pytest.fixture
def stub(monkeypatch):
    client = _StubClient()
    monkeypatch.setattr(storage_r2, "_client", lambda: client)
    return client


@override_settings(R2_BUCKET="aaroham-private")
def test_presign_put_is_scoped_to_one_key_and_one_method(stub):
    storage_r2.presign_put(key="photos/2026/06/a.webp", content_type="image/webp")

    operation, params, expires = stub.calls[0]
    assert operation == "put_object"
    assert params["Bucket"] == "aaroham-private"
    assert params["Key"] == "photos/2026/06/a.webp"
    assert params["ContentType"] == "image/webp"
    # Longer than an upload on a bad connection, shorter than a URL stays useful.
    assert expires == 900


@override_settings(R2_BUCKET="aaroham-private")
def test_presign_put_omits_content_type_when_none_was_given(stub):
    """Signing a ContentType the browser then does not send makes R2 reject the PUT."""
    storage_r2.presign_put(key="photos/a.webp")

    _, params, _ = stub.calls[0]
    assert "ContentType" not in params


@override_settings(R2_BUCKET="aaroham-private")
def test_presign_get_is_read_only_and_short_lived(stub):
    storage_r2.presign_get(key="photos/a.webp")

    operation, params, expires = stub.calls[0]
    assert operation == "get_object"
    assert params == {"Bucket": "aaroham-private", "Key": "photos/a.webp"}
    # Long enough to render a feed, short enough that a forwarded link is already
    # dead. Lengthening this moves the authorisation somewhere nobody can revoke.
    assert expires == 300


@override_settings(R2_BUCKET="aaroham-private")
def test_exists_reports_false_only_for_a_genuine_404(monkeypatch):
    """The reconciliation deletes rows on the strength of this answer, so an outage
    must not be reported as "the object is missing"."""
    from botocore.exceptions import ClientError

    def head(code):
        def _head(**_):
            raise ClientError({"Error": {"Code": code}}, "HeadObject")

        return _head

    class _Client:
        def __init__(self, behaviour):
            self.head_object = behaviour

    monkeypatch.setattr(storage_r2, "_client", lambda: _Client(head("404")))
    assert storage_r2.exists(key="photos/gone.webp") is False

    monkeypatch.setattr(storage_r2, "_client", lambda: _Client(head("500")))
    with pytest.raises(ClientError):
        storage_r2.exists(key="photos/a.webp")

    monkeypatch.setattr(storage_r2, "_client", lambda: _Client(lambda **_: {"ContentLength": 1}))
    assert storage_r2.exists(key="photos/there.webp") is True
