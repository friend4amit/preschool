from django.contrib.admin import AdminSite


class SuperadminOnlyAdminSite(AdminSite):
    """Django admin ignores request context: it uses `_default_manager` and knows
    nothing about the request user, so a branch admin who reaches it would see every
    branch unless every ModelAdmin overrode get_queryset.

    Rather than maintain forty overrides, the admin is an operator tool only. School
    staff get purpose-built screens. See docs/plan.md.
    """

    site_header = "Aaroham operations"
    site_title = "Aaroham"
    index_title = "Operator tools"

    def has_permission(self, request) -> bool:
        return bool(request.user.is_active and request.user.is_superuser)
