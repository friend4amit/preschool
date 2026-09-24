"""Staff routes for the notice board, under /staff/announcements/.

The parent-facing routes are NOT here — they live in apps/people/portal_urls.py under
/portal/, so the staff/parent split stays visible in the URL tree rather than hiding
behind a role check. Same rule as apps/activities.
"""

from django.urls import path

from apps.announcements import views

urlpatterns = [
    path("", views.announcement_list, name="announcement_list"),
    path("new/", views.announcement_new, name="announcement_new"),
    path("<int:announcement_id>/", views.announcement_detail, name="announcement_detail"),
    path(
        "<int:announcement_id>/publish/",
        views.announcement_publish,
        name="announcement_publish",
    ),
    path(
        "<int:announcement_id>/withdraw/",
        views.announcement_unpublish,
        name="announcement_unpublish",
    ),
]
