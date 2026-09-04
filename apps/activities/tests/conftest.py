"""Fixtures for activities and photos.

The shape here is dictated by the questions worth asking. A photo feed leaks in three
directions and each needs a different piece of scenery:

- across families — hence two children with two unrelated guardians;
- across branches — hence a second branch;
- across consent — hence guardians whose consent rows are set independently.

`consent_for` is the lever most tests pull. Consent is off by default, per
docs/plan.md, so a test that forgets to grant is testing the closed door, which is
usually the right test anyway.
"""

from datetime import date

import pytest

from apps.core.models import (
    AcademicYear,
    Classroom,
    Consent,
    ConsentPurpose,
    Organization,
    Role,
    User,
)
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
def teacher(branch):
    user = User.objects.create_user(phone="9100000001", full_name="Meera Nair")
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
def family_b(branch, room, year):
    """A second, unrelated family in the SAME room — which is what makes the
    cross-family tests meaningful. Two children in different rooms would pass a
    weaker version of the same test."""
    return _family(
        branch,
        room,
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


@pytest.fixture
def consent_for(branch):
    """Grant or refuse one purpose for one guardian user.

    `granted=False` is a recorded refusal and is NOT the same as no row at all — the
    multi-guardian rule in selectors.py turns on exactly that difference, so the
    fixture has to be able to express both.
    """

    def _set(user, purpose=ConsentPurpose.PHOTOS_IN_APP, *, granted=True):
        from django.utils import timezone

        return Consent.objects.update_or_create(
            guardian=user,
            purpose=purpose,
            branch=branch,
            defaults={
                "granted": granted,
                "granted_at": timezone.now() if granted else None,
                "revoked_at": None,
            },
        )[0]

    return _set
