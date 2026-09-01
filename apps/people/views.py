"""Staff console and parent portal controllers.

Every view here is a translator: parse the request, call one service or selector,
pick a template. The rules about who may see whom live in `selectors.py`; the rules
about what happens live in `services.py`. What is left is this file, and it should
stay boring.

One rule is worth stating rather than inferring. When a selector returns `None`
because the object belongs to another family or another branch, these views raise
`Http404` — never `PermissionDenied`. A 403 confirms the record exists, which tells
somebody guessing ids that they guessed right. See docs/plan.md.
"""

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.core import selectors as core_selectors
from apps.core import services as core_services
from apps.core.models import Role
from apps.people import forms, selectors, services
from apps.website import selectors as website_selectors
from apps.website import services as website_services

# A parent who reaches a staff URL is sent to the login page rather than shown a
# 403 — same reasoning as the 404s below: say as little as possible.
staff_required = user_passes_test(core_selectors.is_staff_member)


def _student_or_404(request: HttpRequest, student_id: int):
    student = selectors.student_detail_for_user(request.user, student_id)
    if student is None:
        raise Http404("No such student.")
    return student


# --- students -------------------------------------------------------------------------


@login_required
@staff_required
def student_list(request: HttpRequest) -> HttpResponse:
    """Search-as-you-type that is still a plain GET form underneath.

    htmx swaps the rows partial; with JavaScript off the same form submits normally
    and the full page re-renders. Nothing about the search lives in the JavaScript,
    which is what makes that true rather than aspirational.
    """
    form = forms.StudentSearchForm(
        request.GET or None, classrooms=core_selectors.classrooms_for_user(request.user)
    )
    filters = form.cleaned_data if form.is_valid() else {}
    students = selectors.search_students(
        request.user,
        query=filters.get("q") or "",
        classroom_id=filters.get("classroom"),
        status=filters.get("status") or "",
    )

    context = {"form": form, "students": students}
    if request.headers.get("HX-Request"):
        return render(request, "people/partials/student_rows.html", context)
    return render(request, "people/pages/student_list.html", context)


@login_required
@staff_required
def student_detail(request: HttpRequest, student_id: int) -> HttpResponse:
    student = _student_or_404(request, student_id)
    return render(
        request,
        "people/pages/student_detail.html",
        {
            "student": student,
            "guardian_links": selectors.guardians_for_student(student),
            "contacts": selectors.emergency_contacts_for(student),
            "enrollments": selectors.enrollment_history(student),
            "pickups": selectors.valid_pickups_for(student),
            "documents": selectors.documents_for_student(student),
            "open_enrollment": selectors.open_enrollment(student),
        },
    )


@login_required
@staff_required
def student_edit(request: HttpRequest, student_id: int) -> HttpResponse:
    student = _student_or_404(request, student_id)
    form = forms.StudentForm(request.POST or None, request.FILES or None, instance=student)

    if request.method == "POST" and form.is_valid():
        services.update_student(student=student, **form.cleaned_data)
        messages.success(request, f"{student.display_name}'s record is updated.")
        return redirect("student_detail", student_id=student.pk)

    return render(request, "people/pages/student_form.html", {"form": form, "student": student})


@login_required
@staff_required
def student_new(request: HttpRequest) -> HttpResponse:
    """A walk-in admission — the same screen as the enquiry conversion, without an
    enquiry behind it. Families do turn up at the gate."""
    branch = core_selectors.branches_for_user(request.user).first()
    if branch is None:
        raise Http404("No branch.")
    return _render_admission(request, branch=branch, enquiry=None)


# --- admissions: the one screen that both entry points share --------------------------


def _render_admission(request: HttpRequest, *, branch, enquiry) -> HttpResponse:
    """Shared by the walk-in and the enquiry conversion.

    Two views, one form, one service call each — the difference between them is
    which service closes the enquiry, and that is the only difference.
    """
    classrooms = core_selectors.classrooms_for_user(request.user).filter(branch=branch)
    years = core_selectors.academic_years_for_user(request.user).filter(branch=branch)
    initial = _admission_initial(enquiry, branch)

    form = forms.AdmissionForm(
        request.POST or None, classrooms=classrooms, years=years, initial=initial
    )
    consent_form = forms.ConsentForm(request.POST or None)

    if request.method == "POST" and form.is_valid() and consent_form.is_valid():
        student = _admit(request, branch=branch, enquiry=enquiry, form=form, consents=consent_form)
        messages.success(request, f"{student.display_name} is admitted.")
        return redirect("student_detail", student_id=student.pk)

    return render(
        request,
        "people/pages/admission_form.html",
        {"form": form, "consent_form": consent_form, "enquiry": enquiry, "branch": branch},
    )


def _admission_initial(enquiry, branch) -> dict:
    """Nothing typed on the public site gets typed again. That is the whole feature."""
    year = core_selectors.current_academic_year(branch)
    initial = {"academic_year": str(year.pk) if year else ""}
    if enquiry is not None:
        initial |= {
            "child_name": enquiry.child_name,
            "date_of_birth": enquiry.child_dob,
            "guardian_name": enquiry.guardian_name,
            "guardian_phone": enquiry.phone,
            "guardian_email": enquiry.email,
        }
    return initial


def _admit(request: HttpRequest, *, branch, enquiry, form, consents):
    fields = form.cleaned_data
    call = {
        "child_name": fields["child_name"],
        "date_of_birth": fields["date_of_birth"],
        "guardian_name": fields["guardian_name"],
        "guardian_phone": fields["guardian_phone"],
        "relationship": fields["relationship"],
        "classroom": _pick(core_selectors.classrooms_for_user(request.user), fields["classroom"]),
        "academic_year": _pick(
            core_selectors.academic_years_for_user(request.user), fields["academic_year"]
        ),
        "consents": consents.answers(),
        "open_portal_account": fields["open_portal_account"],
        "recorded_by": request.user,
        "preferred_name": fields["preferred_name"],
        "allergies": fields["allergies"],
    }
    if enquiry is not None:
        return website_services.convert_enquiry(enquiry=enquiry, **call)
    return services.admit_family(branch=branch, **call)


def _pick(queryset, pk):
    """Re-fetch through the scoped queryset rather than trusting the posted id.

    The select box was built from scoped choices, but a POST is not a select box —
    anyone can post any integer, and this is the line that makes that harmless.
    """
    return queryset.filter(pk=pk).first() if pk else None


# --- the admissions queue -------------------------------------------------------------


@login_required
@staff_required
def enquiry_list(request: HttpRequest) -> HttpResponse:
    """The staff side of the public contact form. Deferred out of Phase 1 to here,
    because a queue is only worth having once there is somewhere to convert into."""
    return render(
        request,
        "people/pages/enquiry_list.html",
        {"enquiries": website_selectors.open_enquiries_for_user(request.user)},
    )


@login_required
@staff_required
def enquiry_convert(request: HttpRequest, enquiry_id: int) -> HttpResponse:
    """The join between the two halves of the product."""
    enquiry = website_selectors.enquiry_detail_for_user(request.user, enquiry_id)
    if enquiry is None:
        raise Http404("No such enquiry.")
    return _render_admission(request, branch=enquiry.branch, enquiry=enquiry)


# --- guardians ------------------------------------------------------------------------


@login_required
@staff_required
def guardian_new(request: HttpRequest, student_id: int) -> HttpResponse:
    """Add a second guardian to a child. Split families are the normal case."""
    student = _student_or_404(request, student_id)
    form = forms.NewGuardianForm(request.POST or None)
    link_form = forms.LinkGuardianForm(
        guardians=selectors.unlinked_guardians_for(student, user=request.user)
    )

    if request.method == "POST" and form.is_valid():
        services.add_guardian_to_student(student=student, **form.cleaned_data)
        messages.success(request, "Guardian added.")
        return redirect("student_detail", student_id=student.pk)

    return render(
        request,
        "people/pages/guardian_form.html",
        {"form": form, "link_form": link_form, "student": student},
    )


@login_required
@staff_required
@require_POST
def guardian_link(request: HttpRequest, student_id: int) -> HttpResponse:
    """Attach an existing guardian to another child — how a sibling reaches a mother
    who is already on file, instead of creating a second family."""
    student = _student_or_404(request, student_id)
    form = forms.LinkGuardianForm(
        request.POST, guardians=selectors.unlinked_guardians_for(student, user=request.user)
    )
    if not form.is_valid():
        messages.error(request, "Pick a guardian and a relationship.")
        return redirect("guardian_new", student_id=student.pk)

    guardian = (
        selectors.guardians_for_user(request.user).filter(pk=form.cleaned_data["guardian"]).first()
    )
    if guardian is None:
        raise Http404("No such guardian.")

    services.link_guardian(
        student=student,
        guardian=guardian,
        relationship=form.cleaned_data["relationship"],
        is_primary=form.cleaned_data["is_primary"],
    )
    messages.success(request, f"{guardian.full_name} is now linked to {student.display_name}.")
    return redirect("student_detail", student_id=student.pk)


@login_required
@staff_required
def guardian_edit(request: HttpRequest, guardian_id: int) -> HttpResponse:
    guardian = selectors.guardian_detail_for_user(request.user, guardian_id)
    if guardian is None:
        raise Http404("No such guardian.")

    form = forms.GuardianForm(request.POST or None, instance=guardian)
    if request.method == "POST" and form.is_valid():
        services.update_guardian(guardian=guardian, **form.cleaned_data)
        messages.success(request, "Guardian updated.")
        return redirect("guardian_edit", guardian_id=guardian.pk)

    return render(
        request,
        "people/pages/guardian_edit.html",
        {"form": form, "guardian": guardian, "children": selectors.children_of_guardian(guardian)},
    )


@login_required
@staff_required
@require_POST
def guardian_account(request: HttpRequest, guardian_id: int) -> HttpResponse:
    """Create the login and show the link once, on screen, for the admin to hand over.

    The link is never emailed and never stored — it is a credential, and the whole
    point of a one-time link is that it exists for as long as it takes to pass it on.
    """
    guardian = selectors.guardian_detail_for_user(request.user, guardian_id)
    if guardian is None:
        raise Http404("No such guardian.")

    account = services.create_portal_account(guardian=guardian)
    return render(
        request,
        "people/pages/account_link.html",
        {"account": account, "link": _set_password_link(request, account), "guardian": guardian},
    )


def _set_password_link(request: HttpRequest, account) -> str:
    uid, token = core_services.issue_set_password_token(account)
    return request.build_absolute_uri(reverse("set_password", kwargs={"uid": uid, "token": token}))


# --- emergency contacts and enrolment -------------------------------------------------


@login_required
@staff_required
def emergency_contact_add(request: HttpRequest, student_id: int) -> HttpResponse:
    student = _student_or_404(request, student_id)
    form = forms.EmergencyContactForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        services.add_emergency_contact(student=student, **form.cleaned_data)
        messages.success(request, "Emergency contact added.")
        return redirect("student_detail", student_id=student.pk)

    return render(
        request, "people/pages/emergency_contact_form.html", {"form": form, "student": student}
    )


@login_required
@staff_required
def enrollment_change(request: HttpRequest, student_id: int) -> HttpResponse:
    """Place or move a child. The service closes the old row rather than editing it."""
    student = _student_or_404(request, student_id)
    classrooms = core_selectors.classrooms_for_user(request.user).filter(branch=student.branch)
    years = core_selectors.academic_years_for_user(request.user).filter(branch=student.branch)
    form = forms.EnrollmentForm(request.POST or None, classrooms=classrooms, years=years)

    if request.method == "POST" and form.is_valid():
        services.enroll_student(
            student=student,
            classroom=_pick(classrooms, form.cleaned_data["classroom"]),
            academic_year=_pick(years, form.cleaned_data["academic_year"]),
        )
        messages.success(request, f"{student.display_name} is enrolled.")
        return redirect("student_detail", student_id=student.pk)

    return render(request, "people/pages/enrollment_form.html", {"form": form, "student": student})


# --- staff ----------------------------------------------------------------------------


@login_required
@staff_required
def staff_list(request: HttpRequest) -> HttpResponse:
    return render(
        request, "people/pages/staff_list.html", {"staff": selectors.staff_for_user(request.user)}
    )


@login_required
@staff_required
def staff_detail(request: HttpRequest, staff_id: int) -> HttpResponse:
    member = selectors.staff_detail_for_user(request.user, staff_id)
    if member is None:
        raise Http404("No such staff member.")

    form = forms.StaffForm(request.POST or None, instance=member)
    if request.method == "POST" and form.is_valid():
        services.update_staff_profile(staff=member, **form.cleaned_data)
        messages.success(request, "Profile updated.")
        return redirect("staff_detail", staff_id=member.pk)

    return render(request, "people/pages/staff_detail.html", {"member": member, "form": form})


@login_required
@staff_required
def staff_new(request: HttpRequest) -> HttpResponse:
    """Create a teacher's account and profile together, and show the link to hand over.

    One account system: this is the same `User` a parent gets, with a different
    BranchMembership role. There is no second identity table.
    """
    branch = core_selectors.branches_for_user(request.user).first()
    if branch is None:
        raise Http404("No branch.")

    form = forms.AccountForm(request.POST or None, roles=STAFF_ROLE_CHOICES)
    if request.method == "POST" and form.is_valid():
        member = services.onboard_staff(branch=branch, **form.cleaned_data)
        return render(
            request,
            "people/pages/account_link.html",
            {
                "account": member.user,
                "link": _set_password_link(request, member.user),
                "member": member,
            },
        )

    return render(request, "people/pages/staff_form.html", {"form": form})


STAFF_ROLE_CHOICES = [
    (Role.TEACHER, Role.TEACHER.label),
    (Role.BRANCH_ADMIN, Role.BRANCH_ADMIN.label),
    (Role.ACCOUNTANT, Role.ACCOUNTANT.label),
]


# --- parent portal --------------------------------------------------------------------


@login_required
def my_children(request: HttpRequest) -> HttpResponse:
    """The portal's front door. `children_of` is the guardian link and nothing else —
    a teacher opening this sees their own children, not their class."""
    return render(
        request, "people/pages/my_children.html", {"children": selectors.children_of(request.user)}
    )


@login_required
def child_detail(request: HttpRequest, student_id: int) -> HttpResponse:
    """A stub until Phase 4 fills it with the activity feed.

    Scoped through `children_of`, not `students_for_user`: this page is the parent's
    view of their own child, and a teacher reaching it should see it as a parent or
    not at all.
    """
    child = selectors.children_of(request.user).filter(pk=student_id).first()
    if child is None:
        raise Http404("No such child.")
    return render(request, "people/pages/child_detail.html", {"child": child})
