"""Fixtures for the notice board.

Two rooms rather than one, which is the difference from the activities fixtures. A
notice is addressed to the whole school or to a room, so the question worth asking is
whether a Nursery parent sees a notice written for Playgroup — and that question needs
a second room to exist.

Consent does not appear here at all, and its absence is the point. A notice is the
school talking to the parents of its own students; there is no purpose to consent to,
and a guardian who declined photo consent must still be told the school is shut on
Monday. `test_selectors.py` asserts that rather than leaving it implied.
"""

from datetime import date

import pytest

from apps.core.models import AcademicYear, Classroom, Organization, Role, User
from apps.core.services import create_branch, grant_membership
from apps.people.services import create_guardian, create_student, enroll_student, link_guardian


@pytest.fixture
def org(db):
    return Organization.objects.create(name="Aaroham", slug="aaroham")


@pytest.fixture
def branch(org):
    return create_branch(organization=org, name="Main", slug="main")


@pytest.fixture
def other_branch(org):
    return create_branch(organization=org, name="Second", slug="second")


@pytest.fixture
def year(branch):
    return AcademicYear.objects.create(
        branch=branch,
        name="2026-27",
        start_date=date(2026, 6, 1),
        end_date=date(2027, 4, 30),
        is_current=True,
    )


@pytest.fixture
def room(branch):
    return Classroom.objects.create(branch=branch, name="Nursery A", capacity=20)


@pytest.fixture
def other_room(branch):
    return Classroom.objects.create(branch=branch, name="Playgroup B", capacity=20)


@pytest.fixture
def admin_user(branch):
    user = User.objects.create_user(phone="9100000010", full_name="Office")
    grant_membership(user=user, branch=branch, role=Role.BRANCH_ADMIN)
    return user


@pytest.fixture
def teacher(branch):
    user = User.objects.create_user(phone="9100000011", full_name="Meera Nair")
    grant_membership(user=user, branch=branch, role=Role.TEACHER)
    return user


def _family(branch, room, year, *, name, phone, guardian_name, guardian_phone):
    """One child, one guardian with a portal account, enrolled in `room`."""
    student = create_student(branch=branch, first_name=name, date_of_birth=date(2023, 4, 1))
    enroll_student(student=student, classroom=room, academic_year=year)
    user = User.objects.create_user(phone=phone, full_name=guardian_name)
    who = create_guardian(branch=branch, full_name=guardian_name, phone=guardian_phone)
    who.user = user
    who.save(update_fields=["user"])
    link_guardian(student=student, guardian=who, relationship="mother", is_primary=True)
    return student, user, who


@pytest.fixture
def family_a(branch, room, year):
    return _family(
        branch,
        room,
        year,
        name="Aarav",
        phone="9100000002",
        guardian_name="Priya Sharma",
        guardian_phone="9876500001",
    )


@pytest.fixture
def family_b(branch, other_room, year):
    """A family in the OTHER room. Room-targeted notices are only meaningfully tested
    against a parent who is in the school but not in the addressed room."""
    return _family(
        branch,
        other_room,
        year,
        name="Bhavya",
        phone="9100000003",
        guardian_name="Rekha Iyer",
        guardian_phone="9876500002",
    )


@pytest.fixture
def child_a(family_a):
    return family_a[0]


@pytest.fixture
def parent_a(family_a):
    return family_a[1]


@pytest.fixture
def child_b(family_b):
    return family_b[0]


@pytest.fixture
def parent_b(family_b):
    return family_b[1]
