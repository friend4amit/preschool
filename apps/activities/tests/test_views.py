"""The screens.

The selector tests already prove the gate; these prove the views are actually wired
to it. That is a separate claim — a correct selector called from the wrong place, or
not called at all, fails none of the tests in test_consent_gate.py.

So the questions here are HTTP ones: does a stranger get 404 rather than 403, does a
parent with no consent get a page that explains rather than a blank one, and does the
publish button leave the blocked photos behind.
"""

import pytest
from django.urls import reverse

from apps.activities import selectors, services
from apps.activities.models import ActivityEntry, ActivityKind, IncidentSeverity, MediaAsset
from apps.core.models import ConsentPurpose

pytestmark = pytest.mark.django_db


@pytest.fixture
def signed_in_teacher(client, teacher):
    client.force_login(teacher)
    return teacher


def _photo(branch, teacher, *, key):
    media = services.register_upload(branch=branch, key=key, uploaded_by=teacher)
    return services.confirm_upload(media=media, byte_size=1024)


# --- the teacher's day ------------------------------------------------------------------


def test_the_day_screen_renders_for_a_teacher(client, signed_in_teacher, room, child_a):
    response = client.get(reverse("activities_day", args=[room.pk]))

    assert response.status_code == 200
    assert child_a.display_name in response.content.decode()


def test_a_teacher_at_another_branch_gets_404_for_a_room(client, org, room, child_a):
    """404, not 403 — a teacher at branch one must not learn branch two's room ids."""
    from apps.core.models import Role, User
    from apps.core.services import create_branch, grant_membership

    elsewhere = create_branch(organization=org, name="Second", slug="second")
    outsider = User.objects.create_user(phone="9100000077", full_name="Other Teacher")
    grant_membership(user=outsider, branch=elsewhere, role=Role.TEACHER)
    client.force_login(outsider)

    assert client.get(reverse("activities_day", args=[room.pk])).status_code == 404


def test_a_parent_cannot_open_the_staff_day_screen(client, parent_a, room):
    """The parent portal and the staff console are different URL trees on purpose."""
    client.force_login(parent_a)

    response = client.get(reverse("activities_day", args=[room.pk]))

    assert response.status_code in (302, 403, 404)


def test_the_bulk_button_writes_one_row_for_the_room(
    client, signed_in_teacher, room, child_a, child_b
):
    response = client.post(
        reverse("activities_quick_entry", args=[room.pk]),
        {"kind": ActivityKind.NAP, "student": "0"},
    )

    assert response.status_code == 302
    assert ActivityEntry.objects.count() == 1
    assert ActivityEntry.objects.get().classroom == room


def test_a_per_child_entry_targets_that_child(client, signed_in_teacher, room, child_a):
    client.post(
        reverse("activities_quick_entry", args=[room.pk]),
        {"kind": ActivityKind.MEAL, "student": str(child_a.pk), "body": "Ate everything"},
    )

    entry = ActivityEntry.objects.get()
    assert entry.student == child_a
    assert entry.classroom is None
    assert entry.is_published is False


def test_publishing_the_day_leaves_the_blocked_photos_behind(
    client, signed_in_teacher, branch, room, child_a, child_b, parent_a, consent_for
):
    """The whole day publishes; one photo does not. Stopping everything on one missing
    consent would strand the other twenty, so the count is reported instead."""
    ready = _photo(branch, signed_in_teacher, key="photos/ready.webp")
    services.tag(media=ready, student=child_a, tagged_by=signed_in_teacher)
    held = _photo(branch, signed_in_teacher, key="photos/held.webp")
    services.tag(media=held, student=child_b, tagged_by=signed_in_teacher)
    consent_for(parent_a, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS)
    services.record_for_classroom(classroom=room, kind=ActivityKind.NAP)

    response = client.post(reverse("activities_publish_day", args=[room.pk]), follow=True)

    assert response.status_code == 200
    ready.refresh_from_db()
    held.refresh_from_db()
    assert ready.is_published is True
    assert held.is_published is False
    assert ActivityEntry.objects.get().is_published is True
    # And the teacher is told which child held it back, not just that something did.
    assert child_b.display_name in response.content.decode()


# --- tagging ----------------------------------------------------------------------------


def test_the_tag_screen_flags_a_child_who_would_block_publication(
    client, signed_in_teacher, branch, child_a, child_b, parent_a, consent_for
):
    """The marker is on the tagging screen, which is the point — a rule discovered
    only when publish refuses is a rule that gets worked around."""
    media = _photo(branch, signed_in_teacher, key="photos/x.webp")
    consent_for(parent_a, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS)

    body = client.get(reverse("activities_tag", args=[media.pk])).content.decode()

    assert "No sharing consent on record" in body


def test_toggling_a_tag_adds_then_removes_it(client, signed_in_teacher, branch, child_a):
    media = _photo(branch, signed_in_teacher, key="photos/x.webp")
    url = reverse("activities_toggle_tag", args=[media.pk, child_a.pk])

    client.post(url)
    assert media.tags.count() == 1

    client.post(url)
    assert media.tags.count() == 0


def test_htmx_gets_the_one_row_back_rather_than_the_page(
    client, signed_in_teacher, branch, child_a
):
    media = _photo(branch, signed_in_teacher, key="photos/x.webp")

    response = client.post(
        reverse("activities_toggle_tag", args=[media.pk, child_a.pk]),
        headers={"hx-request": "true"},
    )

    body = response.content.decode()
    assert response.status_code == 200
    assert "<html" not in body.lower()
    assert child_a.display_name in body


def test_publishing_one_photo_reports_the_blocking_child_by_name(
    client, signed_in_teacher, branch, child_b
):
    media = _photo(branch, signed_in_teacher, key="photos/x.webp")
    services.tag(media=media, student=child_b, tagged_by=signed_in_teacher)

    response = client.post(reverse("activities_publish_photo", args=[media.pk]), follow=True)

    media.refresh_from_db()
    assert media.is_published is False
    assert child_b.display_name in response.content.decode()


# --- uploads ----------------------------------------------------------------------------


def test_asking_for_an_upload_url_says_so_plainly_when_r2_is_absent(
    client, signed_in_teacher, room
):
    """503, not 500. R2 being unconfigured is this machine's normal state, and a
    stack trace would send somebody hunting for a bug that is not there."""
    response = client.post(
        reverse("activities_upload_url", args=[room.pk]),
        {"filename": "IMG_4821.HEIC", "content_type": "image/heic"},
    )

    assert response.status_code == 503
    assert "not configured" in response.json()["error"]
    assert MediaAsset.objects.count() == 0, "no row should be written when we cannot presign"


def test_an_unacceptable_content_type_is_refused(client, signed_in_teacher, room):
    """The value is signed into the presigned URL, so an unchecked one would
    pre-authorise an upload of anything at all to our bucket."""
    response = client.post(
        reverse("activities_upload_url", args=[room.pk]),
        {"filename": "payload.svg", "content_type": "image/svg+xml"},
    )

    assert response.status_code == 400


# --- incidents --------------------------------------------------------------------------


def test_reporting_an_incident_reaches_the_family_immediately(
    client, signed_in_teacher, child_a, parent_a
):
    client.post(
        reverse("incident_new", args=[child_a.pk]),
        {
            "severity": IncidentSeverity.MINOR,
            "what_happened": "Grazed a knee on the path",
            "action_taken": "Cleaned and plastered",
        },
    )

    _, incidents = selectors.incidents_for_child_of(parent_a, child_a.pk)
    assert incidents.count() == 1


def test_a_parent_can_acknowledge_their_own_childs_incident(
    client, signed_in_teacher, child_a, parent_a
):
    incident = services.report_incident(
        student=child_a,
        severity=IncidentSeverity.MINOR,
        what_happened="Grazed a knee",
        action_taken="Cleaned",
        staff_responsible=signed_in_teacher,
    )
    client.force_login(parent_a)

    client.post(reverse("incident_acknowledge", args=[incident.pk]))

    incident.refresh_from_db()
    assert incident.acknowledged_by == parent_a


def test_a_parent_cannot_acknowledge_another_familys_incident(
    client, teacher, child_b, parent_a, parent_b
):
    """This would put the wrong name on the one record that exists to say who was
    told, so it is a 404 and not a quiet no-op."""
    incident = services.report_incident(
        student=child_b,
        severity=IncidentSeverity.MINOR,
        what_happened="Grazed a knee",
        action_taken="Cleaned",
        staff_responsible=teacher,
    )
    client.force_login(parent_a)

    assert client.post(reverse("incident_acknowledge", args=[incident.pk])).status_code == 404

    incident.refresh_from_db()
    assert incident.acknowledged_at is None


# --- the parent portal ------------------------------------------------------------------


def test_a_parent_gets_404_for_another_familys_photo_feed(client, child_b, parent_a):
    client.force_login(parent_a)

    assert client.get(reverse("my_child_photos", args=[child_b.pk])).status_code == 404


def test_a_parent_gets_404_for_another_familys_diary(client, child_b, parent_a):
    client.force_login(parent_a)

    assert client.get(reverse("my_child_diary", args=[child_b.pk])).status_code == 404


def test_the_feed_explains_itself_when_consent_is_off(client, child_a, parent_a):
    """Consent is off by default, so this is the first thing most families see. A
    blank screen reads as a broken app; the fix is a conversation with the office."""
    client.force_login(parent_a)

    body = client.get(reverse("my_child_photos", args=[child_a.pk])).content.decode()

    assert "Photos are switched off" in body


def test_the_feed_shows_a_published_photo_once_consent_is_on(
    client, branch, teacher, child_a, parent_a, consent_for
):
    media = _photo(branch, teacher, key="photos/a.webp")
    services.tag(media=media, student=child_a, tagged_by=teacher)
    consent_for(parent_a, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS)
    consent_for(parent_a, ConsentPurpose.PHOTOS_IN_APP)
    services.publish_media(media=media)
    client.force_login(parent_a)

    body = client.get(reverse("my_child_photos", args=[child_a.pk])).content.decode()

    assert "Photos are switched off" not in body
    assert reverse("media_file", args=[media.pk]) in body


def test_a_parent_cannot_fetch_another_familys_photo_bytes(
    client, branch, teacher, child_b, parent_a, parent_b, consent_for
):
    """The fallback file view applies the same gate as the feed. If it did not, the
    whole consent story would have a hole shaped like a URL."""
    media = _photo(branch, teacher, key="photos/b.webp")
    services.tag(media=media, student=child_b, tagged_by=teacher)
    consent_for(parent_b, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS)
    consent_for(parent_b, ConsentPurpose.PHOTOS_IN_APP)
    services.publish_media(media=media)
    client.force_login(parent_a)

    assert client.get(reverse("media_file", args=[media.pk])).status_code == 404


def test_an_anonymous_visitor_is_sent_to_sign_in(client, child_a):
    response = client.get(reverse("my_child_photos", args=[child_a.pk]))

    assert response.status_code == 302
    assert "/accounts/" in response["Location"]


def test_the_day_screen_renders_with_both_kinds_of_entry_staged(
    client, signed_in_teacher, branch, room, child_a
):
    """Regression: the staged list rendered the target with
    `|default:entry.classroom.name`, and a filter ARGUMENT resolves strictly — so a
    student entry, whose classroom is None, raised VariableDoesNotExist and took the
    whole page down. Every earlier render test happened to have no entries at all.
    """
    services.record_for_classroom(classroom=room, kind=ActivityKind.NAP, body="All slept")
    services.record_entry(
        kind=ActivityKind.MEAL, branch=branch, student=child_a, body="Second helping"
    )

    response = client.get(reverse("activities_day", args=[room.pk]))

    assert response.status_code == 200
    body = response.content.decode()
    assert child_a.display_name in body
    assert room.name in body


# --- the "Photos" nav entry point -------------------------------------------------------


def test_photos_nav_goes_straight_to_the_feed_for_a_one_child_family(client, child_a, parent_a):
    """The feed is opened daily, and most families here have one child. Charging them
    a tap through a one-item list every time is a choice that is not being offered."""
    client.force_login(parent_a)

    response = client.get(reverse("my_photos"))

    assert response.status_code == 302
    assert response["Location"] == reverse("my_child_photos", args=[child_a.pk])


def test_photos_nav_goes_to_the_picker_when_there_is_more_than_one_child(
    client, branch, room, year, child_a, parent_a
):
    from apps.people.services import create_student, enroll_student, link_guardian

    sibling = create_student(
        branch=branch, first_name="Ishaan", date_of_birth=child_a.date_of_birth
    )
    enroll_student(student=sibling, classroom=room, academic_year=year)
    link_guardian(
        student=sibling,
        guardian=parent_a.guardian_profile,
        relationship="mother",
    )
    client.force_login(parent_a)

    response = client.get(reverse("my_photos"))

    assert response.status_code == 302
    assert response["Location"] == reverse("my_children")
