"""Controllers. Parse the request, call one service or selector, pick a template.

If a view here grows past ~15 lines, or grows an `if` about business meaning, the
logic belongs a layer down. `lint-imports` enforces that these never reach past
services and selectors into the ORM.
"""

from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from apps.core import selectors, services
from apps.core.forms import PhoneAuthenticationForm, SetPasswordForm
from apps.core.models import Role

# Which console each role lands in. A dict rather than a chain of ifs, so adding a
# role is a line here and not a branch — and so the mapping is readable at a glance.
# Where each role lands after signing in. The two administrative roles go to the
# dashboard from Phase 7 onward — "the owner opens one screen each morning" is the
# whole point of that screen, and it is not one if they have to navigate to it.
# Teachers do NOT: their morning is a room and a register, and a school-wide
# attendance percentage is not a thing they can act on.
LANDING_BY_ROLE = {
    Role.SUPERADMIN: "dashboard",
    Role.BRANCH_ADMIN: "dashboard",
    Role.TEACHER: "student_list",
    Role.ACCOUNTANT: "student_list",
    Role.PARENT: "my_children",
}


def healthz(request: HttpRequest) -> HttpResponse:
    """Liveness for the container health check. Deliberately touches nothing."""
    return HttpResponse("ok", content_type="text/plain")


# --- the installable portal ------------------------------------------------------------
#
# Both of these are rendered rather than shipped as static files, and for the same
# reason: they name other static assets, and WhiteNoise's manifest storage hashes those
# names at collectstatic time. A hand-written `/static/css/app.css` in a service worker
# would 404 in production on the first deploy and never be noticed, because a worker
# that fails to install fails quietly.


def manifest(request: HttpRequest) -> HttpResponse:
    """The web app manifest. Served from the site root so its scope can be /portal/."""
    return render(
        request, "core/pwa/manifest.webmanifest", content_type="application/manifest+json"
    )


def service_worker(request: HttpRequest) -> HttpResponse:
    """The service worker, at the ROOT path deliberately.

    A worker's scope cannot be broader than the directory it is served from, so one
    at /static/sw.js could never control /portal/. This is the whole reason it is a
    view rather than a file.
    """
    response = render(request, "core/pwa/sw.js", content_type="text/javascript")
    # Browsers revalidate a worker at most every 24h by default; this asks for it
    # every time, so a deploy that changes the allowlist takes effect on the next
    # visit rather than tomorrow.
    response["Cache-Control"] = "no-cache"
    return response


def offline(request: HttpRequest) -> HttpResponse:
    """What a parent sees when they open the app with no signal. Cached by the worker,
    so it must not reference anything the worker has not also cached."""
    return render(request, "core/pages/offline.html")


class LoginView(auth_views.LoginView):
    template_name = "core/pages/login.html"
    authentication_form = PhoneAuthenticationForm
    redirect_authenticated_user = True


@login_required
def after_login(request: HttpRequest) -> HttpResponse:
    """Staff and parents share a login form and land in different places."""
    role = selectors.primary_role_for(request.user)
    return redirect(LANDING_BY_ROLE.get(role, "my_children"))


@require_http_methods(["GET", "POST"])
def set_password(request: HttpRequest, uid: str, token: str) -> HttpResponse:
    """The one-time link an admin hands over. No email anywhere in this flow."""
    user = services.resolve_set_password_token(uid, token)
    if user is None:
        return render(request, "core/pages/link_expired.html", status=410)

    form = SetPasswordForm(user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        services.set_password(user=user, raw_password=form.cleaned_data["new_password1"])
        return redirect(f"{reverse('login')}?password_set=1")

    return render(request, "core/pages/set_password.html", {"form": form, "account": user})
