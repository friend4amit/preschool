"""Fixtures for attendance.

A room with three children in it, a second room, and a second branch — because the
questions worth asking here are "does the register leak across rooms" and "does it
leak across branches", and neither can be asked with one of each.
"""

from datetime import date

import pytest

from apps.core.models import AcademicYear, Classroom, Organization, Role, User
from apps.core.services import create_branch, grant_membership
from apps.people.services import (
    authorize_pickup,
    create_guardian,
    create_student,
    enroll_student,
    link_guardian,
)


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
    return Classroom.objects.create(branch=branch, name="Nursery B", capacity=20)


@pytest.fixture
def teacher(branch):
    user = User.objects.create_user(phone="9100000001", full_name="Meera Nair")
    grant_membership(user=user, branch=branch, role=Role.TEACHER)
    return user


@pytest.fixture
def parent(db):
    return User.objects.create_user(phone="9100000002", full_name="Priya Sharma")


@pytest.fixture
def children(branch, room, year):
    """Three children in Nursery A."""
    made = []
    for name in ("Aarav", "Bhavya", "Chetan"):
        student = create_student(branch=branch, first_name=name, date_of_birth=date(2023, 4, 1))
        enroll_student(student=student, classroom=room, academic_year=year)
        made.append(student)
    return made


@pytest.fixture
def child(children):
    return children[0]


@pytest.fixture
def guardian(branch, child, parent):
    who = create_guardian(branch=branch, full_name="Priya Sharma", phone="9876500001")
    who.user = parent
    who.save(update_fields=["user"])
    link_guardian(student=child, guardian=who, relationship="mother", is_primary=True)
    return who


@pytest.fixture
def uncle(child, guardian):
    """An authorisation valid today, so the happy path has something to use."""
    return authorize_pickup(
        student=child,
        authorized_by=guardian,
        name="Rakesh Uncle",
        relationship="Uncle",
        phone="9876500010",
    )
