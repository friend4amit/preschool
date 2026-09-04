"""Staff routes for the day and the photographs, under /staff/day/.

The day view carries the classroom in the path and the date in the query string, the
same shape the register uses: a teacher bookmarks their room, not their room on one
Tuesday.

Parent-facing routes are NOT here — they live in apps/people/portal_urls.py under
/portal/, so the staff/parent split stays visible in the URL tree rather than hiding
behind a role check.
"""

from django.urls import path

from apps.activities import views

urlpatterns = [
    path("", views.today, name="activities_today"),
    path("<int:classroom_id>/", views.day, name="activities_day"),
    path("<int:classroom_id>/record/", views.quick_entry, name="activities_quick_entry"),
    path("<int:classroom_id>/publish/", views.publish_day, name="activities_publish_day"),
    path("<int:classroom_id>/upload-url/", views.upload_url, name="activities_upload_url"),
    path("photo/<int:media_id>/", views.tag_photo, name="activities_tag"),
    path(
        "photo/<int:media_id>/tag/<int:student_id>/",
        views.toggle_tag,
        name="activities_toggle_tag",
    ),
    path("photo/<int:media_id>/publish/", views.publish_photo, name="activities_publish_photo"),
    path("photo/<int:media_id>/confirm/", views.confirm_upload, name="activities_confirm_upload"),
    path("incidents/", views.incident_list, name="incident_list"),
    path("incidents/new/<int:student_id>/", views.report_incident, name="incident_new"),
]
