"""Who a notice reaches, and who it does not.

The gate here is enrolment, not consent. That is the one thing about this feed that
differs from the photo feed sitting next to it in the portal, and the first test says
so out loud so that nobody copies the consent check across out of symmetry.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from apps.announcements import selectors, services
from apps.core.models import Consent, ConsentPurpose

pytestmark = pytest.mark.django_db


def _publish(**kwargs):
    return services.publish(services.create_announcement(**kwargs))


def test_a_notice_is_not_gated_on_photo_consent(branch, parent_a):
    """A guardian who refused photo consent must still be told the school is shut.

    This is the test that stops somebody symmetrising the two feeds. `photos_in_app`
    is a question about pictures of a child; a notice about term dates is not one.
    """
    Consent.objects.create(
        guardian=parent_a,
        purpose=ConsentPurpose.PHOTOS_IN_APP,
        branch=branch,
        granted=False,
    )
    _publish(branch=branch, title="Closed Monday", body="Holiday.", is_school_wide=True)

    assert selectors.feed_for(parent_a).count() == 1


def test_a_draft_reaches_nobody(branch, parent_a):
    services.create_announcement(
        branch=branch, title="Fee revision", body="Draft.", is_school_wide=True
    )
    assert selectors.feed_for(parent_a).count() == 0


def test_school_wide_reaches_every_parent(branch, parent_a, parent_b):
    _publish(branch=branch, title="Sports day", body="Saturday.", is_school_wide=True)
    assert selectors.feed_for(parent_a).count() == 1
    assert selectors.feed_for(parent_b).count() == 1


def test_a_room_notice_reaches_only_that_room(branch, room, parent_a, parent_b):
    """parent_b is in the school, and in a different room. They must not see it."""
    _publish(branch=branch, title="Nursery trip", body="Bring a hat.", classroom=room)

    assert selectors.feed_for(parent_a).count() == 1
    assert selectors.feed_for(parent_b).count() == 0


def test_an_expired_notice_drops_out_of_the_feed(branch, parent_a):
    yesterday = timezone.localdate() - timedelta(days=1)
    _publish(
        branch=branch,
        title="PTM",
        body="Yesterday.",
        is_school_wide=True,
        expires_on=yesterday,
    )
    assert selectors.feed_for(parent_a).count() == 0


def test_a_notice_expiring_today_is_still_showing(branch, parent_a):
    """Boundary, and it matters: `expires_on` is the last day it shows, not the first
    day it does not. An off-by-one here takes a notice down on the morning of the
    event it is about."""
    _publish(
        branch=branch,
        title="Sports day",
        body="Today.",
        is_school_wide=True,
        expires_on=timezone.localdate(),
    )
    assert selectors.feed_for(parent_a).count() == 1


def test_another_branch_does_not_leak(org, other_branch, parent_a):
    _publish(branch=other_branch, title="Other branch", body="Not yours.", is_school_wide=True)
    assert selectors.feed_for(parent_a).count() == 0


def test_unread_count_drops_when_the_notice_is_read(branch, parent_a):
    notice = _publish(branch=branch, title="Sports day", body="Saturday.", is_school_wide=True)
    assert selectors.unread_count(parent_a) == 1

    services.mark_read(announcement=notice, guardian=parent_a)
    assert selectors.unread_count(parent_a) == 0


def test_one_guardians_read_does_not_clear_anothers_badge(branch, parent_a, parent_b):
    """The receipt is per person, which is the whole reason it is a table."""
    notice = _publish(branch=branch, title="Sports day", body="Saturday.", is_school_wide=True)
    services.mark_read(announcement=notice, guardian=parent_a)

    assert selectors.unread_count(parent_a) == 0
    assert selectors.unread_count(parent_b) == 1


def test_a_notice_appears_once_for_a_guardian_with_two_children(
    branch, room, year, family_a, parent_a
):
    """Two children in the same addressed room must not double the row.

    The feed annotates the receipt with `Exists` rather than joining `reads` for
    exactly this reason, and a second child is what proves the join would have
    duplicated it.
    """
    from apps.people.services import create_student, enroll_student, link_guardian

    sibling = create_student(
        branch=branch, first_name="Ishaan", date_of_birth=family_a[0].date_of_birth
    )
    enroll_student(student=sibling, classroom=room, academic_year=year)
    link_guardian(student=sibling, guardian=family_a[2], relationship="mother", is_primary=True)

    _publish(branch=branch, title="Nursery trip", body="Bring a hat.", classroom=room)

    assert selectors.feed_for(parent_a).count() == 1


def test_audience_size_counts_accounts_not_guardians(branch, room, year, parent_a):
    """A guardian with no portal login cannot read a notice, so the denominator must
    not include them — otherwise every notice looks permanently unread."""
    from apps.people.services import create_guardian, link_guardian

    paper_only = create_guardian(branch=branch, full_name="No Account", phone="9876500099")
    link_guardian(
        student=parent_a.guardian_profile.student_links.first().student,
        guardian=paper_only,
        relationship="father",
    )

    notice = _publish(branch=branch, title="Sports day", body="Saturday.", is_school_wide=True)
    assert selectors.audience_size(notice) == 1


def test_staff_see_drafts_and_parents_do_not(branch, admin_user, parent_a):
    services.create_announcement(branch=branch, title="Draft", body="Not yet.", is_school_wide=True)
    assert selectors.for_user(admin_user).count() == 1
    assert selectors.feed_for(parent_a).count() == 0
