from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from simple_history.admin import SimpleHistoryAdmin

from apps.core.models import (
    AcademicYear,
    Branch,
    BranchMembership,
    Classroom,
    Consent,
    Organization,
    User,
)


class BranchMembershipInline(admin.TabularInline):
    model = BranchMembership
    extra = 0


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """Subclasses Django's auth UserAdmin, and that is not a style preference.

    A plain `ModelAdmin` renders `password` as what the model says it is — an
    ordinary CharField — so an operator who types a new password into it saves the
    RAW STRING into the hash column. The account can then never log in, because
    `check_password` compares a real hash against a plain word, and the password sits
    readable in the database and in every pg_dump taken afterwards. This admin shipped
    that way and it cost three accounts; `manage.py repair_passwords` finds them.

    `DjangoUserAdmin` swaps in `ReadOnlyPasswordHashField` — the change form shows the
    algorithm and a link to the change-password screen, never an editable box — and
    `UserCreationForm` on the add form, which hashes.

    The fieldsets are restated because the stock ones name `username`, and this user
    is keyed by `phone`.
    """

    list_display = ("phone", "full_name", "email", "is_active", "is_superuser")
    list_filter = ("is_active", "is_superuser", "is_staff")
    search_fields = ("phone", "full_name", "email")
    ordering = ("full_name", "phone")
    inlines = [BranchMembershipInline]

    fieldsets = (
        (None, {"fields": ("phone", "password")}),
        ("Who they are", {"fields": ("full_name", "email")}),
        (
            "Permissions",
            {
                "fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions"),
                # /admin is superadmin-only (config/admin.py), so `is_staff` here is
                # Django's flag and not a role in this product. Roles are
                # BranchMembership rows, edited in the inline above.
                "description": "Staff roles live in Branch memberships below, not here.",
            },
        ),
        ("Dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("phone", "full_name", "usable_password", "password1", "password2"),
            },
        ),
    )


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "created_at")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "is_active", "gstin")
    list_filter = ("organization", "is_active")


@admin.register(Consent)
class ConsentAdmin(SimpleHistoryAdmin):
    list_display = ("guardian", "purpose", "granted", "version", "granted_at", "revoked_at")
    list_filter = ("purpose", "granted", "branch")
    search_fields = ("guardian__phone", "guardian__full_name")


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ("name", "start_date", "end_date", "is_current", "branch")
    list_filter = ("branch", "is_current")
    # Required by the autocomplete_fields on people's Enrollment admin.
    search_fields = ("name",)


@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ("name", "capacity", "is_active", "branch")
    list_filter = ("branch", "is_active")
    search_fields = ("name",)
