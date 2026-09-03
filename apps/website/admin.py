from django.contrib import admin

from apps.website.models import (
    Enquiry,
    GalleryImage,
    Program,
    SiteSettings,
    Stat,
    TeamMember,
    Testimonial,
)


@admin.register(SiteSettings)
class SiteSettingsAdmin(admin.ModelAdmin):
    list_display = ("branch", "phone", "email")


@admin.register(Program)
class ProgramAdmin(admin.ModelAdmin):
    list_display = ("name", "age_range_display", "order", "is_published")
    list_editable = ("order", "is_published")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(TeamMember)
class TeamMemberAdmin(admin.ModelAdmin):
    list_display = ("name", "role", "order", "is_published")
    list_editable = ("order", "is_published")


@admin.register(Testimonial)
class TestimonialAdmin(admin.ModelAdmin):
    list_display = ("author_name", "relationship", "is_published")
    list_editable = ("is_published",)


@admin.register(GalleryImage)
class GalleryImageAdmin(admin.ModelAdmin):
    list_display = ("__str__", "placement", "order", "is_published", "branch")
    list_filter = ("placement", "is_published", "branch")
    list_editable = ("placement", "order", "is_published")


@admin.register(Stat)
class StatAdmin(admin.ModelAdmin):
    """The numbers on the home page. Nobody should be inventing these — see the
    CONFIRM BEFORE LAUNCH note in seed_website.py."""

    list_display = ("value", "label", "order", "is_published", "branch")
    list_editable = ("order", "is_published")


@admin.register(Enquiry)
class EnquiryAdmin(admin.ModelAdmin):
    list_display = ("guardian_name", "phone", "child_name", "program", "status", "created_at")
    list_filter = ("status", "program", "branch", "created_at")
    search_fields = ("guardian_name", "phone", "email", "child_name")
    readonly_fields = ("created_at", "updated_at", "source")
