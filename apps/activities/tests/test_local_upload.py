"""Uploading a photograph on a stack with no R2 bucket.

The presigned-PUT design in plan.md assumes Cloudflare. A school that has not bought
a bucket yet still has to be able to use the product, so `upload_url` hands the
browser a Django endpoint instead — same shape, one key, one method, so
`photo-upload.js` needs no branch of its own.

The tests that matter here are the refusals, not the happy path:

- it is chosen by CONFIGURATION, never by the caller. With R2 present this route is
  404, or it would be a slower worker-occupying second way into the same bucket.
- a teacher at another branch gets 404, so nobody can write bytes into a row they
  were never shown.
- a completed upload cannot be overwritten, or a replayed PUT would replace a
  photograph that has already been tagged and published.
"""

import io

import pytest
from django.core.files.storage import default_storage
from django.urls import reverse
from PIL import Image

from apps.activities import services
from apps.activities.models import MediaAsset, UploadState

pytestmark = pytest.mark.django_db


def _jpeg(size=(400, 300)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (120, 140, 90)).save(buffer, format="JPEG")
    return buffer.getvalue()


@pytest.fixture
def signed_in_teacher(client, teacher):
    client.force_login(teacher)
    return teacher


# --------------------------------------------------------------------------------
# Handing out the destination
# --------------------------------------------------------------------------------


def test_upload_url_points_at_django_when_there_is_no_bucket(client, signed_in_teacher, room):
    """It used to answer 503 here — correct once, but it left the feature unusable on
    every stack without R2, which is every stack today."""
    response = client.post(
        reverse("activities_upload_url", args=[room.pk]),
        {"filename": "IMG_1.jpg", "content_type": "image/jpeg"},
    )

    assert response.status_code == 200
    body = response.json()
    media = MediaAsset.objects.get(pk=body["media_id"])
    assert body["url"] == reverse("activities_upload_direct", args=[media.pk])
    assert media.upload_state == UploadState.PENDING


def test_a_bad_content_type_is_still_refused(client, signed_in_teacher, room):
    """The allow-list guarded the presigned URL; it has to guard this path too."""
    response = client.post(
        reverse("activities_upload_url", args=[room.pk]),
        {"filename": "notes.pdf", "content_type": "application/pdf"},
    )

    assert response.status_code == 400
    assert not MediaAsset.objects.exists()


# --------------------------------------------------------------------------------
# Receiving the bytes
# --------------------------------------------------------------------------------


def test_the_bytes_land_and_the_photo_can_be_confirmed(client, signed_in_teacher, room):
    """The whole round trip the teacher's browser makes: ask, put, confirm."""
    grant = client.post(
        reverse("activities_upload_url", args=[room.pk]),
        {"filename": "IMG_2.jpg", "content_type": "image/jpeg"},
    ).json()
    payload = _jpeg()

    put = client.put(grant["url"], data=payload, content_type="image/jpeg")

    assert put.status_code == 200
    media = MediaAsset.objects.get(pk=grant["media_id"])
    assert default_storage.exists(media.key)
    with default_storage.open(media.key, "rb") as handle:
        assert handle.read() == payload

    confirmed = client.post(grant["confirm"], {"byte_size": len(payload)})
    assert confirmed.status_code == 200
    media.refresh_from_db()
    assert media.upload_state == UploadState.STORED


def test_an_empty_upload_is_refused(client, signed_in_teacher, room):
    grant = client.post(
        reverse("activities_upload_url", args=[room.pk]),
        {"filename": "IMG_3.jpg", "content_type": "image/jpeg"},
    ).json()

    put = client.put(grant["url"], data=b"", content_type="image/jpeg")

    assert put.status_code == 400
    assert MediaAsset.objects.get(pk=grant["media_id"]).upload_state == UploadState.PENDING


def test_an_oversized_upload_is_refused_and_leaves_the_row_pending(
    client, signed_in_teacher, room, monkeypatch
):
    """PENDING rather than FAILED on purpose: the nightly reconciliation already knows
    how to settle a pending row against storage, and it is the one place that decides
    an upload is dead."""
    monkeypatch.setattr(services, "MAX_LOCAL_UPLOAD_BYTES", 64)
    grant = client.post(
        reverse("activities_upload_url", args=[room.pk]),
        {"filename": "IMG_4.jpg", "content_type": "image/jpeg"},
    ).json()

    put = client.put(grant["url"], data=_jpeg(), content_type="image/jpeg")

    assert put.status_code == 400
    media = MediaAsset.objects.get(pk=grant["media_id"])
    assert media.upload_state == UploadState.PENDING
    assert not default_storage.exists(media.key)


def test_a_completed_upload_cannot_be_overwritten(client, signed_in_teacher, room):
    """A replayed PUT must not replace a photograph teachers have already tagged."""
    grant = client.post(
        reverse("activities_upload_url", args=[room.pk]),
        {"filename": "IMG_5.jpg", "content_type": "image/jpeg"},
    ).json()
    client.put(grant["url"], data=_jpeg(), content_type="image/jpeg")
    client.post(grant["confirm"], {"byte_size": 10})

    replay = client.put(grant["url"], data=_jpeg(size=(10, 10)), content_type="image/jpeg")

    assert replay.status_code == 400


# --------------------------------------------------------------------------------
# The refusals
# --------------------------------------------------------------------------------


def test_the_local_route_is_closed_when_r2_is_configured(
    client, signed_in_teacher, room, monkeypatch
):
    """Otherwise this is a second, slower, worker-occupying way into the same bucket,
    reachable by anyone holding an old URL — and the presigned design becomes advice."""
    grant = client.post(
        reverse("activities_upload_url", args=[room.pk]),
        {"filename": "IMG_6.jpg", "content_type": "image/jpeg"},
    ).json()

    monkeypatch.setattr("integrations.storage_r2.is_configured", lambda: True)
    put = client.put(grant["url"], data=_jpeg(), content_type="image/jpeg")

    assert put.status_code == 404


def test_a_teacher_at_another_branch_cannot_write_into_the_row(client, org, room, branch):
    """404, not 403. Writing bytes into someone else's row is the same disclosure as
    reading it, and the answer must not confirm the id exists."""
    from apps.core.models import Role, User
    from apps.core.services import create_branch, grant_membership

    media = services.register_upload(branch=branch, key="photos/1/x/a.jpg")

    elsewhere = create_branch(organization=org, name="Second", slug="second")
    outsider = User.objects.create_user(phone="9100000099", full_name="Other Teacher")
    grant_membership(user=outsider, branch=elsewhere, role=Role.TEACHER)
    client.force_login(outsider)

    put = client.put(
        reverse("activities_upload_direct", args=[media.pk]),
        data=_jpeg(),
        content_type="image/jpeg",
    )

    assert put.status_code == 404
    assert not default_storage.exists(media.key)


def test_a_parent_cannot_upload(client, parent_a, branch):
    media = services.register_upload(branch=branch, key="photos/1/x/b.jpg")
    client.force_login(parent_a)

    put = client.put(
        reverse("activities_upload_direct", args=[media.pk]),
        data=_jpeg(),
        content_type="image/jpeg",
    )

    assert put.status_code in (302, 403, 404)
    assert not default_storage.exists(media.key)


def test_anonymous_cannot_upload(client, branch):
    media = services.register_upload(branch=branch, key="photos/1/x/c.jpg")

    put = client.put(
        reverse("activities_upload_direct", args=[media.pk]),
        data=_jpeg(),
        content_type="image/jpeg",
    )

    assert put.status_code in (302, 403, 404)
    assert not default_storage.exists(media.key)


# --------------------------------------------------------------------------------
# Seeing what you just uploaded
# --------------------------------------------------------------------------------


def test_a_teacher_can_view_a_photo_they_have_not_tagged_yet(client, signed_in_teacher, room):
    """The bug the local fallback exposed.

    `media_for_user` scopes through the tags, so an untagged photograph belongs to no
    student and was visible to nobody — including the teacher who had just uploaded it
    and was opening it in order to tag it. Invisible while nothing could reach local
    storage; a broken image on the tagging screen the moment uploads landed there.
    """
    grant = client.post(
        reverse("activities_upload_url", args=[room.pk]),
        {"filename": "IMG_7.jpg", "content_type": "image/jpeg"},
    ).json()
    client.put(grant["url"], data=_jpeg(), content_type="image/jpeg")
    client.post(grant["confirm"], {"byte_size": 10})

    media = MediaAsset.objects.get(pk=grant["media_id"])
    assert media.tags.count() == 0, "the point of the test is that it is untagged"

    response = client.get(reverse("media_file", args=[media.pk]))

    assert response.status_code == 200


def test_the_tagging_screen_and_its_image_agree_on_who_may_look(
    client, signed_in_teacher, room, org
):
    """The page is scoped by `media_for_staff` and the image by `media_file`. If the
    two disagree, one of them is wrong — here, that a teacher elsewhere gets the same
    404 from both rather than a page they can open and an image they cannot."""
    from apps.core.models import Role, User
    from apps.core.services import create_branch, grant_membership

    grant = client.post(
        reverse("activities_upload_url", args=[room.pk]),
        {"filename": "IMG_8.jpg", "content_type": "image/jpeg"},
    ).json()
    client.put(grant["url"], data=_jpeg(), content_type="image/jpeg")
    client.post(grant["confirm"], {"byte_size": 10})
    media_id = grant["media_id"]

    assert client.get(reverse("activities_tag", args=[media_id])).status_code == 200
    assert client.get(reverse("media_file", args=[media_id])).status_code == 200

    elsewhere = create_branch(organization=org, name="Third", slug="third")
    outsider = User.objects.create_user(phone="9100000098", full_name="Far Teacher")
    grant_membership(user=outsider, branch=elsewhere, role=Role.TEACHER)
    client.force_login(outsider)

    assert client.get(reverse("activities_tag", args=[media_id])).status_code == 404
    assert client.get(reverse("media_file", args=[media_id])).status_code == 404
