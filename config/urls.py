from django.contrib import admin
from django.contrib.sitemaps.views import sitemap
from django.urls import include, path

from apps.core import views as core_views
from apps.website.sitemaps import StaticViewSitemap
from apps.website.views import robots_txt

sitemaps = {"static": StaticViewSitemap}

urlpatterns = [
    # Superadmin only — Django admin ignores request context, so it is an
    # operator tool, never a staff-facing surface. See docs/plan.md.
    path("admin/", admin.site.urls),
    path("healthz", core_views.healthz, name="healthz"),
    path("robots.txt", robots_txt, name="robots"),
    path(
        "sitemap.xml", sitemap, {"sitemaps": sitemaps}, name="django.contrib.sitemaps.views.sitemap"
    ),
    path("accounts/", include("apps.core.urls")),
    path("staff/", include("apps.people.urls")),
    path("portal/", include("apps.people.portal_urls")),
    path("", include("apps.website.urls")),
]
