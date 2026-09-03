"""Who can see whom. The highest-value tests in the phase.

`docs/implementation-plan.md` calls the cross-family check "the permission test to
write now and keep forever". It is written here at the selector layer because that is
the layer that exists; the HTTP-level companion — another family's student id returns
**404, not 403**, so existence is not leaked — lands with the student detail view.
"""

import pytest

from apps.core.models import User
from apps.people.selectors import (
    children_of,
    guardians_for_user,
    roster,
    search_students,
    staff_for_user,
    student_detail_for_user,
    students_for_user,
    students_missing_an_emergency_contact,
    valid_pickups_for,
)

pytestmark = pytest.mark.django_db


# --- the canary ---------------------------------------------------------------------


def test_a_parent_cannot_see_another_familys_child(family, other_family, parent_user):
    """The reputational failure mode of the whole product, in one assertion."""
    mine, _ = family
    theirs, _ = other_family

    visible = students_for_user(parent_user)
    assert mine in visible
    assert theirs not in visible


def test_fetching_another_familys_child_by_id_returns_nothing(family, other_family, parent_user):
    """Guessing an id is the attack. The selector returns None and the view turns
    that into a 404 — never a 403, which would confirm the child exists."""
    _, _ = family
    theirs, _ = other_family
    assert student_detail_for_user(parent_user, theirs.pk) is None


def test_a_parent_with_no_guardian_profile_sees_nobody(family, db):
    """An account with no links is not an account with every link."""
    stranger = User.objects.create_user(phone="9111111111")
    assert list(students_for_user(stranger)) == []


def test_an_anonymous_user_sees_nobody(family):
    from django.contrib.auth.models import AnonymousUser

    assert list(students_for_user(AnonymousUser())) == []


def test_a_parent_cannot_read_the_staff_list(parent_user, teacher_user, branch):
    from apps.people.services import create_staff_profile

    create_staff_profile(branch=branch, user=teacher_user, designation="Lead teacher")
    assert list(staff_for_user(parent_user)) == []
    assert staff_for_user(teacher_user).count() == 1


def test_a_parent_sees_only_their_own_guardian_record(family, other_family, parent_user):
    _, mine = family
    _, theirs = other_family
    visible = guardians_for_user(parent_user)
    assert mine in visible
    assert theirs not in visible


# --- staff and superadmin ------------------------------------------------------------


def test_staff_see_every_child_at_their_branch(family, other_family, teacher_user):
    assert students_for_user(teacher_user).count() == 2


def test_staff_do_not_see_another_branch(family, other_branch, teacher_user):
    """Branch two does not exist yet. The scoping does, which is the whole point of
    carrying `branch` from the first migration."""
    from datetime import date

    from apps.people.services import create_student

    elsewhere = create_student(
        branch=other_branch, first_name="Not ours", date_of_birth=date(2023, 1, 1)
    )
    assert elsewhere not in students_for_user(teacher_user)


def test_a_superadmin_sees_everything(family, other_family, other_branch, superadmin):
    from datetime import date

    from apps.people.services import create_student

    create_student(branch=other_branch, first_name="Elsewhere", date_of_birth=date(2023, 1, 1))
    assert students_for_user(superadmin).count() == 3


def test_a_teacher_who_is_also_a_parent_gets_the_wider_view(family, other_family, teacher_user):
    """The membership is the broader grant, so it wins. A staff member with a child
    at the school must not have their roster narrowed to their own family."""
    from apps.people.services import create_guardian, link_guardian

    mine, _ = family
    guardian = create_guardian(branch=mine.branch, full_name="Meera Nair", phone="9000000003")
    guardian.user = teacher_user
    guardian.save(update_fields=["user"])
    link_guardian(student=mine, guardian=guardian, relationship="mother")

    assert students_for_user(teacher_user).count() == 2


# --- the parent portal ---------------------------------------------------------------


def test_children_of_is_the_guardian_link_and_nothing_else(family, other_family, teacher_user):
    """Distinct from students_for_user on purpose: "my children" must stay my children
    even for a user whose staff role would otherwise widen it."""
    assert list(children_of(teacher_user)) == []


# --- filters and rosters -------------------------------------------------------------


def test_search_scopes_before_it_filters(family, other_family, parent_user):
    """A search term must never reach outside the caller's own scope."""
    theirs, _ = other_family
    assert list(search_students(parent_user, query="Ishaan")) == []


def test_search_finds_a_child_by_preferred_name(family, teacher_user):
    student, _ = family
    student.preferred_name = "Chintu"
    student.save()
    assert list(search_students(teacher_user, query="chintu")) == [student]


def test_roster_is_scoped_too(enrolled, other_family, classroom, parent_user, teacher_user):
    """Guessing a classroom id must not hand over the room's register."""
    assert roster(classroom.pk, user=teacher_user).count() == 1
    assert roster(classroom.pk, user=parent_user).count() == 1

    from django.contrib.auth.models import AnonymousUser

    assert roster(classroom.pk, user=AnonymousUser()).count() == 0


def test_students_missing_an_emergency_contact_is_the_office_checklist(family, branch):
    from apps.people.services import add_emergency_contact

    student, _ = family
    assert student in students_missing_an_emergency_contact(branch)

    add_emergency_contact(
        student=student, name="Grandmother", relationship="Grandmother", phone="9876500009"
    )
    assert student not in students_missing_an_emergency_contact(branch)


def test_expired_pickup_authorisation_is_not_returned(family):
    """The whole reason AuthorizedPickup carries a window."""
    from datetime import date, timedelta

    from django.utils import timezone

    from apps.people.services import authorize_pickup

    student, guardian = family
    yesterday = timezone.localdate() - timedelta(days=1)

    expired = authorize_pickup(
        student=student,
        authorized_by=guardian,
        name="Uncle",
        relationship="Uncle",
        phone="9876500010",
        valid_from=date(2026, 1, 1),
        valid_to=yesterday,
    )
    current = authorize_pickup(
        student=student,
        authorized_by=guardian,
        name="Grandfather",
        relationship="Grandfather",
        phone="9876500011",
    )

    valid = list(valid_pickups_for(student))
    assert current in valid
    assert expired not in valid
