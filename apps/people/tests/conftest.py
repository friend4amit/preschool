"""Fixtures for the people app.

Two branches and two unrelated families, always. A single-family fixture cannot
catch a leak, and a leak between families is the failure mode that matters here.
"""

from datetime import date

import pytest

from apps.core.models import AcademicYear, Classroom, Organization, Role, User
from apps.core.services import create_branch, grant_membership
from apps.people.services import create_guardian, create_student, enroll_student, link_guardian


@pytest.fixture
def org():
    return Organization.objects.create(name="Aaroham", slug="aaroham")


@pytest.fixture
def branch(org):
    return create_branch(organization=org, name="Main", slug="main")


@pytest.fixture
def other_branch(org):
    """Branch two, years early. The switcher is hidden, but the scoping is not."""
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
def classroom(branch):
    return Classroom.objects.create(branch=branch, name="Nursery A", capacity=20)


@pytest.fixture
def other_classroom(branch):
    return Classroom.objects.create(branch=branch, name="Nursery B", capacity=20)


@pytest.fixture
def parent_user(db):
    return User.objects.create_user(phone="9000000001", full_name="Priya Sharma")


@pytest.fixture
def other_parent_user(db):
    return User.objects.create_user(phone="9000000002", full_name="Anita Rao")


@pytest.fixture
def teacher_user(db, branch):
    user = User.objects.create_user(phone="9000000003", full_name="Meera Nair")
    grant_membership(user=user, branch=branch, role=Role.TEACHER)
    return user


@pytest.fixture
def superadmin(db):
    return User.objects.create_superuser(phone="9000000000", password="x")


def _family(branch, user, child_name, phone):
    student = create_student(branch=branch, first_name=child_name, date_of_birth=date(2023, 4, 12))
    guardian = create_guardian(branch=branch, full_name=f"{child_name} parent", phone=phone)
    guardian.user = user
    guardian.save(update_fields=["user"])
    link_guardian(student=student, guardian=guardian, relationship="mother", is_primary=True)
    return student, guardian


@pytest.fixture
def family(branch, parent_user):
    """Aarav and his mother."""
    return _family(branch, parent_user, "Aarav", "9876500001")


@pytest.fixture
def other_family(branch, other_parent_user):
    """A second, unrelated family at the same branch — the one that must never leak."""
    return _family(branch, other_parent_user, "Ishaan", "9876500002")


@pytest.fixture
def enrolled(family, classroom, year):
    student, _ = family
    return enroll_student(student=student, classroom=classroom, academic_year=year)
