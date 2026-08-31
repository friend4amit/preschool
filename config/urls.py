from django.contrib import admin
from django.urls import path

from apps.core import views

urlpatterns = [
    # Superadmin only — Django admin ignores request context, so it is an
    # operator tool, never a staff-facing surface. See docs/plan.md.
    path("admin/", admin.site.urls),
    path("healthz", views.healthz, name="healthz"),
    path("", views.home, name="home"),
]
