"""Operator-only views. /admin is superadmin-only (config/admin.py); staff get built
screens, which arrive with the rest of Phase 4."""

from django.contrib import admin

from apps.activities.models import ActivityEntry, IncidentReport, MediaAsset, MediaTag


class MediaTagInline(admin.TabularInline):
    model = MediaTag
    extra = 0
    autocomplete_fields = ["student"]


@admin.register(ActivityEntry)
class ActivityEntryAdmin(admin.ModelAdmin):
    list_display = ["kind", "student", "classroom", "occurred_at", "is_published"]
    list_filter = ["kind", "is_published", "branch"]
    date_hierarchy = "occurred_at"


@admin.register(IncidentReport)
class IncidentReportAdmin(admin.ModelAdmin):
    list_display = ["student", "severity", "occurred_at", "acknowledged_at"]
    list_filter = ["severity", "branch"]
    date_hierarchy = "occurred_at"


@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):
    list_display = ["key", "taken_at", "upload_state", "is_published"]
    list_filter = ["upload_state", "is_published", "branch"]
    date_hierarchy = "taken_at"
    inlines = [MediaTagInline]
