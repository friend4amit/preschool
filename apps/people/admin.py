"""Operator screens, not staff screens.

`/admin` is superadmin-only (`config/admin.py`) because Django admin ignores the
request user and would show every branch to a branch admin. School staff get built
screens later in this phase; this is here so the owner can fix data at 9pm.
"""

from django.contrib import admin

from apps.people.models import (
    AuthorizedPickup,
    Document,
    EmergencyContact,
    Enrollment,
    Guardian,
    Staff,
    Student,
    StudentGuardian,
)


class StudentGuardianInline(admin.TabularInline):
    model = StudentGuardian
    extra = 0
    autocomplete_fields = ["guardian"]


class EmergencyContactInline(admin.TabularInline):
    model = EmergencyContact
    extra = 0


class EnrollmentInline(admin.TabularInline):
    model = Enrollment
    extra = 0
    autocomplete_fields = ["classroom", "academic_year"]


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("display_name", "date_of_birth", "status", "has_medical_flags", "branch")
    list_filter = ("status", "branch")
    search_fields = ("first_name", "last_name", "preferred_name", "admission_number")
    inlines = [StudentGuardianInline, EmergencyContactInline, EnrollmentInline]
    fieldsets = [
        (None, {"fields": ["branch", "first_name", "last_name", "preferred_name", "photo"]}),
        ("Admission", {"fields": ["date_of_birth", "admission_number", "status"]}),
        (
            # Grouped and named so nobody has to hunt for an allergy in a flat form.
            "Medical — read on every roster",
            {
                "fields": [
                    "allergies",
                    "medical_conditions",
                    "medications",
                    "blood_group",
                    "doctor_name",
                    "doctor_phone",
                ]
            },
        ),
        ("Other", {"fields": ["notes"]}),
    ]

    @admin.display(boolean=True, description="Medical flags")
    def has_medical_flags(self, obj: Student) -> bool:
        return obj.has_medical_flags


@admin.register(Guardian)
class GuardianAdmin(admin.ModelAdmin):
    list_display = ("full_name", "phone", "email", "has_account", "branch")
    list_filter = ("branch",)
    search_fields = ("full_name", "phone", "email")

    @admin.display(boolean=True, description="Portal account")
    def has_account(self, obj: Guardian) -> bool:
        return obj.user_id is not None


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("student", "classroom", "academic_year", "joined_on", "left_on")
    list_filter = ("academic_year", "classroom", "branch")
    autocomplete_fields = ["student", "classroom", "academic_year"]


@admin.register(AuthorizedPickup)
class AuthorizedPickupAdmin(admin.ModelAdmin):
    list_display = ("name", "student", "relationship", "valid_from", "valid_to")
    list_filter = ("branch",)
    search_fields = ("name", "student__first_name", "student__last_name")


@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = ("user", "designation", "joined_on", "left_on", "branch")
    list_filter = ("branch",)
    search_fields = ("user__full_name", "user__phone", "designation")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    list_display = ("student", "doc_type", "expires_on", "created_at")
    list_filter = ("doc_type", "branch")
    search_fields = ("student__first_name", "student__last_name")
