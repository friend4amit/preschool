from django.contrib.admin.apps import AdminConfig


class AarohamAdminConfig(AdminConfig):
    default_site = "config.admin.SuperadminOnlyAdminSite"
