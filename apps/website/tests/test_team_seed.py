"""The team the public site ships with.

One rule here outranks the rest: **Dr. Surashree Shome does not appear on this site.**
docs/implementation-plan.md removes her card entirely, and `seed_media` blocks her
photograph by filename. This file closes the third door — the seeded content itself —
so that all three would have to be undone deliberately rather than by someone adding
a plausible-looking row.
"""

import pytest

from apps.core.selectors import current_branch_fallback
from apps.website.management.commands.seed_media import PORTRAITS, is_blocked
from apps.website.management.commands.seed_website import TEAM
from apps.website.models import TeamMember

pytestmark = pytest.mark.django_db


@pytest.fixture
def seeded(db):
    from django.core.management import call_command

    from apps.core.models import Branch, Organization

    org = Organization.objects.create(name="Aaroham", slug="aaroham")
    Branch.objects.create(organization=org, name="Main", slug="main", is_active=True)
    call_command("seed_website", verbosity=0)
    return current_branch_fallback()


# --------------------------------------------------------------------------------
# The removal
# --------------------------------------------------------------------------------


def test_the_removed_founder_is_in_no_seed_list():
    """Names, not just files. The blocklist stops her photograph; this stops a card
    being typed in beside it."""
    blob = " ".join(
        f"{name} {role} {credentials} {bio}" for name, role, credentials, bio in TEAM
    ).lower()
    assert "surashree" not in blob
    assert "shome" not in blob
    assert not any("surashree" in str(p).lower() or "shome" in str(p).lower() for p in PORTRAITS)


def test_no_seeded_portrait_is_a_blocked_file():
    """Every portrait this command would attach must survive the blocklist. If one
    ever does not, the seeder is trying to ship something the plan forbids."""
    for name, source, _widths in PORTRAITS:
        assert is_blocked(source) is None, f"{name}'s portrait {source} is blocked"


def test_seeding_creates_no_row_for_the_removed_founder(seeded):
    assert not TeamMember.objects.filter(name__icontains="surashree").exists()
    assert not TeamMember.objects.filter(name__icontains="shome").exists()


# --------------------------------------------------------------------------------
# The team that does ship
# --------------------------------------------------------------------------------


def test_the_founders_are_seeded_and_published(seeded):
    prachi = TeamMember.objects.get(name="Prachi Tamrakar")
    preevi = TeamMember.objects.get(name="Preevi")

    assert prachi.role == "Founder & Director"
    assert preevi.role == "Co-founder"
    assert prachi.is_published and preevi.is_published
    # Order is the display order on /our-team/, and the founder leads.
    assert prachi.order < preevi.order


def test_prachis_bio_carries_over_from_the_reference_site(seeded):
    """Her own copy, not something written for her. The plan says her card carries
    over; this asserts it actually did rather than being replaced by a placeholder."""
    prachi = TeamMember.objects.get(name="Prachi Tamrakar")

    assert len(prachi.bio) > 300
    assert "early childhood educator" in prachi.bio
    # The old school's name must not have come across with it.
    assert "udgam" not in prachi.bio.lower()


def test_a_member_with_no_bio_still_renders(client, seeded):
    """Preevi has a name and a role and nothing else, because nobody has given us
    more and inventing a biography for a real person is not shippable. The card must
    stand up anyway — the template falls back to an initial where a photo would be."""
    response = client.get("/our-team/")

    assert response.status_code == 200
    body = response.content.decode()
    assert "Preevi" in body
    assert "Co-founder" in body
    assert "Prachi Tamrakar" in body


def test_seeding_twice_does_not_duplicate_anyone(seeded):
    """Matched on name, so the command can be re-run after an edit without leaving a
    second Prachi behind."""
    from django.core.management import call_command

    call_command("seed_website", verbosity=0)

    assert TeamMember.objects.filter(name="Prachi Tamrakar").count() == 1
    assert TeamMember.objects.count() == len(TEAM)


def test_reseeding_does_not_clear_an_attached_portrait(seeded):
    """`photo` is not in the seeder's defaults on purpose: seed_media attaches it, and
    a later content re-run must not wipe the image."""
    from django.core.management import call_command

    prachi = TeamMember.objects.get(name="Prachi Tamrakar")
    prachi.photo = "team/prachi-tamrakar-800.webp"
    prachi.save(update_fields=["photo"])

    call_command("seed_website", verbosity=0)

    prachi.refresh_from_db()
    assert prachi.photo.name == "team/prachi-tamrakar-800.webp"
