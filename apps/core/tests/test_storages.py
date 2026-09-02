"""The storage aliases, and why there are two of them.

`default` is the private store — children's photos, pickup photos, student
documents. In production it is an R2 bucket served by short-lived presigned URLs
after a consent check. `public_media` is the marketing site's photographs:
world-readable, cached, indexable.

Keeping them apart is a compliance boundary, not a convenience. These tests exist
because the failure mode of dropping the alias from one settings file is unusually
nasty: a model field declaring `storage=public_media` resolves the alias at import
time, so the suite stops COLLECTING rather than failing a test, and every error
points somewhere unhelpful.
"""

from django.core.files.storage import storages


def test_both_media_aliases_are_configured():
    assert storages["default"] is not None
    assert storages["public_media"] is not None


def test_the_two_stores_are_not_the_same_object():
    """If these ever collapse into one, a marketing image and a child's photo end
    up in the same bucket with the same visibility — which is the whole thing this
    split exists to prevent."""
    assert storages["default"] is not storages["public_media"]
