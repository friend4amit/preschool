from django.conf import settings
from django.conf.urls.static import static
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
    path("staff/attendance/", include("apps.attendance.urls")),
    path("portal/", include("apps.people.portal_urls")),
    path("", include("apps.website.urls")),
]

# Uploaded media, in development only. `static()` already returns [] when DEBUG is
# False, but the guard is written out anyway so nobody has to know that to be sure
# this is not serving media from Django in production — there, images come from R2
# (or from Caddy, when R2 is unconfigured). See deploy/Caddyfile.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
