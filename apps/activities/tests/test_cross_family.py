"""Cross-family isolation.

CLAUDE.md: every parent-visible model gets a cross-family test the day it is added.
This app adds three of them, so this file exists on day one rather than after the
first support ticket.

The rule these enforce is "return 404, not 403" — the selectors return None or an
empty queryset and never distinguish "not yours" from "does not exist", so a view
built on them cannot leak the existence of another family's records by status code.
"""

import pytest

from apps.activities import selectors, services
from apps.activities.models import ActivityKind, IncidentSeverity
from apps.core.models import ConsentPurpose

pytestmark = pytest.mark.django_db


def _published_photo_of(child, branch, teacher, parent, consent_for, *, key):
    media = services.register_upload(branch=branch, key=key, uploaded_by=teacher)
    services.confirm_upload(media=media, byte_size=1024)
    services.tag(media=media, student=child, tagged_by=teacher)
    consent_for(parent, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS)
    consent_for(parent, ConsentPurpose.PHOTOS_IN_APP)
    services.publish_media(media=media)
    return media


def test_a_parent_cannot_reach_another_familys_photo_feed(
    branch, teacher, child_a, child_b, parent_a, parent_b, consent_for
):
    _published_photo_of(child_b, branch, teacher, parent_b, consent_for, key="photos/b.webp")

    # Parent A asks for child B by id — the id is a small integer and guessing it is
    # not a feat.
    child, feed = selectors.feed_for_child_of(parent_a, child_b.pk)

    assert child is None
    assert list(feed) == []


def test_a_parent_sees_only_their_own_child_in_their_own_feed(
    branch, teacher, child_a, child_b, parent_a, parent_b, consent_for
):
    """Both children are in the same room, so this is the real case rather than a
    convenient one."""
    mine = _published_photo_of(child_a, branch, teacher, parent_a, consent_for, key="photos/a.webp")
    _published_photo_of(child_b, branch, teacher, parent_b, consent_for, key="photos/b.webp")

    _, feed = selectors.feed_for_child_of(parent_a, child_a.pk)

    assert list(feed) == [mine]


def test_a_parent_cannot_reach_another_familys_activity_entries(
    branch, teacher, child_a, child_b, parent_a
):
    services.record_entry(
        kind=ActivityKind.MEAL, branch=branch, student=child_b, body="Ate well", author=teacher
    )

    child, entries = selectors.entries_for_child_of(parent_a, child_b.pk)

    assert child is None
    assert list(entries) == []


def test_a_parent_cannot_reach_another_familys_incidents(
    branch, teacher, child_a, child_b, parent_a
):
    """An incident is the most sensitive record in the app and is deliberately not
    consent-gated, so its only protection is this scoping."""
    services.report_incident(
        student=child_b,
        severity=IncidentSeverity.MINOR,
        what_happened="Grazed a knee",
        action_taken="Cleaned and plastered",
        staff_responsible=teacher,
    )

    child, incidents = selectors.incidents_for_child_of(parent_a, child_b.pk)

    assert child is None
    assert list(incidents) == []


def test_an_anonymous_user_sees_nothing(branch, teacher, child_a, parent_a, consent_for):
    from django.contrib.auth.models import AnonymousUser

    _published_photo_of(child_a, branch, teacher, parent_a, consent_for, key="photos/a.webp")

    child, feed = selectors.feed_for_child_of(AnonymousUser(), child_a.pk)

    assert child is None
    assert list(feed) == []


def test_staff_at_another_branch_see_no_media(org, branch, teacher, child_a, parent_a, consent_for):
    """Branch isolation, which is the other direction the same query can leak in."""
    from apps.core.models import Role, User
    from apps.core.services import create_branch, grant_membership

    _published_photo_of(child_a, branch, teacher, parent_a, consent_for, key="photos/a.webp")

    elsewhere = create_branch(organization=org, name="Second", slug="second")
    outsider = User.objects.create_user(phone="9100000077", full_name="Other Teacher")
    grant_membership(user=outsider, branch=elsewhere, role=Role.TEACHER)

    assert list(selectors.media_for_user(outsider)) == []
    assert list(selectors.entries_for_user(outsider)) == []


def test_a_parent_reaching_the_feed_as_staff_still_sees_it_as_a_parent(
    branch, teacher, child_a, parent_a, consent_for
):
    """`feed_for_child_of` goes through `children_of`, not `students_for_user`. A
    teacher who is also a parent gets their own child through the parent path and
    every other child not at all."""
    from apps.core.models import Role
    from apps.core.services import grant_membership

    grant_membership(user=parent_a, branch=branch, role=Role.TEACHER)
    _published_photo_of(child_a, branch, teacher, parent_a, consent_for, key="photos/a.webp")

    # Their own child: reachable.
    assert selectors.feed_for_child_of(parent_a, child_a.pk)[0] == child_a

    # Staff membership does not widen the parent path — a child they are not a
    # guardian of stays invisible on it, even though `students_for_user` would show
    # them the child.
    from apps.people.services import create_student

    stranger = create_student(
        branch=branch, first_name="Divya", date_of_birth=child_a.date_of_birth
    )
    assert selectors.feed_for_child_of(parent_a, stranger.pk)[0] is None
