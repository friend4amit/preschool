"""Operator-only views. /admin is superadmin-only (config/admin.py); staff use the
notice board under /staff/announcements/.

`AnnouncementRead` is registered read-only. A receipt is a record that a named person
saw something at a known time, and an operator who can edit one by hand has turned it
into an assertion. Deleting a notice still removes its receipts, which is the cascade
the FK declares and the right one — the claim has no meaning without the notice.
"""

from django.contrib import admin

from apps.announcements.models import Announcement, AnnouncementRead


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ["title", "audience", "is_published", "published_at", "expires_on"]
    list_filter = ["is_published", "is_pinned", "branch"]
    search_fields = ["title", "body"]
    date_hierarchy = "created_at"


@admin.register(AnnouncementRead)
class AnnouncementReadAdmin(admin.ModelAdmin):
    list_display = ["announcement", "guardian", "read_at"]
    list_filter = ["announcement"]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
