"""The admin registrations, exercised rather than assumed.

CLAUDE.md records why this file exists: the layer contract does not cover `admin.py`.
`lint-imports` and `test_architecture.py` police views, services, selectors and models,
and the admin sits outside all of it while being able to write to every table. The one
catastrophic bug in this repo's history was an untested admin registration that stored
parent passwords in plain text for four phases.

`AnnouncementReadAdmin` makes a behavioural claim — that a receipt cannot be added or
edited by hand — and a claim made only in a method nobody calls in a test is prose.
"""

import pytest
from django.urls import reverse

from apps.announcements import services
from apps.announcements.models import AnnouncementRead

pytestmark = pytest.mark.django_db


@pytest.fixture
def root(django_user_model):
    return django_user_model.objects.create_superuser(phone="9000000001", password="pw")


def test_a_receipt_cannot_be_added_through_the_admin(client, root):
    """A receipt records that a named person saw something at a known time. An operator
    who can type one has turned a record into an assertion."""
    client.force_login(root)
    response = client.get(reverse("admin:announcements_announcementread_add"))
    assert response.status_code == 403


def test_a_receipt_cannot_be_edited_through_the_admin(client, root, branch, parent_a):
    notice = services.publish(
        services.create_announcement(
            branch=branch, title="Sports day", body="Saturday.", is_school_wide=True
        )
    )
    receipt = services.mark_read(announcement=notice, guardian=parent_a)
    was = receipt.read_at

    client.force_login(root)
    response = client.post(
        reverse("admin:announcements_announcementread_change", args=[receipt.pk]),
        {"announcement": notice.pk, "guardian": parent_a.pk, "read_at_0": "2020-01-01"},
    )

    assert response.status_code in (302, 403)
    receipt.refresh_from_db()
    assert receipt.read_at == was


def test_the_receipt_list_is_readable(client, root, branch, parent_a):
    """Read-only, not invisible. "Who was told, and when" is exactly the question an
    operator opens the admin to answer."""
    notice = services.publish(
        services.create_announcement(
            branch=branch, title="Sports day", body="Saturday.", is_school_wide=True
        )
    )
    services.mark_read(announcement=notice, guardian=parent_a)

    client.force_login(root)
    response = client.get(reverse("admin:announcements_announcementread_changelist"))
    assert response.status_code == 200
    assert b"Priya Sharma" in response.content


def test_editing_a_notice_through_the_admin_keeps_its_receipts(client, root, branch, parent_a):
    """The admin form is the surface with no layer contract over it. Editing a notice
    must not disturb the record of who had already read it."""
    notice = services.publish(
        services.create_announcement(
            branch=branch, title="Sports day", body="Saturday.", is_school_wide=True
        )
    )
    services.mark_read(announcement=notice, guardian=parent_a)

    client.force_login(root)
    client.post(
        reverse("admin:announcements_announcement_change", args=[notice.pk]),
        {
            "branch": branch.pk,
            "title": "Sports day — 9am",
            "body": "Saturday at nine.",
            "is_school_wide": "on",
            "is_published": "on",
            "published_at_0": notice.published_at.date().isoformat(),
            "published_at_1": "09:00:00",
        },
    )

    notice.refresh_from_db()
    assert notice.title == "Sports day — 9am"
    assert AnnouncementRead.objects.filter(announcement=notice, guardian=parent_a).count() == 1
