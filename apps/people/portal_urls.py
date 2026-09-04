"""Parent portal routes, all under /portal/.

Separate from the staff console's urls.py rather than folded in behind a role check,
so the split is visible in the URL tree and in robots.txt. A parent-facing URL that
looks like a staff one is a permission bug waiting to be written.
"""

from django.urls import path

from apps.activities import views as activities_views
from apps.attendance import views as attendance_views
from apps.people import views

urlpatterns = [
    path("", views.my_children, name="my_children"),
    path("children/<int:student_id>/", views.child_detail, name="child_detail"),
    path(
        "children/<int:student_id>/attendance/",
        attendance_views.my_child_attendance,
        name="my_child_attendance",
    ),
    path("photos/", activities_views.my_photos, name="my_photos"),
    path(
        "children/<int:student_id>/photos/",
        activities_views.my_child_photos,
        name="my_child_photos",
    ),
    path(
        "children/<int:student_id>/diary/",
        activities_views.my_child_diary,
        name="my_child_diary",
    ),
    path(
        "incidents/<int:incident_id>/seen/",
        activities_views.acknowledge,
        name="incident_acknowledge",
    ),
    # Only reached where R2 is unconfigured; see activities.views.media_file.
    path("photo/<int:media_id>/", activities_views.media_file, name="media_file"),
]
