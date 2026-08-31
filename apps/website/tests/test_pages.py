"""Public pages: they render, they carry their SEO, and they leak nothing.

Cheap tests, but they catch the failure mode that matters for a marketing site — a
page that 500s or silently drops its metadata is a page that stops bringing families in.
"""

import pytest
from django.urls import reverse

from apps.core.models import Organization
from apps.core.services import create_branch
from apps.website.models import Enquiry, Program, SiteSettings, TeamMember, Testimonial

pytestmark = pytest.mark.django_db

PUBLIC_PAGES = ["home", "about", "approach", "programs", "team", "special_education", "contact"]


@pytest.fixture
def branch():
    org = Organization.objects.create(name="Aaroham", slug="aaroham")
    return create_branch(organization=org, name="Main", slug="main")


@pytest.mark.parametrize("name", PUBLIC_PAGES)
def test_page_renders(client, branch, name):
    assert client.get(reverse(name)).status_code == 200


@pytest.mark.parametrize("name", PUBLIC_PAGES)
def test_page_renders_before_any_content_exists(client, name):
    """No Branch, no programmes, no settings — a fresh deploy must not 500.

    This is the state the site is in for the minutes between first boot and the seed
    command, and the state it returns to if someone deactivates the branch.
    """
    assert client.get(reverse(name)).status_code == 200


@pytest.mark.parametrize("name", PUBLIC_PAGES)
def test_page_carries_its_own_title_and_description(client, branch, name):
    content = client.get(reverse(name)).content
    assert b"<title>" in content
    assert b'name="description"' in content
    # A page that inherits the base title has forgotten to set its own.
    assert b"<title>Aaroham</title>" not in content


def test_programmes_appear_with_a_human_age_range(client, branch):
    Program.objects.create(
        branch=branch, name="Nursery", slug="nursery", age_from_months=30, age_to_months=42
    )
    content = client.get(reverse("programs")).content.decode()
    assert "Nursery" in content
    assert "2½–3½ years" in content  # parents think in years and half-years


def test_unpublished_content_stays_off_the_public_site(client, branch):
    Program.objects.create(
        branch=branch,
        name="Secret",
        slug="secret",
        age_from_months=12,
        age_to_months=24,
        is_published=False,
    )
    TeamMember.objects.create(branch=branch, name="Draft Person", is_published=False)
    assert b"Secret" not in client.get(reverse("programs")).content
    assert b"Draft Person" not in client.get(reverse("team")).content


def test_testimonials_are_off_until_a_real_parent_says_something(client, branch):
    """Default is unpublished on purpose — inventing parent quotes would be bad to ship."""
    t = Testimonial.objects.create(branch=branch, quote="Lovely place", author_name="A Parent")
    assert t.is_published is False
    assert b"Lovely place" not in client.get(reverse("home")).content


def test_enquiries_are_never_exposed_on_a_public_page(client, branch):
    """Nothing a parent submitted may leak onto an unauthenticated page.

    The name is a deliberate sentinel rather than something plausible: the contact
    form uses a realistic placeholder, and a test asserting on a common name would
    match that instead of a real leak and pass for the wrong reason.
    """
    sentinel = "Zzqx-Leak-Canary-8823"
    Enquiry.objects.create(branch=branch, guardian_name=sentinel, phone="9876543210")
    for name in PUBLIC_PAGES:
        assert sentinel.encode() not in client.get(reverse(name)).content


def test_contact_page_shows_the_branch_details(client, branch):
    SiteSettings.objects.create(branch=branch, phone="080 1234 5678", email="hello@aaroham.example")
    content = client.get(reverse("contact")).content
    assert b"080 1234 5678" in content
    assert b"hello@aaroham.example" in content


# --- SEO plumbing ------------------------------------------------------------------


def test_sitemap_lists_every_public_page(client, branch):
    content = client.get("/sitemap.xml").content.decode()
    assert content.count("<url>") == len(PUBLIC_PAGES)
    for name in PUBLIC_PAGES:
        assert reverse(name) in content


def test_robots_points_at_the_sitemap_and_hides_private_areas(client):
    content = client.get("/robots.txt").content.decode()
    assert "Sitemap:" in content
    assert "sitemap.xml" in content
    for private in ("/admin/", "/staff/", "/portal/"):
        assert f"Disallow: {private}" in content
