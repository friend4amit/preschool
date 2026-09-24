"""Fixtures for the dashboard and the exports.

Two branches and two families, because the questions this app has to answer are about
scope: a dashboard that counts another branch's children is wrong, and a CSV that
exports them is a leak. A single-branch fixture would pass a weaker version of every
test in here.
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
def other_year(other_branch):
    return AcademicYear.objects.create(
        branch=other_branch,
        name="2026-27",
        start_date=date(2026, 6, 1),
        end_date=date(2027, 4, 30),
        is_current=True,
    )


@pytest.fixture
def room(branch):
    return Classroom.objects.create(branch=branch, name="Nursery A", capacity=20)


@pytest.fixture
def other_room(other_branch):
    return Classroom.objects.create(branch=other_branch, name="Theirs", capacity=20)


@pytest.fixture
def admin_user(branch):
    user = User.objects.create_user(phone="9100000010", full_name="Office")
    grant_membership(user=user, branch=branch, role=Role.BRANCH_ADMIN)
    return user


@pytest.fixture
def other_admin(other_branch):
    user = User.objects.create_user(phone="9100000020", full_name="Other Office")
    grant_membership(user=user, branch=other_branch, role=Role.BRANCH_ADMIN)
    return user


def _family(branch, room, year, *, name, phone, guardian_name, guardian_phone):
    student = create_student(branch=branch, first_name=name, date_of_birth=date(2023, 4, 1))
    enroll_student(student=student, classroom=room, academic_year=year)
    user = User.objects.create_user(phone=phone, full_name=guardian_name)
    who = create_guardian(branch=branch, full_name=guardian_name, phone=guardian_phone)
    who.user = user
    who.save(update_fields=["user"])
    link_guardian(student=student, guardian=who, relationship="mother", is_primary=True)
    return student, user, who


@pytest.fixture
def child_a(branch, room, year):
    return _family(
        branch,
        room,
        year,
        name="Aarav",
        phone="9100000002",
        guardian_name="Priya Sharma",
        guardian_phone="9876500001",
    )[0]


@pytest.fixture
def child_b(branch, room, year):
    return _family(
        branch,
        room,
        year,
        name="Bhavya",
        phone="9100000003",
        guardian_name="Rekha Iyer",
        guardian_phone="9876500002",
    )[0]


@pytest.fixture
def other_child(other_branch, other_room, other_year):
    """A child at the branch this user does not work at. Nothing should ever count or
    export them."""
    return _family(
        other_branch,
        other_room,
        other_year,
        name="Zoya",
        phone="9100000004",
        guardian_name="Sana Khan",
        guardian_phone="9876500003",
    )[0]
