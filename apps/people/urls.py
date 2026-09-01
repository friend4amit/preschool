"""Staff console routes, all under /staff/.

Named, never referenced by literal path: a renamed URL then fails loudly at render
instead of shipping a dead link.
"""

from django.urls import path

from apps.people import views

urlpatterns = [
    path("students/", views.student_list, name="student_list"),
    path("students/new/", views.student_new, name="student_new"),
    path("students/<int:student_id>/", views.student_detail, name="student_detail"),
    path("students/<int:student_id>/edit/", views.student_edit, name="student_edit"),
    path("students/<int:student_id>/guardians/new/", views.guardian_new, name="guardian_new"),
    path("students/<int:student_id>/guardians/link/", views.guardian_link, name="guardian_link"),
    path(
        "students/<int:student_id>/emergency-contacts/new/",
        views.emergency_contact_add,
        name="emergency_contact_add",
    ),
    path(
        "students/<int:student_id>/enrolment/",
        views.enrollment_change,
        name="enrollment_change",
    ),
    path("guardians/<int:guardian_id>/", views.guardian_edit, name="guardian_edit"),
    path("guardians/<int:guardian_id>/account/", views.guardian_account, name="guardian_account"),
    path("enquiries/", views.enquiry_list, name="enquiry_list"),
    path("enquiries/<int:enquiry_id>/admit/", views.enquiry_convert, name="enquiry_convert"),
    path("staff/", views.staff_list, name="staff_list"),
    path("staff/new/", views.staff_new, name="staff_new"),
    path("staff/<int:staff_id>/", views.staff_detail, name="staff_detail"),
]
