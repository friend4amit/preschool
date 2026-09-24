"""404, never 403, when a parent asks for a notice that is not theirs.

Written the day the model was added, per CLAUDE.md, and never deleted. A 403 tells
somebody walking ids that they guessed a real notice; for a room-targeted one that
leaks which rooms exist and, with a couple of tries, that something was sent to a room
their child is not in.
"""

import pytest
from django.urls import reverse

from apps.announcements import selectors, services

pytestmark = pytest.mark.django_db


def test_a_room_notice_is_a_404_for_a_parent_in_another_room(client, branch, room, parent_b):
    notice = services.publish(
        services.create_announcement(
            branch=branch, title="Nursery trip", body="Bring a hat.", classroom=room
        )
    )
    client.force_login(parent_b)
    assert client.get(reverse("my_announcement", args=[notice.pk])).status_code == 404


def test_a_draft_is_a_404_for_a_parent_it_is_addressed_to(client, branch, parent_a):
    """Unpublished is not "visible but greyed out". It does not exist to a parent."""
    notice = services.create_announcement(
        branch=branch, title="Fee revision", body="Draft.", is_school_wide=True
    )
    client.force_login(parent_a)
    assert client.get(reverse("my_announcement", args=[notice.pk])).status_code == 404


def test_another_branch_is_a_404(client, other_branch, parent_a):
    notice = services.publish(
        services.create_announcement(
            branch=other_branch, title="Other branch", body="Not yours.", is_school_wide=True
        )
    )
    client.force_login(parent_a)
    assert client.get(reverse("my_announcement", args=[notice.pk])).status_code == 404


def test_reading_someone_elses_notice_records_nothing(client, branch, room, parent_b):
    """The 404 has to happen before the receipt is written. A view that marked read and
    then checked would leave a row proving the notice exists."""
    from apps.announcements.models import AnnouncementRead

    notice = services.publish(
        services.create_announcement(
            branch=branch, title="Nursery trip", body="Bring a hat.", classroom=room
        )
    )
    client.force_login(parent_b)
    client.get(reverse("my_announcement", args=[notice.pk]))

    assert AnnouncementRead.objects.count() == 0


def test_staff_at_another_branch_cannot_open_it(client, org, other_branch, branch):
    from apps.core.models import Role, User
    from apps.core.services import grant_membership

    outsider = User.objects.create_user(phone="9100000050", full_name="Other Office")
    grant_membership(user=outsider, branch=other_branch, role=Role.BRANCH_ADMIN)

    notice = services.create_announcement(
        branch=branch, title="Ours", body="Not theirs.", is_school_wide=True
    )
    client.force_login(outsider)
    assert client.get(reverse("announcement_detail", args=[notice.pk])).status_code == 404
    assert selectors.staff_detail(outsider, notice.pk) is None
