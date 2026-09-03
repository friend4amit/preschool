"""Operator screens, not staff screens.

`/admin` is superadmin-only (`config/admin.py`), so this exists for the owner fixing a
register at 9pm, not for a teacher marking one. Teachers get the grid.
"""

from django.contrib import admin

from apps.attendance.models import AttendanceRecord, PickupRecord, StaffAttendance


class PickupInline(admin.StackedInline):
    model = PickupRecord
    extra = 0
    autocomplete_fields = ["authorized_pickup", "guardian"]


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ("student", "date", "status", "classroom", "marked_by", "marked_at")
    list_filter = ("status", "date", "classroom", "branch")
    search_fields = ("student__first_name", "student__last_name", "student__admission_number")
    date_hierarchy = "date"
    autocomplete_fields = ["student", "classroom"]
    inlines = [PickupInline]


@admin.register(PickupRecord)
class PickupRecordAdmin(admin.ModelAdmin):
    list_display = ("attendance", "collected_by", "was_override", "released_by", "released_at")
    # `was_override` first among the filters on purpose: the exceptions are the only
    # rows anyone comes here to read.
    list_filter = ("branch", "released_at")
    search_fields = (
        "attendance__student__first_name",
        "attendance__student__last_name",
        "override_name",
    )
    autocomplete_fields = ["attendance", "authorized_pickup", "guardian"]

    @admin.display(boolean=True, description="Override")
    def was_override(self, obj: PickupRecord) -> bool:
        return obj.was_override


@admin.register(StaffAttendance)
class StaffAttendanceAdmin(admin.ModelAdmin):
    list_display = ("staff", "date", "status", "marked_by")
    list_filter = ("status", "date", "branch")
    search_fields = ("staff__user__full_name", "staff__user__phone")
    date_hierarchy = "date"
