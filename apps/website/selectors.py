"""Reads for the public site and the staff enquiry list.

The public pages are unauthenticated, so most of these take a Branch rather than a
User — but `enquiries_for_user` is staff-facing and scopes the same way everything
else does.
"""

from django.db.models import QuerySet

from apps.core.models import Branch, User
from apps.core.selectors import branches_for_user
from apps.website.models import Enquiry, Program, SiteSettings, TeamMember, Testimonial


def current_branch() -> Branch | None:
    """The branch the public site speaks for.

    One row exists until phase 8, so this is the whole of "which branch is this page
    about". When the switcher arrives it becomes a lookup on host or URL prefix, and
    every caller below is already asking the question rather than assuming.
    """
    return Branch.objects.filter(is_active=True).order_by("pk").first()


def site_settings_for(branch: Branch | None) -> SiteSettings | None:
    if branch is None:
        return None
    return SiteSettings.objects.filter(branch=branch).first()


def published_programs(branch: Branch | None) -> QuerySet[Program]:
    if branch is None:
        return Program.objects.none()
    return Program.objects.published().filter(branch=branch)


def published_team(branch: Branch | None) -> QuerySet[TeamMember]:
    if branch is None:
        return TeamMember.objects.none()
    return TeamMember.objects.published().filter(branch=branch)


def published_testimonials(branch: Branch | None) -> QuerySet[Testimonial]:
    """Empty until a real parent says a real thing — see the model docstring."""
    if branch is None:
        return Testimonial.objects.none()
    return Testimonial.objects.published().filter(branch=branch)


def enquiries_for_user(user: User) -> QuerySet[Enquiry]:
    return (
        Enquiry.objects.filter(branch__in=branches_for_user(user))
        .select_related("program", "branch")
        .order_by("-created_at")
    )
