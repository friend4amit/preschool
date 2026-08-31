from django.contrib import admin

from apps.core.models import Branch, BranchMembership, Consent, Organization, User


class BranchMembershipInline(admin.TabularInline):
    model = BranchMembership
    extra = 0


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("phone", "full_name", "email", "is_active", "is_superuser")
    search_fields = ("phone", "full_name", "email")
    inlines = [BranchMembershipInline]


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "created_at")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "is_active", "gstin")
    list_filter = ("organization", "is_active")


@admin.register(Consent)
class ConsentAdmin(admin.ModelAdmin):
    list_display = ("guardian", "purpose", "granted", "version", "granted_at", "revoked_at")
    list_filter = ("purpose", "granted", "branch")
    search_fields = ("guardian__phone", "guardian__full_name")
