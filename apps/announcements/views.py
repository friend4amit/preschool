"""The staff notice board, and the parent's side of it.

Each view parses a request, calls one service or selector, and picks a template. Who
may see which notice lives in `selectors.py`; what publishing means lives in
`services.py`.

The 404 rule from docs/plan.md applies here as everywhere: a selector returning None
becomes `Http404`, never `PermissionDenied`. A 403 on an id a parent is not entitled
to confirms the notice exists.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.announcements import forms, selectors, services
from apps.core import selectors as core_selectors

staff_required = user_passes_test(core_selectors.is_staff_member)


def _announcement_or_404(request: HttpRequest, announcement_id: int):
    found = selectors.staff_detail(request.user, announcement_id)
    if found is None:
        raise Http404("No such notice.")
    return found


@login_required
@staff_required
def announcement_list(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "announcements/pages/list.html",
        {"announcements": selectors.for_user(request.user)},
    )


@login_required
@staff_required
def announcement_new(request: HttpRequest) -> HttpResponse:
    rooms = core_selectors.classrooms_for_user(request.user)
    form = forms.AnnouncementForm(request.POST or None, classrooms=rooms)
    if request.method == "POST" and form.is_valid():
        room = form.classroom
        branch = room.branch if room else core_selectors.current_branch_fallback()
        try:
            services.create_announcement(
                branch=branch,
                title=form.cleaned_data["title"],
                body=form.cleaned_data["body"],
                classroom=room,
                is_school_wide=form.is_school_wide,
                is_pinned=form.cleaned_data["is_pinned"],
                expires_on=form.cleaned_data["expires_on"],
                author=request.user,
            )
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, "Saved as a draft. Publish it when it is ready.")
            return redirect("announcement_list")
    return render(request, "announcements/pages/form.html", {"form": form})


@login_required
@staff_required
def announcement_detail(request: HttpRequest, announcement_id: int) -> HttpResponse:
    announcement = _announcement_or_404(request, announcement_id)
    return render(
        request,
        "announcements/pages/detail.html",
        {
            "announcement": announcement,
            "read_count": selectors.read_count(announcement),
            "audience_size": selectors.audience_size(announcement),
        },
    )


@login_required
@staff_required
@require_POST
def announcement_publish(request: HttpRequest, announcement_id: int) -> HttpResponse:
    announcement = _announcement_or_404(request, announcement_id)
    services.publish(announcement)
    messages.success(request, "Published. Parents will see it on their next visit.")
    return redirect("announcement_detail", announcement_id=announcement.pk)


@login_required
@staff_required
@require_POST
def announcement_unpublish(request: HttpRequest, announcement_id: int) -> HttpResponse:
    announcement = _announcement_or_404(request, announcement_id)
    services.unpublish(announcement)
    messages.success(request, "Withdrawn. Who had already read it is still on record.")
    return redirect("announcement_detail", announcement_id=announcement.pk)


# --------------------------------------------------------------------------------
# Parent portal
# --------------------------------------------------------------------------------


@login_required
def my_announcements(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "announcements/pages/portal_list.html",
        {"announcements": selectors.feed_for(request.user)},
    )


@login_required
def my_announcement(request: HttpRequest, announcement_id: int) -> HttpResponse:
    """Open one notice, and record that this guardian did.

    The receipt is written on the detail view rather than on the list, and that is
    the whole reason a detail view exists. "It appeared in a list they scrolled past"
    is not the same claim as "they opened it", and the receipt is only worth keeping
    if it means the second one.
    """
    announcement = selectors.detail_for(request.user, announcement_id)
    if announcement is None:
        raise Http404("No such notice.")
    services.mark_read(announcement=announcement, guardian=request.user)
    return render(request, "announcements/pages/portal_detail.html", {"announcement": announcement})
