"""The unread badge, and the "last visit" it counts from.

Controller layer — it takes a request, so it belongs above services and selectors and
is named accordingly. `apps/core/tests/test_architecture.py` guards `views.py`,
`services.py` and `selectors.py`; this is the fourth kind of module in that stack and
sits on the same side of the line as `views.py`.

**Why the session.** The plan asks for "an unread badge since last visit" and says
nothing about where last-visit lives. There is no field for it, and adding one is a
migration, a nullable datetime on `User` that only guardians ever use, and a write on
every feed view. The session already exists, already survives thirty days
(`SESSION_COOKIE_AGE`), and is already written on every request
(`SESSION_SAVE_EVERY_REQUEST`). What it costs is honest and worth stating: the badge
is per browser. A parent who reads the feed on their phone still sees a badge on the
laptop. For a "since last visit" badge that is a tolerable answer; for a per-item read
receipt — which Phase 7 wants for announcements — it would not be, and that is the
point at which this earns a column.

**Why a context processor.** The badge belongs in the portal nav, which lives in
`layouts/parent.html` and is inherited by views in three different apps. Threading a
count through every one of them is six places to forget it. The cost is a query on
pages that never show a badge, which the lazy wrapper removes: nothing is evaluated
unless a template actually renders `portal_unread`.
"""

from django.utils import timezone
from django.utils.functional import lazy

SESSION_KEY = "portal_last_visit"


def _last_visit(request):
    """When this browser last opened the feed.

    Seeded to *now* on first sight rather than to the epoch. A parent logging in for
    the first time should not be met with a badge counting every photograph the school
    has ever published of their child — that is a history, not news.

    "First sight" is the first page that RENDERS the badge, not the first request:
    this runs inside the lazy callable, so a parent whose first authenticated page has
    no badge on it is seeded a page later. The behaviour is the same either way — the
    seed is only ever "now" — but the timing is worth stating rather than assuming.
    """
    stamp = request.session.get(SESSION_KEY)
    if stamp:
        from django.utils.dateparse import parse_datetime

        parsed = parse_datetime(stamp)
        if parsed is not None:
            return parsed
    now = timezone.now()
    request.session[SESSION_KEY] = now.isoformat()
    return now


def mark_feed_visited(request) -> None:
    """Reset the badge. Called by the feed views, and only by them.

    Opening "my children" deliberately does not clear it — the badge points at
    photographs, so it clears when the photographs have been looked at.
    """
    request.session[SESSION_KEY] = timezone.now().isoformat()


def portal_unread(request):
    """Published photographs of this browser's user's children since their last visit.

    Uses `selectors.unread_count`, which runs the same gated query as the feed itself.
    A count derived any other way is a badge that can promise a photo the feed then
    withholds, and those two drift apart the first time consent is revoked.
    """

    def count() -> int:
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return 0
        from apps.activities import selectors

        return selectors.unread_count(user, _last_visit(request))

    # `lazy(..., int)` rather than SimpleLazyObject, and the difference is not
    # cosmetic. SimpleLazyObject does not proxy `__float__`, so Django's `pluralize`
    # filter falls through its own except clauses and silently returns the SINGULAR
    # every time — "12 new photo". Promising `int` copies int's dunders onto the
    # proxy, so the value behaves like the number a template author expects.
    return {"portal_unread": lazy(count, int)()}
