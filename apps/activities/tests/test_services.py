"""The write side: entries, the bulk path, incidents, and upload state.

No HttpRequest is constructed anywhere in this file. If one is ever needed to test a
service, the logic has leaked upward into the view layer.
"""

import pytest
from django.core.exceptions import ValidationError

from apps.activities import selectors, services
from apps.activities.models import ActivityEntry, ActivityKind, IncidentSeverity, UploadState

pytestmark = pytest.mark.django_db


# --------------------------------------------------------------------------------
# Entries
# --------------------------------------------------------------------------------


def test_an_entry_targets_exactly_one_of_a_student_or_a_room(branch, teacher, child_a, room):
    with pytest.raises(ValidationError):
        services.record_entry(kind=ActivityKind.MEAL, branch=branch)
    with pytest.raises(ValidationError):
        services.record_entry(
            kind=ActivityKind.MEAL, branch=branch, student=child_a, classroom=room
        )


def test_entries_are_drafts_until_published(branch, teacher, child_a):
    """Teachers stage the day and publish once — a parent should get the day, not a
    trickle of six notifications between 9am and 4pm."""
    entry = services.record_entry(
        kind=ActivityKind.NOTE, branch=branch, student=child_a, body="Settled well"
    )

    assert entry.is_published is False
    assert entry.published_at is None


def test_the_bulk_path_writes_one_row_for_the_whole_room(branch, teacher, room, child_a, child_b):
    """One row, not thirty. Thirty is what makes a teacher stop using the feature."""
    services.record_for_classroom(classroom=room, kind=ActivityKind.NAP, author=teacher)

    assert ActivityEntry.objects.count() == 1
    assert ActivityEntry.objects.get().classroom == room


def test_a_room_entry_reaches_every_child_in_that_room(
    branch, teacher, room, child_a, child_b, parent_a, parent_b
):
    entry = services.record_for_classroom(classroom=room, kind=ActivityKind.NAP, author=teacher)
    services.publish_entries(entries=[entry])

    assert list(selectors.entries_for_child_of(parent_a, child_a.pk)[1]) == [entry]
    assert list(selectors.entries_for_child_of(parent_b, child_b.pk)[1]) == [entry]


def test_publishing_twice_does_not_restamp(branch, teacher, child_a):
    """A double tap must not reset published_at and reorder a parent's feed."""
    entry = services.record_entry(kind=ActivityKind.MEAL, branch=branch, student=child_a)
    assert services.publish_entries(entries=[entry]) == 1
    entry.refresh_from_db()
    first = entry.published_at

    assert services.publish_entries(entries=[entry]) == 0
    entry.refresh_from_db()
    assert entry.published_at == first


def test_a_draft_entry_is_invisible_to_the_parent(branch, teacher, child_a, parent_a):
    services.record_entry(kind=ActivityKind.MEAL, branch=branch, student=child_a, body="Draft")

    assert list(selectors.entries_for_child_of(parent_a, child_a.pk)[1]) == []


# --------------------------------------------------------------------------------
# Incidents
# --------------------------------------------------------------------------------


def test_an_incident_is_visible_immediately_with_no_draft_state(branch, teacher, child_a, parent_a):
    """An incident a teacher is still deciding whether to mention is the exact case
    this record exists to prevent."""
    incident = services.report_incident(
        student=child_a,
        severity=IncidentSeverity.MODERATE,
        what_happened="Fell from the low climbing frame",
        action_taken="Ice pack, monitored for an hour",
        staff_responsible=teacher,
    )

    assert list(selectors.incidents_for_child_of(parent_a, child_a.pk)[1]) == [incident]
    assert incident.is_acknowledged is False


def test_acknowledgement_records_who_and_when(branch, teacher, child_a, parent_a):
    incident = services.report_incident(
        student=child_a,
        severity=IncidentSeverity.MINOR,
        what_happened="Grazed a knee",
        action_taken="Cleaned and plastered",
        staff_responsible=teacher,
    )

    services.acknowledge_incident(incident=incident, guardian=parent_a)

    incident.refresh_from_db()
    assert incident.acknowledged_by == parent_a
    assert incident.acknowledged_at is not None
    assert incident.is_acknowledged is True


def test_the_first_acknowledgement_stands(branch, teacher, child_a, parent_a, parent_b):
    """ "When did the family find out" has one answer and it is the earliest one."""
    incident = services.report_incident(
        student=child_a,
        severity=IncidentSeverity.MINOR,
        what_happened="Grazed a knee",
        action_taken="Cleaned and plastered",
        staff_responsible=teacher,
    )
    services.acknowledge_incident(incident=incident, guardian=parent_a)
    incident.refresh_from_db()
    first_at, first_by = incident.acknowledged_at, incident.acknowledged_by

    services.acknowledge_incident(incident=incident, guardian=parent_b)

    incident.refresh_from_db()
    assert incident.acknowledged_at == first_at
    assert incident.acknowledged_by == first_by


def test_unacknowledged_incidents_are_oldest_first(branch, teacher, child_a, child_b):
    """The list a branch admin chases. The oldest is the one that matters."""
    from datetime import timedelta

    from django.utils import timezone

    older = services.report_incident(
        student=child_a,
        severity=IncidentSeverity.MINOR,
        what_happened="A",
        action_taken="A",
        staff_responsible=teacher,
        occurred_at=timezone.now() - timedelta(days=3),
    )
    newer = services.report_incident(
        student=child_b,
        severity=IncidentSeverity.MINOR,
        what_happened="B",
        action_taken="B",
        staff_responsible=teacher,
    )

    assert list(selectors.unacknowledged_incidents(teacher)) == [older, newer]


# --------------------------------------------------------------------------------
# Uploads
# --------------------------------------------------------------------------------


def test_a_row_exists_before_the_browser_starts_uploading(branch, teacher):
    """The row comes first so an object that lands but is never confirmed still has
    something pointing at it."""
    media = services.register_upload(branch=branch, key="photos/x.webp", uploaded_by=teacher)

    assert media.upload_state == UploadState.PENDING
    assert list(selectors.awaiting_upload()) == [media]


def test_confirming_promotes_pending_to_stored(branch, teacher):
    media = services.register_upload(branch=branch, key="photos/x.webp")

    services.confirm_upload(media=media, byte_size=2048, width=1600, height=1200)

    media.refresh_from_db()
    assert media.upload_state == UploadState.STORED
    assert (media.byte_size, media.width, media.height) == (2048, 1600, 1200)
    assert list(selectors.awaiting_upload()) == []


def test_tagging_the_same_child_twice_is_one_tag(branch, teacher, child_a):
    """Tapping a child twice is a slip, not an instruction to create a second tag."""
    media = services.register_upload(branch=branch, key="photos/x.webp")

    services.tag(media=media, student=child_a, tagged_by=teacher)
    services.tag(media=media, student=child_a, tagged_by=teacher)

    assert media.tags.count() == 1


def test_untagging_removes_the_child(branch, teacher, child_a):
    media = services.register_upload(branch=branch, key="photos/x.webp")
    services.tag(media=media, student=child_a, tagged_by=teacher)

    services.untag(media=media, student=child_a)

    assert media.tags.count() == 0


def test_publishable_among_splits_a_day_without_writing(
    branch, teacher, child_a, child_b, parent_a, consent_for
):
    """What the publish screen shows before the teacher commits."""
    from apps.core.models import ConsentPurpose

    ready_photo = services.register_upload(branch=branch, key="photos/ready.webp")
    services.confirm_upload(media=ready_photo)
    services.tag(media=ready_photo, student=child_a, tagged_by=teacher)

    blocked_photo = services.register_upload(branch=branch, key="photos/blocked.webp")
    services.confirm_upload(media=blocked_photo)
    services.tag(media=blocked_photo, student=child_b, tagged_by=teacher)

    consent_for(parent_a, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS)

    ready, blocked = services.publishable_among([ready_photo, blocked_photo])

    assert ready == [ready_photo]
    assert blocked == [blocked_photo]
    # Nothing was written.
    ready_photo.refresh_from_db()
    assert ready_photo.is_published is False


# --------------------------------------------------------------------------------
# Feed ordering
# --------------------------------------------------------------------------------


def test_the_feed_orders_by_taken_at_not_upload_time(
    branch, teacher, child_a, parent_a, consent_for
):
    """Teachers upload the morning's photos in the evening. A feed ordered by upload
    time shows a parent their child's day backwards."""
    from datetime import timedelta

    from django.utils import timezone

    from apps.core.models import ConsentPurpose

    now = timezone.now()
    consent_for(parent_a, ConsentPurpose.PHOTOS_IN_APP)
    consent_for(parent_a, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS)

    # Created in the wrong order on purpose: morning is registered second.
    afternoon = services.register_upload(
        branch=branch, key="photos/pm.webp", taken_at=now - timedelta(hours=1)
    )
    morning = services.register_upload(
        branch=branch, key="photos/am.webp", taken_at=now - timedelta(hours=6)
    )
    for media in (afternoon, morning):
        services.confirm_upload(media=media)
        services.tag(media=media, student=child_a, tagged_by=teacher)
        services.publish_media(media=media)

    _, feed = selectors.feed_for_child_of(parent_a, child_a.pk)

    assert list(feed) == [afternoon, morning]
