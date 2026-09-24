"""The writes. No HttpRequest is constructed anywhere in this file — if one were
needed, the logic would have leaked up into the view layer."""

import pytest
from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError
from django.utils import timezone

from apps.announcements import services
from apps.announcements.models import Announcement, AnnouncementRead

pytestmark = pytest.mark.django_db


def test_a_new_notice_is_a_draft(branch):
    notice = services.create_announcement(
        branch=branch, title="Sports day", body="Saturday.", is_school_wide=True
    )
    assert notice.is_published is False
    assert notice.published_at is None


def test_school_wide_and_a_room_is_refused(branch, room):
    with pytest.raises(ValidationError):
        services.create_announcement(
            branch=branch,
            title="Both",
            body="No.",
            classroom=room,
            is_school_wide=True,
        )


def test_neither_school_wide_nor_a_room_is_refused(branch):
    with pytest.raises(ValidationError):
        services.create_announcement(branch=branch, title="Nobody", body="No.")


def test_a_room_from_another_branch_is_refused(branch, other_branch):
    from apps.core.models import Classroom

    elsewhere = Classroom.objects.create(branch=other_branch, name="Theirs", capacity=10)
    with pytest.raises(ValidationError):
        services.create_announcement(
            branch=branch, title="Wrong branch", body="No.", classroom=elsewhere
        )


def test_the_database_refuses_a_notice_addressed_to_both(branch, room):
    """The service raises a ValidationError a form can render; the CheckConstraint is
    what makes the rule true. Both, because the second is the one that still holds
    when something bypasses the first — a data migration, a shell session, `loaddata`.
    """
    with pytest.raises(IntegrityError):
        Announcement.objects.create(
            branch=branch, title="Both", body="No.", is_school_wide=True, classroom=room
        )


def test_the_database_refuses_a_notice_addressed_to_nobody(branch):
    with pytest.raises(IntegrityError):
        Announcement.objects.create(branch=branch, title="Neither", body="No.")


def test_republishing_keeps_the_first_publication_time(branch):
    """Editing and re-publishing must not reorder a notice to the top of every feed as
    though it were news, and "when did the school tell us" has one answer."""
    notice = services.create_announcement(
        branch=branch, title="Sports day", body="Saturday.", is_school_wide=True
    )
    services.publish(notice)
    first = notice.published_at

    notice.body = "Saturday, 9am."
    notice.save(update_fields=["body"])
    services.publish(notice)

    assert notice.published_at == first


def test_withdrawing_keeps_the_receipts(branch, parent_a):
    notice = services.publish(
        services.create_announcement(
            branch=branch, title="Sports day", body="Saturday.", is_school_wide=True
        )
    )
    services.mark_read(announcement=notice, guardian=parent_a)
    services.unpublish(notice)

    assert notice.is_published is False
    assert AnnouncementRead.objects.filter(announcement=notice).count() == 1


def test_reading_twice_keeps_the_first_time(branch, parent_a):
    """The receipt answers "when were they first told". Refreshing it on every re-open
    would erase the only fact it exists to hold."""
    notice = services.publish(
        services.create_announcement(
            branch=branch, title="Sports day", body="Saturday.", is_school_wide=True
        )
    )
    first = services.mark_read(announcement=notice, guardian=parent_a)
    again = services.mark_read(announcement=notice, guardian=parent_a)

    assert first.pk == again.pk
    assert AnnouncementRead.objects.count() == 1


def test_expiry_is_reported_against_a_given_day(branch):
    from datetime import timedelta

    notice = services.create_announcement(
        branch=branch,
        title="PTM",
        body="Friday.",
        is_school_wide=True,
        expires_on=timezone.localdate(),
    )
    assert notice.has_expired() is False
    assert notice.has_expired(on=timezone.localdate() + timedelta(days=1)) is True
