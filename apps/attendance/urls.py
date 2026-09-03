"""Register routes, under /staff/attendance/.

The day view carries the classroom in the path and the date in the query string,
deliberately: a teacher bookmarks their room, not their room on one Tuesday.
"""

from django.urls import path

from apps.attendance import views

urlpatterns = [
    path("", views.today, name="attendance_today"),
    path("<int:classroom_id>/", views.day, name="attendance_day"),
    path("<int:classroom_id>/all-present/", views.all_present, name="attendance_all_present"),
    path("<int:classroom_id>/report/", views.report, name="attendance_report"),
    path("<int:classroom_id>/<int:student_id>/mark/", views.mark, name="attendance_mark"),
    path("<int:classroom_id>/<int:student_id>/detail/", views.detail, name="attendance_detail"),
    path("pickup/<int:record_id>/", views.pickup, name="attendance_pickup"),
]
