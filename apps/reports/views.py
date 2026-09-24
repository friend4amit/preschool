"""The owner's morning screen, and the files the office downloads.

Each view parses a request, calls one selector or service, and picks a template or
wraps a string in a response. The scoping is in `selectors.py` and the CSV text is
built in `services.py`, which is what keeps these short enough to read.

An export is a screen that saves to disk, so it obeys the same two rules as one: it is
scoped through `students_for_user`, and an id this user is not entitled to becomes a
404 rather than a 403.
"""

from datetime import date as date_type

from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from apps.announcements import selectors as announcement_selectors
from apps.core import selectors as core_selectors
from apps.reports import selectors, services

staff_required = user_passes_test(core_selectors.is_staff_member)


def _csv_response(text: str, filename: str) -> HttpResponse:
    """A CSV the browser saves rather than renders.

    `text/csv; charset=utf-8` with a BOM. The BOM is not decoration: without it Excel
    on Windows reads a UTF-8 CSV as the system codepage, and every name with a Devanagari
    character or a curly apostrophe comes out as mojibake. The school opens these in
    Excel, so the file is written for Excel.
    """
    response = HttpResponse(text.encode("utf-8-sig"), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _month_from(request: HttpRequest) -> tuple[int, int]:
    """The month being reported on, from `?month=YYYY-MM`. This month if absent or
    unparseable — the same forgiving read `activities.views._day_from` does."""
    today = timezone.localdate()
    raw = request.GET.get("month") or ""
    try:
        parsed = date_type.fromisoformat(f"{raw}-01")
    except ValueError:
        return today.year, today.month
    return parsed.year, parsed.month


def _classroom_or_404(request: HttpRequest, classroom_id: int):
    room = selectors.classroom_for_user(request.user, classroom_id)
    if room is None:
        raise Http404("No such classroom.")
    return room


@login_required
@staff_required
def dashboard(request: HttpRequest) -> HttpResponse:
    """One screen, read once a morning.

    Deliberately not configurable and deliberately not paginated. The whole value is
    that the same numbers are in the same places every day, so the owner reads it in
    ten seconds instead of studying it.
    """
    return render(
        request,
        "reports/pages/dashboard.html",
        {
            "attendance": selectors.attendance_today(request.user),
            "absent": selectors.absent_today(request.user),
            "enrolled": selectors.enrolled_count(request.user),
            "enquiries": selectors.new_enquiries(request.user),
            "photos": selectors.recent_photo_activity(request.user),
            "trend": selectors.enrolment_trend(request.user),
            "announcements": announcement_selectors.for_user(request.user).filter(
                is_published=True
            )[:3],
            "classrooms": core_selectors.classrooms_for_user(request.user),
        },
    )


@login_required
@staff_required
def report_index(request: HttpRequest) -> HttpResponse:
    return render(
        request,
        "reports/pages/index.html",
        {"classrooms": core_selectors.classrooms_for_user(request.user)},
    )


@login_required
@staff_required
def roster_csv(request: HttpRequest) -> HttpResponse:
    room = None
    if request.GET.get("classroom"):
        try:
            room = _classroom_or_404(request, int(request.GET["classroom"]))
        except ValueError as exc:
            raise Http404("No such classroom.") from exc

    rows = selectors.roster_rows(request.user, classroom=room)
    stamp = timezone.localdate().isoformat()
    where = f"-{room.name.lower().replace(' ', '-')}" if room else ""
    return _csv_response(services.roster_csv(rows), f"roster{where}-{stamp}.csv")


@login_required
@staff_required
def attendance_csv(request: HttpRequest, classroom_id: int) -> HttpResponse:
    room = _classroom_or_404(request, classroom_id)
    year, month = _month_from(request)
    rows = selectors.month_register(request.user, room, year, month)
    return _csv_response(
        services.attendance_summary_csv(rows, year, month),
        f"attendance-{room.name.lower().replace(' ', '-')}-{year}-{month:02d}.csv",
    )


@login_required
@staff_required
def attendance_register(request: HttpRequest, classroom_id: int) -> HttpResponse:
    """The month register, laid out for A4 and a printer.

    Its own template rather than a print stylesheet on the staff console: the register
    a school files is a grid with a signature line, and nothing else on the page. See
    `templates/reports/pages/register.html`.
    """
    room = _classroom_or_404(request, classroom_id)
    year, month = _month_from(request)
    days = selectors.month_days(year, month)
    rows = selectors.month_register(request.user, room, year, month)
    return render(
        request,
        "reports/pages/register.html",
        {
            "classroom": room,
            "month": date_type(year, month, 1),
            "days": days,
            "rows": services.register_grid(rows, days),
            "marks": services.REGISTER_MARKS,
        },
    )
