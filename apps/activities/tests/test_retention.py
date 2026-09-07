"""Erasure and the retention sweep — the paths that delete a photograph of a child.

Two properties matter more than anything else here and each has its own test:

1. **Nothing deletes without `commit=True`.** The default is a report. If that ever
   stops being true, the first sign of it will be data that is already gone.
2. **Erasing one child does not delete a photograph of three.** The multi-child rule
   governs deletion as much as it governs publication — a shared photo belongs to
   every family in it, and one family's request is not the others' answer.

`_forget_object` falls through to `default_storage` here, because R2 is unconfigured
in the test settings. That is the same path the dev machine takes, which is the point
of it existing.
"""

from datetime import date, timedelta

import pytest
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.utils import timezone

from apps.activities import selectors, services
from apps.activities.models import ActivityKind, MediaAsset, MediaTag, UploadState
from apps.people.models import Enrollment

pytestmark = pytest.mark.django_db


def _stored(branch, *, key, taken_at=None, bytes_on_disk=True):
    """A STORED asset with real bytes behind it, so a delete has something to remove."""
    if bytes_on_disk:
        default_storage.save(key, ContentFile(b"not-really-a-jpeg"))
    return MediaAsset.objects.create(
        branch=branch,
        key=key,
        upload_state=UploadState.STORED,
        taken_at=taken_at or timezone.now(),
    )


def _left(student, *, on):
    """Close every enrolment this child has, as of `on`.

    `joined_on` moves back with it — the fixture enrols today, and the model's
    `enrollment_ends_after_it_starts` constraint quite rightly refuses a child who
    left before they arrived.
    """
    Enrollment.objects.filter(student=student).update(
        joined_on=on - timedelta(days=180), left_on=on
    )


# --------------------------------------------------------------------------------
# The dry run is the default
# --------------------------------------------------------------------------------


def test_erasure_reports_and_changes_nothing_without_commit(branch, child_a, teacher):
    media = _stored(branch, key="photos/1/dry/a.jpg")
    services.tag(media=media, student=child_a, tagged_by=teacher)
    services.record_entry(kind=ActivityKind.NOTE, branch=branch, student=child_a, body="hello")

    result = services.erase_student_media(student=child_a)

    assert result["committed"] is False
    assert result["media_deleted"] == [media.pk]
    assert MediaAsset.objects.filter(pk=media.pk).exists()
    assert MediaTag.objects.filter(student=child_a).exists()
    assert default_storage.exists(media.key)


def test_the_retention_sweep_reports_and_changes_nothing_without_commit(branch, child_a, teacher):
    media = _stored(branch, key="photos/1/dry/b.jpg")
    services.tag(media=media, student=child_a, tagged_by=teacher)
    _left(child_a, on=date.today() - timedelta(days=400))

    result = services.prune_expired_media()

    assert result["committed"] is False
    assert media.pk in result["media_deleted"]
    assert MediaAsset.objects.filter(pk=media.pk).exists()
    assert default_storage.exists(media.key)


# --------------------------------------------------------------------------------
# Erasure
# --------------------------------------------------------------------------------


def test_erasure_removes_the_row_the_object_and_the_entries(branch, child_a, teacher):
    media = _stored(branch, key="photos/1/erase/a.jpg")
    services.tag(media=media, student=child_a, tagged_by=teacher)
    services.record_entry(kind=ActivityKind.NOTE, branch=branch, student=child_a, body="hello")

    result = services.erase_student_media(student=child_a, commit=True)

    assert result["committed"] is True
    assert not MediaAsset.objects.filter(pk=media.pk).exists()
    assert not default_storage.exists(media.key)
    assert result["entries_deleted"] == 1
    assert not child_a.activity_entries.exists()


def test_erasing_one_child_keeps_a_photo_that_shows_another(branch, child_a, child_b, teacher):
    """The rule that makes this path safe to run. A shared photograph is Bhavya's
    photograph too, and Aarav's family's request is not an answer on her behalf."""
    shared = _stored(branch, key="photos/1/erase/shared.jpg")
    services.tag(media=shared, student=child_a, tagged_by=teacher)
    services.tag(media=shared, student=child_b, tagged_by=teacher)

    result = services.erase_student_media(student=child_a, commit=True)

    assert result["media_kept"] == [shared.pk]
    assert result["media_deleted"] == []
    assert MediaAsset.objects.filter(pk=shared.pk).exists()
    assert default_storage.exists(shared.key)
    # ...but Aarav is no longer in it, which is what was actually asked for.
    assert not MediaTag.objects.filter(media=shared, student=child_a).exists()
    assert MediaTag.objects.filter(media=shared, student=child_b).exists()


def test_erasure_leaves_incident_reports_alone(branch, child_a, teacher):
    """A safety record naming a member of staff, which the school may be required to
    hold. Deleting it on request would let the record of an injury be removed by
    asking; the command says so where the operator reads it."""
    incident = services.report_incident(
        student=child_a,
        severity="minor",
        what_happened="Grazed knee",
        action_taken="Cleaned and plastered",
        staff_responsible=teacher,
    )

    services.erase_student_media(student=child_a, commit=True)

    incident.refresh_from_db()
    assert incident.pk is not None


def test_room_level_entries_survive_one_childs_erasure(branch, child_a, room, teacher):
    """ "Everyone napped" is not a record about this child."""
    services.record_for_classroom(kind=ActivityKind.NAP, classroom=room)

    result = services.erase_student_media(student=child_a, commit=True)

    assert result["entries_deleted"] == 0
    assert room.activity_entries.count() == 1


# --------------------------------------------------------------------------------
# The retention window
# --------------------------------------------------------------------------------


def test_a_child_still_on_the_roll_keeps_their_photographs(branch, child_a, teacher):
    media = _stored(
        branch, key="photos/1/keep/a.jpg", taken_at=timezone.now() - timedelta(days=900)
    )
    services.tag(media=media, student=child_a, tagged_by=teacher)

    assert selectors.departure_date(child_a) is None
    assert media.pk not in [m.pk for m in selectors.media_expired_by_retention(window_days=365)]


def test_a_photo_expires_only_once_every_tagged_child_has_gone(branch, child_a, child_b, teacher):
    """One child still enrolled keeps the whole photograph — the same "every tagged
    child" shape as the publish gate, pointing the other way."""
    shared = _stored(branch, key="photos/1/expire/shared.jpg")
    services.tag(media=shared, student=child_a, tagged_by=teacher)
    services.tag(media=shared, student=child_b, tagged_by=teacher)
    _left(child_a, on=date.today() - timedelta(days=400))

    expired = [m.pk for m in selectors.media_expired_by_retention(window_days=365)]
    assert shared.pk not in expired

    _left(child_b, on=date.today() - timedelta(days=400))
    expired = [m.pk for m in selectors.media_expired_by_retention(window_days=365)]
    assert shared.pk in expired


def test_a_child_gone_less_than_the_window_is_not_yet_expired(branch, child_a, teacher):
    media = _stored(branch, key="photos/1/expire/recent.jpg")
    services.tag(media=media, student=child_a, tagged_by=teacher)
    _left(child_a, on=date.today() - timedelta(days=100))

    assert media.pk not in [m.pk for m in selectors.media_expired_by_retention(window_days=365)]
    assert media.pk in [m.pk for m in selectors.media_expired_by_retention(window_days=90)]


def test_a_photograph_nobody_ever_tagged_expires_on_its_own_age(branch):
    """The worst kind to keep: a picture of children that no consent rule in this
    codebase can reason about, because nothing says who is in it."""
    old = _stored(
        branch, key="photos/1/untagged/old.jpg", taken_at=timezone.now() - timedelta(days=400)
    )
    fresh = _stored(branch, key="photos/1/untagged/new.jpg")

    expired = [m.pk for m in selectors.media_expired_by_retention(window_days=365)]
    assert old.pk in expired
    assert fresh.pk not in expired


def test_the_sweep_deletes_the_object_as_well_as_the_row(branch, child_a, teacher):
    """A delete that leaves the image in the bucket is not a delete."""
    media = _stored(branch, key="photos/1/sweep/a.jpg")
    services.tag(media=media, student=child_a, tagged_by=teacher)
    _left(child_a, on=date.today() - timedelta(days=400))

    result = services.prune_expired_media(commit=True)

    assert media.key in result["objects_removed"]
    assert not default_storage.exists(media.key)
    assert not MediaAsset.objects.filter(pk=media.pk).exists()


def test_the_thumbnail_goes_with_the_photograph(branch, child_a, teacher):
    media = _stored(branch, key="photos/1/thumb/a.jpg")
    default_storage.save("photos/1/thumb/a_thumb.jpg", ContentFile(b"thumb"))
    media.thumbnail_key = "photos/1/thumb/a_thumb.jpg"
    media.save(update_fields=["thumbnail_key"])

    result = services.forget_media(media=media, commit=True)

    assert set(result["objects_removed"]) == {media.key, "photos/1/thumb/a_thumb.jpg"}
    assert not default_storage.exists("photos/1/thumb/a_thumb.jpg")


def test_a_missing_object_is_not_an_error(branch):
    """A row whose object was already gone still gets its row removed. Half a delete
    is the state this whole module exists to leave nobody in."""
    media = _stored(branch, key="photos/1/gone/a.jpg", bytes_on_disk=False)

    result = services.forget_media(media=media, commit=True)

    assert result["objects_removed"] == []
    assert not MediaAsset.objects.filter(pk=media.pk).exists()
