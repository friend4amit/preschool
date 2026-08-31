"""Controllers. Parse the request, call one service or selector, pick a template.

If a view here grows past ~15 lines, or grows an `if` about business meaning, the
logic belongs a layer down. `lint-imports` enforces that these never reach past
services and selectors into the ORM.
"""

from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


def home(request: HttpRequest) -> HttpResponse:
    return render(request, "core/pages/home.html")


def healthz(request: HttpRequest) -> HttpResponse:
    """Liveness for the container health check. Deliberately touches nothing."""
    return HttpResponse("ok", content_type="text/plain")
