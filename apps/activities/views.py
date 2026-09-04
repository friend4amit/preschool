"""The teacher's day, the tagging screen, and a parent's feed.

Every view parses a request, calls one service or selector, and picks a template. Who
may see whose child lives in `selectors.py`; what a publish means lives in
`services.py`.

Three things worth stating rather than inferring:

1. A selector returning None becomes `Http404`, never `PermissionDenied`. A 403 tells
   somebody walking ids that they guessed a real child. See docs/plan.md.
2. Publication refusals are the exception: `services.publish_media` raises with the
   blocking child's name, and that message is shown. The teacher already knows the
   child is in their room — what they need is which consent is missing.
3. Photographs never reach a template as a bare key. `selectors.media_url` issues a
   short-lived presigned GET, and where R2 is unconfigured `media_file` streams the
   bytes through the same gate instead.
"""

from datetime import date as date_type

from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.http import FileResponse, Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.activities import forms, selectors, services
from apps.activities.models import ActivityKind
from apps.core import selectors as core_selectors
from apps.people import selectors as people_selectors

staff_required = user_passes_test(core_selectors.is_staff_member)


def _day_from(request: HttpRequest) -> date_type:
    """The day being written up. Today unless the query string says otherwise, and
    today again if it says something that is not a date."""
    raw = request.GET.get("date") or request.POST.get("date") or ""
    try:
        return date_type.fromisoformat(raw)
    except ValueError:
        return timezone.localdate()


def _room_or_404(request: HttpRequest, classroom_id: int):
    room = core_selectors.classrooms_for_user(request.user).filter(pk=classroom_id).first()
    if room is None:
        raise Http404("No such classroom.")
    return room


def _student_or_404(request: HttpRequest, student_id: int):
    student = people_selectors.students_for_user(request.user).filter(pk=student_id).first()
    if student is None:
        raise Http404("No such student.")
    return student


def _media_or_404(request: HttpRequest, media_id: int):
    media = selectors.media_for_staff(request.user, media_id)
    if media is None:
        raise Http404("No such photo.")
    return media


def _day_url(room, day: date_type) -> str:
    return f"{reverse('activities_day', kwargs={'classroom_id': room.pk})}?date={day}"


# --- the teacher's day ------------------------------------------------------------------


@login_required
@staff_required
def today(request: HttpRequest) -> HttpResponse:
    """Straight into a room, the way the register does."""
    room = core_selectors.classrooms_for_user(request.user).first()
    if room is None:
        raise Http404("No classroom.")
    return redirect("activities_day", classroom_id=room.pk)


@login_required
@staff_required
def day(request: HttpRequest, classroom_id: int) -> HttpResponse:
    """Everything written and photographed in one room on one day, staged.

    Both halves on one screen because they are published together — a teacher who has
    to remember a second page is a teacher who publishes the notes and forgets the
    photos.
    """
    room = _room_or_404(request, classroom_id)
    writing = _day_from(request)
    photos = list(selectors.media_for_room_on(room, writing, user=request.user))
    ready, blocked = services.publishable_among(photos)

    return render(
        request,
        "activities/pages/day.html",
        {
            "room": room,
            "day": writing,
            "is_today": writing == timezone.localdate(),
            "rooms": core_selectors.classrooms_for_user(request.user),
            "roster": people_selectors.roster(room.pk, user=request.user),
            "entries": selectors.entries_for_room_on(room, writing, user=request.user),
            "photos": [{"media": m, "url": selectors.media_url(m)} for m in photos],
            "ready_count": len(ready),
            "blocked_count": len(blocked),
            "kinds": ActivityKind.choices,
            "form": forms.EntryForm(),
        },
    )


@login_required
@staff_required
@require_POST
def quick_entry(request: HttpRequest, classroom_id: int) -> HttpResponse:
    """The fast path: one kind, against the whole room or one child.

    A student id of 0 means the room. The bulk path writes ONE classroom row rather
    than thirty student rows — the reasoning is in services.record_for_classroom.
    """
    room = _room_or_404(request, classroom_id)
    writing = _day_from(request)
    form = forms.QuickEntryForm(request.POST)
    if not form.is_valid():
        messages.error(request, "That is not something we can record.")
        return redirect(_day_url(room, writing))

    occurred = _occurred_on(writing)
    # Not `int(...)` bare: a malformed POST is a mistake, not a crash, and a teacher
    # meeting a 500 on a phone has no idea the field was the problem.
    raw = request.POST.get("student", "0")
    try:
        student_id = int(raw or 0)
    except ValueError:
        messages.error(request, "That is not a child we know about.")
        return redirect(_day_url(room, writing))

    if not student_id:
        services.record_for_classroom(
            classroom=room, occurred_at=occurred, author=request.user, **form.cleaned_data
        )
        messages.success(request, f"Recorded for the whole of {room.name}.")
    else:
        student = _student_or_404(request, student_id)
        services.record_entry(
            branch=room.branch,
            student=student,
            occurred_at=occurred,
            author=request.user,
            **form.cleaned_data,
        )
        messages.success(request, f"Recorded for {student.display_name}.")
    return redirect(_day_url(room, writing))


@login_required
@staff_required
@require_POST
def publish_day(request: HttpRequest, classroom_id: int) -> HttpResponse:
    """Publish the staged day in one action — notes and photographs together.

    Photographs whose consent is incomplete are left as drafts rather than failing the
    whole publish, and the count is reported. The teacher has already seen which ones
    and why on the screen they pressed this from; stopping the whole day on one
    missing consent would strand the other twenty.
    """
    room = _room_or_404(request, classroom_id)
    writing = _day_from(request)

    entries = list(selectors.entries_for_room_on(room, writing, user=request.user))
    written = services.publish_entries(entries=entries)

    photos = list(selectors.media_for_room_on(room, writing, user=request.user))
    ready, blocked = services.publishable_among(photos)
    for asset in ready:
        services.publish_media(media=asset)

    messages.success(
        request,
        f"Published {written} note{'' if written == 1 else 's'} "
        f"and {len(ready)} photo{'' if len(ready) == 1 else 's'}.",
    )
    if blocked:
        names = ", ".join(
            child.display_name for asset in blocked for child in selectors.blocked_tags(asset)
        )
        messages.warning(
            request,
            f"{len(blocked)} photo{'' if len(blocked) == 1 else 's'} held back — "
            f"no sharing consent on record for {names}.",
        )
    return redirect(_day_url(room, writing))


# --- tagging ----------------------------------------------------------------------------


@login_required
@staff_required
def tag_photo(request: HttpRequest, media_id: int) -> HttpResponse:
    """Who is in this photograph, with the consent state shown beside each name."""
    media = _media_or_404(request, media_id)
    return render(
        request,
        "activities/pages/tag.html",
        {
            "media": media,
            "url": selectors.media_url(media),
            "candidates": selectors.taggable_students(media, user=request.user),
            "blocked": selectors.blocked_tags(media),
            "is_publishable": selectors.is_publishable(media),
        },
    )


@login_required
@staff_required
@require_POST
def toggle_tag(request: HttpRequest, media_id: int, student_id: int) -> HttpResponse:
    """Two taps, not a form. htmx swaps the one name back; without it the page
    re-renders and the teacher is where they were."""
    media = _media_or_404(request, media_id)
    student = _student_or_404(request, student_id)

    if media.tags.filter(student=student).exists():
        services.untag(media=media, student=student)
    else:
        services.tag(media=media, student=student, tagged_by=request.user)

    if request.headers.get("HX-Request"):
        return render(
            request,
            "activities/partials/tag_row.html",
            {
                "media": media,
                "row": next(
                    row
                    for row in selectors.taggable_students(media, user=request.user)
                    if row["student"].pk == student.pk
                ),
            },
        )
    return redirect("activities_tag", media_id=media.pk)


@login_required
@staff_required
@require_POST
def publish_photo(request: HttpRequest, media_id: int) -> HttpResponse:
    """One photograph. The refusal names the child, so the teacher's next move is
    obvious — drop the tag, crop it, or keep it for that family."""
    media = _media_or_404(request, media_id)
    try:
        services.publish_media(media=media)
    except ValidationError as refused:
        messages.error(request, "; ".join(refused.messages))
    else:
        messages.success(request, "Published.")
    return redirect("activities_tag", media_id=media.pk)


# --- uploads ----------------------------------------------------------------------------


@login_required
@staff_required
@require_POST
def upload_url(request: HttpRequest, classroom_id: int) -> JsonResponse:
    """Hand the browser a presigned PUT and the row that will point at the object.

    The row is written FIRST, deliberately: an object that lands without a row is an
    orphan nobody is looking for, whereas a row without an object is exactly what the
    nightly reconciliation is built to find.

    503 rather than 500 when R2 is absent. It is a configuration state, not a fault,
    and the message says so — this is the development machine's normal condition.
    """
    from integrations import storage_r2

    room = _room_or_404(request, classroom_id)
    form = forms.UploadRequestForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"error": form.errors.as_text()}, status=400)

    if not storage_r2.is_configured():
        return JsonResponse(
            {"error": "Photo storage is not configured on this server yet."}, status=503
        )

    key = services.build_key(branch=room.branch, filename=form.cleaned_data["filename"])
    media = services.register_upload(
        branch=room.branch,
        key=key,
        uploaded_by=request.user,
        content_type=form.cleaned_data["content_type"],
    )
    return JsonResponse(
        {
            "media_id": media.pk,
            "url": storage_r2.presign_put(key=key, content_type=form.cleaned_data["content_type"]),
            "confirm": reverse("activities_confirm_upload", kwargs={"media_id": media.pk}),
        }
    )


@login_required
@staff_required
@require_POST
def confirm_upload(request: HttpRequest, media_id: int) -> JsonResponse:
    """The browser reports the PUT succeeded. Promote pending to stored."""
    media = _media_or_404(request, media_id)
    form = forms.ConfirmUploadForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"error": form.errors.as_text()}, status=400)

    if form.cleaned_data.get("taken_at"):
        media.taken_at = form.cleaned_data["taken_at"]
        media.save(update_fields=["taken_at", "updated_at"])
    services.confirm_upload(
        media=media,
        byte_size=form.cleaned_data.get("byte_size"),
        width=form.cleaned_data.get("width"),
        height=form.cleaned_data.get("height"),
    )
    return JsonResponse({"ok": True, "tag_url": reverse("activities_tag", args=[media.pk])})


# --- incidents --------------------------------------------------------------------------


@login_required
@staff_required
def report_incident(request: HttpRequest, student_id: int) -> HttpResponse:
    """Record that a child was hurt. No draft state — see services.report_incident."""
    student = _student_or_404(request, student_id)
    form = forms.IncidentForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        services.report_incident(
            student=student,
            staff_responsible=request.user,
            reported_by=request.user,
            occurred_at=form.cleaned_data.get("occurred_at") or None,
            severity=form.cleaned_data["severity"],
            what_happened=form.cleaned_data["what_happened"],
            action_taken=form.cleaned_data["action_taken"],
        )
        messages.success(request, f"Recorded. {student.display_name}'s family can see it now.")
        return redirect("student_detail", student_id=student.pk)

    return render(
        request, "activities/pages/incident_form.html", {"form": form, "student": student}
    )


@login_required
@staff_required
def incident_list(request: HttpRequest) -> HttpResponse:
    """What the branch admin chases: incidents no family has signed off yet."""
    return render(
        request,
        "activities/pages/incidents.html",
        {"incidents": selectors.unacknowledged_incidents(request.user)},
    )


# --- the parent portal ------------------------------------------------------------------


@login_required
def my_photos(request: HttpRequest) -> HttpResponse:
    """The nav's "Photos", which has no child in the URL.

    One child goes straight to the feed; more than one goes to the picker. The feed is
    the thing parents open every day — implementation-plan.md calls it the reason a
    school pays — and most families here have one child, so making all of them pass
    through a one-item list every time would be a tap charged daily for a choice that
    is not being offered.
    """
    children = list(people_selectors.children_of(request.user)[:2])
    if len(children) == 1:
        return redirect("my_child_photos", student_id=children[0].pk)
    return redirect("my_children")


@login_required
def my_child_photos(request: HttpRequest, student_id: int) -> HttpResponse:
    """The feed. Reverse-chronological by `taken_at`, grouped into days.

    `feed_for_child_of` returns (None, empty) both for a child that is not this user's
    and for one that does not exist, so a 404 here leaks neither.
    """
    child, feed = selectors.feed_for_child_of(request.user, student_id)
    if child is None:
        raise Http404("No such child.")

    from apps.core.models import ConsentPurpose

    # The selector leaves `url` None where R2 is unconfigured, because naming a Django
    # route is the controller's job. Fill it with the gated fallback view here.
    days = selectors.feed_days(feed)
    for bucket in days:
        for item in bucket["media"]:
            item["url"] = item["url"] or reverse("media_file", args=[item["asset"].pk])

    return render(
        request,
        "activities/pages/child_photos.html",
        {
            "child": child,
            "days": days,
            "has_consent": selectors.guardian_has_consent(
                request.user, ConsentPurpose.PHOTOS_IN_APP
            ),
        },
    )


@login_required
def my_child_diary(request: HttpRequest, student_id: int) -> HttpResponse:
    """The written day. Not consent-gated — a parent reading that their own child
    napped is the school telling them something, not a disclosure about anyone else."""
    child, entries = selectors.entries_for_child_of(request.user, student_id)
    if child is None:
        raise Http404("No such child.")
    _, incidents = selectors.incidents_for_child_of(request.user, student_id)
    return render(
        request,
        "activities/pages/child_diary.html",
        {"child": child, "entries": entries[:100], "incidents": incidents},
    )


@login_required
@require_POST
def acknowledge(request: HttpRequest, incident_id: int) -> HttpResponse:
    """A named guardian confirms they were told, at a known time.

    Scoped through `incidents_for_child_of` so a guardian cannot acknowledge another
    family's incident — which would put the wrong name on the one record that exists
    to say who was told.
    """
    from apps.activities.models import IncidentReport

    incident = (
        IncidentReport.objects.filter(
            pk=incident_id, student__in=people_selectors.children_of(request.user)
        )
        .select_related("student")
        .first()
    )
    if incident is None:
        raise Http404("No such incident.")

    services.acknowledge_incident(incident=incident, guardian=request.user)
    messages.success(request, "Thank you — we have recorded that you have seen this.")
    return redirect("my_child_diary", student_id=incident.student_id)


@login_required
def media_file(request: HttpRequest, media_id: int) -> FileResponse:
    """Stream one photograph from local storage, applying the same gate as the feed.

    Narrow by design, and worth being honest about when it runs. With R2 configured,
    `media_url` returns a presigned URL and nothing routes here. With R2 absent the
    upload endpoint answers 503, so no NEW photograph can reach local storage either —
    what this serves is rows that got there another way: a fixture, a management
    command, or a bucket that was configured and later was not.

    It exists rather than an unauthenticated /media/ URL because that would put a
    permanent public link on a photograph of a child and hole the rule this whole app
    is built around. plan.md's "do not proxy the bytes through Django" is about R2
    egress in production, which is exactly the case that never reaches this view.
    """
    from django.core.files.storage import default_storage

    from apps.activities.models import MediaAsset

    visible = selectors.media_for_user(request.user)
    if not visible.filter(pk=media_id).exists():
        # Fall back to the parent path: a guardian is not staff, so `media_for_user`
        # is empty for them and the gated feed is the only thing that may answer.
        allowed = {
            asset.pk
            for child in people_selectors.children_of(request.user)
            for asset in selectors.feed_for_child_of(request.user, child.pk)[1]
        }
        if media_id not in allowed:
            raise Http404("No such photo.")

    media = MediaAsset.objects.filter(pk=media_id).first()
    if media is None or not default_storage.exists(media.key):
        raise Http404("No such photo.")
    return FileResponse(default_storage.open(media.key, "rb"))


# --- helpers ----------------------------------------------------------------------------


def _occurred_on(writing: date_type):
    """Now, if the day being written up is today; otherwise midday on that day.

    Midday rather than midnight so a `taken_at`-ordered feed does not put a backfilled
    note either side of a real one by an accident of timezone.
    """
    from datetime import datetime, time

    now = timezone.localtime()
    if writing == now.date():
        return now
    return timezone.make_aware(datetime.combine(writing, time(12, 0)))
