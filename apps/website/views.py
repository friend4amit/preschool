"""Public site controllers.

Each one parses a request, asks a selector or calls one service, and picks a template.
No ORM, no business rules — `lint-imports` and test_architecture.py both check.
"""

from django.conf import settings
from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from apps.website import selectors, services
from apps.website.forms import EnquiryForm
from apps.website.models import ImagePlacement
from integrations import turnstile


def _page_context(request: HttpRequest) -> dict:
    """Everything the shared layout needs: settings for the footer, programs for the nav."""
    branch = selectors.current_branch()
    return {
        "branch": branch,
        "site": selectors.site_settings_for(branch),
        "programs": selectors.published_programs(branch),
    }


def home(request: HttpRequest) -> HttpResponse:
    context = _page_context(request)
    branch = context["branch"]
    context["testimonials"] = selectors.published_testimonials(branch)
    context["gallery"] = selectors.published_gallery(branch)
    context["stats"] = selectors.published_stats(branch)
    return render(request, "website/pages/home.html", context)


def about(request: HttpRequest) -> HttpResponse:
    context = _page_context(request)
    context["photo"] = selectors.image_for(context["branch"], ImagePlacement.ABOUT)
    return render(request, "website/pages/about.html", context)


def approach(request: HttpRequest) -> HttpResponse:
    """Three traditions, three photographs. Materials and hands rather than faces —
    which is what docs/plan.md says a preschool site actually needs, and what carries
    no consent question at all."""
    context = _page_context(request)
    context["photos"] = {
        key: selectors.image_for(context["branch"], key)
        for key in (
            ImagePlacement.APPROACH_PLAY,
            ImagePlacement.APPROACH_HANDS,
            ImagePlacement.APPROACH_VALUES,
        )
    }
    return render(request, "website/pages/approach.html", context)


def programs(request: HttpRequest) -> HttpResponse:
    return render(request, "website/pages/programs.html", _page_context(request))


def team(request: HttpRequest) -> HttpResponse:
    context = _page_context(request)
    context["team"] = selectors.published_team(context["branch"])
    context["photo"] = selectors.image_for(context["branch"], ImagePlacement.TEAM)
    return render(request, "website/pages/team.html", context)


def special_education(request: HttpRequest) -> HttpResponse:
    context = _page_context(request)
    context["photo"] = selectors.image_for(context["branch"], ImagePlacement.INCLUSION)
    return render(request, "website/pages/special_education.html", context)


@require_http_methods(["GET", "POST"])
def contact(request: HttpRequest) -> HttpResponse:
    context = _page_context(request)
    form = EnquiryForm(request.POST or None, programs=context["programs"])

    if request.method == "POST" and form.is_valid() and _passes_turnstile(request):
        services.create_enquiry(branch=context["branch"], **_enquiry_fields(form))
        messages.success(request, "Thank you — we have your enquiry and will call you shortly.")
        return redirect(f"{reverse('contact')}?sent=1")

    if request.method == "POST" and form.is_valid():
        form.add_error(None, "We couldn't verify that you're human. Please try again.")

    context["form"] = form
    context["turnstile_site_key"] = settings.TURNSTILE_SITE_KEY
    context["just_sent"] = request.GET.get("sent") == "1"
    return render(request, "website/pages/contact.html", context)


def _passes_turnstile(request: HttpRequest) -> bool:
    return turnstile.verify(
        request.POST.get("cf-turnstile-response", ""),
        remote_ip=request.META.get("REMOTE_ADDR"),
    )


def _enquiry_fields(form: EnquiryForm) -> dict:
    data = form.cleaned_data.copy()
    data.pop("website", None)  # honeypot, never stored
    return data


def robots_txt(request: HttpRequest) -> HttpResponse:
    lines = [
        "User-agent: *",
        "Allow: /",
        # Nothing behind a login should ever be indexed.
        "Disallow: /admin/",
        "Disallow: /staff/",
        "Disallow: /portal/",
        f"Sitemap: {request.build_absolute_uri('/sitemap.xml')}",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")
