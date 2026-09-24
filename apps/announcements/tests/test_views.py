"""The screens, both sides of the notice board."""

import pytest
from django.urls import reverse

from apps.announcements import selectors, services
from apps.announcements.models import AnnouncementRead

pytestmark = pytest.mark.django_db


def _published(branch, **kwargs):
    kwargs.setdefault("title", "Sports day")
    kwargs.setdefault("body", "Saturday at nine.")
    kwargs.setdefault("is_school_wide", True)
    return services.publish(services.create_announcement(branch=branch, **kwargs))


# --------------------------------------------------------------------------------
# Staff
# --------------------------------------------------------------------------------


def test_a_parent_cannot_reach_the_staff_notice_board(client, parent_a):
    client.force_login(parent_a)
    response = client.get(reverse("announcement_list"))
    assert response.status_code == 302  # bounced to login by the staff gate


def test_writing_a_notice_saves_a_draft(client, admin_user, room):
    client.force_login(admin_user)
    response = client.post(
        reverse("announcement_new"),
        {"title": "Sports day", "body": "Saturday.", "audience": str(room.pk)},
        follow=True,
    )
    assert response.status_code == 200

    from apps.announcements.models import Announcement

    notice = Announcement.objects.get()
    assert notice.is_published is False
    assert notice.classroom == room
    assert notice.author == admin_user


def test_the_audience_choices_are_only_this_users_rooms(client, admin_user, other_branch):
    """A form offering a room the user cannot write to is a permission bug with a
    dropdown in front of it."""
    from apps.core.models import Classroom

    Classroom.objects.create(branch=other_branch, name="Theirs", capacity=10)
    client.force_login(admin_user)
    response = client.get(reverse("announcement_new"))

    assert b"Theirs" not in response.content


def test_publishing_then_withdrawing(client, admin_user, branch, parent_a):
    notice = services.create_announcement(
        branch=branch, title="Sports day", body="Saturday.", is_school_wide=True
    )
    client.force_login(admin_user)

    client.post(reverse("announcement_publish", args=[notice.pk]))
    notice.refresh_from_db()
    assert notice.is_published is True

    client.post(reverse("announcement_unpublish", args=[notice.pk]))
    notice.refresh_from_db()
    assert notice.is_published is False


def test_publish_refuses_a_get(client, admin_user, branch):
    notice = services.create_announcement(
        branch=branch, title="Sports day", body="Saturday.", is_school_wide=True
    )
    client.force_login(admin_user)
    assert client.get(reverse("announcement_publish", args=[notice.pk])).status_code == 405


def test_the_detail_page_shows_the_read_count(client, admin_user, branch, parent_a):
    notice = _published(branch)
    services.mark_read(announcement=notice, guardian=parent_a)

    client.force_login(admin_user)
    response = client.get(reverse("announcement_detail", args=[notice.pk]))
    assert response.status_code == 200
    assert response.context["read_count"] == 1
    assert response.context["audience_size"] == 1


# --------------------------------------------------------------------------------
# Parent portal
# --------------------------------------------------------------------------------


def test_the_portal_lists_published_notices(client, branch, parent_a):
    _published(branch)
    client.force_login(parent_a)
    response = client.get(reverse("my_announcements"))

    assert response.status_code == 200
    assert b"Sports day" in response.content


def test_opening_a_notice_records_the_receipt(client, branch, parent_a):
    """The receipt is written by the detail view and nowhere else. "It appeared in a
    list they scrolled past" is not the claim it exists to make."""
    notice = _published(branch)
    client.force_login(parent_a)

    client.get(reverse("my_announcements"))
    assert AnnouncementRead.objects.count() == 0

    client.get(reverse("my_announcement", args=[notice.pk]))
    assert AnnouncementRead.objects.filter(announcement=notice, guardian=parent_a).count() == 1


def test_the_badge_appears_and_then_does_not(client, branch, parent_a):
    notice = _published(branch)
    client.force_login(parent_a)

    response = client.get(reverse("my_children"))
    assert response.context["portal_announcements_unread"] == 1

    client.get(reverse("my_announcement", args=[notice.pk]))
    response = client.get(reverse("my_children"))
    assert response.context["portal_announcements_unread"] == 0


def test_the_badge_is_per_person_not_per_browser(client, branch, parent_a):
    """The difference from the photo badge, asserted rather than assumed: a fresh
    client is a fresh session, and the notices badge stays cleared because the fact
    recorded is "this person read it"."""
    notice = _published(branch)
    client.force_login(parent_a)
    client.get(reverse("my_announcement", args=[notice.pk]))

    from django.test import Client

    other_browser = Client()
    other_browser.force_login(parent_a)
    response = other_browser.get(reverse("my_children"))
    assert response.context["portal_announcements_unread"] == 0


def test_an_anonymous_visitor_is_sent_to_login(client, branch):
    notice = _published(branch)
    assert client.get(reverse("my_announcement", args=[notice.pk])).status_code == 302


def test_the_staff_list_survives_a_user_with_two_branches(client, admin_user, branch, other_branch):
    """`for_user` is `.distinct()` ordered by an F expression with `nulls_first`, and
    the branch filter is a join — which is the combination where Postgres either
    refuses `SELECT DISTINCT ... ORDER BY <expression>` or quietly stops deduplicating.

    A second membership is what makes the join multiply rows, and a draft alongside a
    published notice is what puts a NULL in the ordering column. Neither is exotic: the
    owner will have both the day branch two exists.
    """
    from apps.core.models import Role
    from apps.core.services import grant_membership

    grant_membership(user=admin_user, branch=other_branch, role=Role.BRANCH_ADMIN)

    _published(branch, title="Published one")
    services.create_announcement(
        branch=other_branch, title="Draft one", body="Not yet.", is_school_wide=True
    )

    client.force_login(admin_user)
    response = client.get(reverse("announcement_list"))

    assert response.status_code == 200
    assert list(response.context["announcements"]) == list(selectors.for_user(admin_user))
    assert selectors.for_user(admin_user).count() == 2
    assert response.content.count(b"Published one") == 1
