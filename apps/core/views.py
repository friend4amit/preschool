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
LANDING_BY_ROLE = {
    Role.SUPERADMIN: "student_list",
    Role.BRANCH_ADMIN: "student_list",
    Role.TEACHER: "student_list",
    Role.ACCOUNTANT: "student_list",
    Role.PARENT: "my_children",
}


def healthz(request: HttpRequest) -> HttpResponse:
    """Liveness for the container health check. Deliberately touches nothing."""
    return HttpResponse("ok", content_type="text/plain")


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
