"""Parent portal routes, all under /portal/.

Separate from the staff console's urls.py rather than folded in behind a role check,
so the split is visible in the URL tree and in robots.txt. A parent-facing URL that
looks like a staff one is a permission bug waiting to be written.
"""

from django.urls import path

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
]
