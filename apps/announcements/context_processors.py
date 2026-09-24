"""The notices badge — the receipt-backed one.

There are now two unread badges in the portal and they are counted differently on
purpose. `apps/activities/context_processors.py` explains why the photo badge lives
in the session ("since last visit" is a browser-local question) and then names the
case where that stops being good enough:

    for a per-item read receipt — which Phase 7 wants for announcements — it would
    not be, and that is the point at which this earns a column.

So this one counts rows in `AnnouncementRead`. The visible difference to a parent is
the one worth having: read a notice on your phone and the badge is gone on the laptop
too, because the fact recorded is "this person read it", not "this browser visited".

The photo badge is deliberately left as it is. The docstring above earns a column for
announcements; it does not ask for photographs to be migrated, and doing both in one
phase would mean a nullable datetime per photo per guardian for a badge that already
works.
"""

from django.utils.functional import lazy

from apps.announcements import selectors


def portal_announcements(request):
    """Unread published notices addressed to this user's children.

    Lazy for the same reason the photo badge is: it is rendered in one partial in the
    portal nav, and every staff page and public page would otherwise pay for a query
    whose result they never show. Nothing is evaluated unless a template actually
    reads `portal_announcements_unread`.

    `lazy(..., int)` rather than `SimpleLazyObject`, and that is not cosmetic —
    SimpleLazyObject does not proxy `__float__`, so Django's `pluralize` silently
    returns the singular every time. Promising `int` copies int's dunders onto the
    proxy. The photo badge hit this first; the comment is repeated here because the
    next person to add a badge will reach for SimpleLazyObject.
    """

    def count() -> int:
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return 0
        return selectors.unread_count(user)

    return {"portal_announcements_unread": lazy(count, int)()}
