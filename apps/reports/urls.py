"""The dashboard and the exports, under /staff/reports/.

The dashboard is at the root of this tree rather than at `/staff/` because `/staff/`
already belongs to `apps.people`. It is linked as the first item in the staff nav,
which is what makes it the screen the owner opens; the URL is not the thing that
decides that.

There is no parent-facing route here. Nothing in this app is scoped to a family.
"""

from django.urls import path

from apps.reports import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("files/", views.report_index, name="report_index"),
    path("files/roster.csv", views.roster_csv, name="roster_csv"),
    path(
        "files/attendance/<int:classroom_id>.csv",
        views.attendance_csv,
        name="attendance_csv",
    ),
    path(
        "files/register/<int:classroom_id>/",
        views.attendance_register,
        name="attendance_register",
    ),
]
