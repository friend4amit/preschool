"""The register, the door, and a parent's month.

Every view parses a request, calls one service or selector, and picks a template.
The rules about who may mark whom live in `selectors.py`; the rules about what a mark
means live in `services.py`.

Two things worth stating rather than inferring:

1. A selector returning None becomes `Http404`, never `PermissionDenied`. A 403 tells
   somebody walking ids that they guessed a real child. See docs/plan.md.
2. Every marking action is a real form POST that redirects. htmx swaps a single row
   when it is present, and with JavaScript off the same button submits and the page
   re-renders — which matters here more than anywhere, because this screen is used
   one-handed on a phone on school wifi.
"""

from datetime import date as date_type

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.attendance import forms, selectors, services
from apps.attendance.models import AttendanceStatus
from apps.core import selectors as core_selectors
from apps.people import selectors as people_selectors

staff_required = user_passes_test(core_selectors.is_staff_member)


def _day_from(request: HttpRequest) -> date_type:
    """The date being marked. Today unless the query string says otherwise, and today
    again if it says something that is not a date — a mistyped URL should show the
    register, not a stack trace."""
    raw = request.GET.get("date") or request.POST.get("date") or ""
    try:
        return date_type.fromisoformat(raw)
    except ValueError:
        return timezone.localdate()


def _room_or_404(request: HttpRequest, classroom_id: int):
    room = selectors.classroom_for_user(request.user, classroom_id)
    if room is None:
        raise Http404("No such classroom.")
    return room


def _record_or_404(request: HttpRequest, record_id: int):
    record = selectors.records_for_user(request.user).filter(pk=record_id).first()
    if record is None:
        raise Http404("No such attendance record.")
    return record


# --- the grid ---------------------------------------------------------------------------


@login_required
@staff_required
def today(request: HttpRequest) -> HttpResponse:
    """Straight into a room. A teacher opening this has one room and one question."""
    room = core_selectors.classrooms_for_user(request.user).first()
    if room is None:
        raise Http404("No classroom.")
    return redirect("attendance_day", classroom_id=room.pk)


@login_required
@staff_required
def day(request: HttpRequest, classroom_id: int) -> HttpResponse:
    room = _room_or_404(request, classroom_id)
    marking = _day_from(request)
    return render(
        request,
        "attendance/pages/day.html",
        {
            "room": room,
            "day": marking,
            "is_today": marking == timezone.localdate(),
            "rows": selectors.day_sheet(room, marking, user=request.user),
            "unmarked": selectors.unmarked_count(room, marking, user=request.user),
            "rooms": core_selectors.classrooms_for_user(request.user),
            "recent": selectors.recent_days(timezone.localdate()),
            "statuses": AttendanceStatus.choices,
        },
    )


@login_required
@staff_required
@require_POST
def mark(request: HttpRequest, classroom_id: int, student_id: int) -> HttpResponse:
    """One tap. Returns just the row to htmx, or bounces back to the grid without."""
    room = _room_or_404(request, classroom_id)
    student = people_selectors.students_for_user(request.user).filter(pk=student_id).first()
    if student is None:
        raise Http404("No such student.")

    marking = _day_from(request)
    form = forms.MarkForm(request.POST)
    if form.is_valid():
        services.mark(
            student=student,
            day=marking,
            classroom=room,
            marked_by=request.user,
            **form.cleaned_data,
        )
    return _row_or_redirect(request, room, student, marking)


@login_required
@staff_required
@require_POST
def all_present(request: HttpRequest, classroom_id: int) -> HttpResponse:
    """The one-tap start of a morning."""
    room = _room_or_404(request, classroom_id)
    marking = _day_from(request)
    written = services.mark_all_present(
        classroom=room,
        students=list(people_selectors.roster(room.pk, user=request.user)),
        day=marking,
        marked_by=request.user,
    )
    messages.success(request, f"{written} marked present. Correct the exceptions below.")
    return redirect(f"{_day_url(room, marking)}")


@login_required
@staff_required
def detail(request: HttpRequest, classroom_id: int, student_id: int) -> HttpResponse:
    """The slower path: a late arrival with a time, or an absence with a reason."""
    room = _room_or_404(request, classroom_id)
    student = people_selectors.students_for_user(request.user).filter(pk=student_id).first()
    if student is None:
        raise Http404("No such student.")

    marking = _day_from(request)
    existing = (
        selectors.records_for_user(request.user).filter(student=student, date=marking).first()
    )
    form = forms.DetailForm(request.POST or None, initial=_initial_from(existing))

    if request.method == "POST" and form.is_valid():
        services.mark(
            student=student,
            day=marking,
            classroom=room,
            marked_by=request.user,
            **form.cleaned_data,
        )
        messages.success(request, f"{student.display_name} updated.")
        return redirect(_day_url(room, marking))

    return render(
        request,
        "attendance/pages/detail.html",
        {"form": form, "student": student, "room": room, "day": marking, "record": existing},
    )


# --- the door ---------------------------------------------------------------------------


@login_required
@staff_required
def pickup(request: HttpRequest, record_id: int) -> HttpResponse:
    """Who collected the child. The screen where Phase 2's safety records earn their keep."""
    record = _record_or_404(request, record_id)
    pickups = people_selectors.valid_pickups_for(record.student, on=record.date)
    guardians = [link.guardian for link in people_selectors.guardians_for_student(record.student)]
    form = forms.PickupForm(request.POST or None, pickups=pickups, guardians=guardians)

    if request.method == "POST" and form.is_valid():
        error = _release(request, record, form, pickups, guardians)
        if error is None:
            messages.success(request, f"{record.student.display_name} released.")
            return redirect(_day_url(record.classroom, record.date))
        form.add_error(None, error)

    return render(
        request,
        "attendance/pages/pickup.html",
        {"form": form, "record": record, "pickups": pickups, "guardians": guardians},
    )


# --- reports ----------------------------------------------------------------------------


@login_required
@staff_required
def report(request: HttpRequest, classroom_id: int) -> HttpResponse:
    room = _room_or_404(request, classroom_id)
    today_ = timezone.localdate()
    year = _int_or(request.GET.get("year"), today_.year)
    month = _int_or(request.GET.get("month"), today_.month)
    return render(
        request,
        "attendance/pages/report.html",
        {
            "room": room,
            "year": year,
            "month": month,
            "rows": selectors.classroom_month_report(room, year, month, user=request.user),
        },
    )


@login_required
def my_child_attendance(request: HttpRequest, student_id: int) -> HttpResponse:
    """A parent's calendar. Scoped through `children_of`, so a teacher reaching it
    sees it as a parent or not at all."""
    today_ = timezone.localdate()
    year = _int_or(request.GET.get("year"), today_.year)
    month = _int_or(request.GET.get("month"), today_.month)

    child, records = selectors.month_for_child_of(request.user, student_id, year, month)
    if child is None:
        raise Http404("No such child.")

    return render(
        request,
        "attendance/pages/child_month.html",
        {
            "child": child,
            "records": records,
            "year": year,
            "month": month,
            "summary": selectors.student_month_summary(child, year, month),
        },
    )


# --- helpers ----------------------------------------------------------------------------


def _day_url(room, marking: date_type) -> str:
    from django.urls import reverse

    return f"{reverse('attendance_day', kwargs={'classroom_id': room.pk})}?date={marking}"


def _row_or_redirect(request, room, student, marking):
    """htmx gets the one row it asked about; everyone else gets the page back."""
    if request.headers.get("HX-Request"):
        rows = [
            r
            for r in selectors.day_sheet(room, marking, user=request.user)
            if r["student"].pk == student.pk
        ]
        return render(
            request,
            "attendance/partials/row.html",
            {"row": rows[0], "room": room, "day": marking, "statuses": AttendanceStatus.choices},
        )
    return redirect(_day_url(room, marking))


def _initial_from(record) -> dict:
    if record is None:
        return {"status": AttendanceStatus.PRESENT}
    return {
        "status": record.status,
        "arrived_at": record.arrived_at,
        "left_at": record.left_at,
        "reason": record.reason,
    }


def _release(request, record, form, pickups, guardians) -> str | None:
    """Returns an error message, or None. Re-fetches the chosen person through the
    scoped lists rather than trusting the posted id — the select box was built from
    scoped choices, but a POST is not a select box."""
    choice = form.cleaned_data["collected_by"]
    try:
        if choice == forms.PickupForm.OVERRIDE:
            services.release_with_override(
                record=record,
                name=form.cleaned_data["override_name"],
                reason=form.cleaned_data["override_reason"],
                released_by=request.user,
            )
        elif choice.startswith("guardian:"):
            who = _pick(guardians, choice.split(":", 1)[1])
            services.release_to_guardian(record=record, guardian=who, released_by=request.user)
        else:
            who = _pick(pickups, choice.split(":", 1)[1])
            services.release_to_authorized(record=record, pickup=who, released_by=request.user)
    except (ValueError, LookupError) as refused:
        return str(refused)
    return None


def _pick(candidates, raw_id: str):
    for candidate in candidates:
        if str(candidate.pk) == raw_id:
            return candidate
    raise LookupError("That person is not on this child's list.")


def _int_or(raw, fallback: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return fallback
