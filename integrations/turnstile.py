"""Cloudflare Turnstile — spam protection for the public enquiry form.

A vendor wrapper, so it imports no domain code and tests get a fake for free.
Free, privacy-friendly, and what the reference site already used.
"""

import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
TIMEOUT_SECONDS = 5


def is_enabled() -> bool:
    return bool(getattr(settings, "TURNSTILE_SECRET_KEY", ""))


def verify(token: str, remote_ip: str | None = None) -> bool:
    """True if the challenge passed.

    Fails **open** on a network error or timeout, and says so in the log. A parent
    who cannot submit an admissions enquiry because Cloudflare had a bad minute is a
    worse outcome than a spam row an admin deletes.
    """
    if not is_enabled():
        return True
    if not token:
        return False

    payload = {"secret": settings.TURNSTILE_SECRET_KEY, "response": token}
    if remote_ip:
        payload["remoteip"] = remote_ip

    try:
        response = requests.post(VERIFY_URL, data=payload, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        return bool(response.json().get("success", False))
    except requests.RequestException:
        logger.warning("Turnstile verification unreachable; allowing submission", exc_info=True)
        return True
