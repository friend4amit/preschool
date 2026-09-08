"""The installable portal, the unread badge, and the paged feed.

Grouped together because they are one claim: the parent portal is an app a family can
put on a home screen and open every day, and the count on the icon is the same count
the feed will honour.

The one test in here that is a security test rather than a feature test is
`test_the_service_worker_caches_no_photograph`. A worker that cached photo responses
would write children's images into browser cache storage, and Phase 4's own "revoking
photos_in_app hides the feed on the next request" would quietly become false.
"""

import io
import json
import re

import pytest
from django.conf import settings
from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.urls import reverse
from PIL import Image

from apps.activities import services, views
from apps.activities.context_processors import SESSION_KEY
from apps.core.models import ConsentPurpose

pytestmark = pytest.mark.django_db


def _published_photo(branch, teacher, child, *, key):
    """A photo that has actually cleared the gate, so a badge can count it."""
    media = services.register_upload(branch=branch, key=key, uploaded_by=teacher)
    services.confirm_upload(media=media, byte_size=1024)
    services.tag(media=media, student=child, tagged_by=teacher)
    return services.publish_media(media=media)


def _consent_to_everything(consent_for, user):
    consent_for(user, ConsentPurpose.PHOTOS_IN_APP)
    consent_for(user, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS)


def _jpeg_in_storage(key, *, size, colour=(120, 140, 90)) -> int:
    """Put a real JPEG at `key` and return its byte count.

    Real bytes rather than a stub: `build_thumbnail` opens what it finds and hands it
    to Pillow, so b"not-a-jpeg" would fail the decode rather than exercise the resize.
    """
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, format="JPEG")
    default_storage.save(key, ContentFile(buffer.getvalue()))
    return len(buffer.getvalue())


# --------------------------------------------------------------------------------
# The PWA surfaces
# --------------------------------------------------------------------------------


def test_the_manifest_is_served_and_points_at_the_portal(client):
    """`start_url` is /portal/ and not /. The home-screen icon belongs to a signed-in
    parent; landing them on the enquiry page would be a stranger's answer."""
    response = client.get(reverse("manifest"))

    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/manifest+json")
    manifest = json.loads(response.content)
    assert manifest["start_url"] == "/portal/"
    assert manifest["scope"] == "/portal/"
    # Android crops to the launcher's shape; without a maskable icon it takes the
    # leaves off the one that is there.
    assert any(icon.get("purpose") == "maskable" for icon in manifest["icons"])


def test_the_service_worker_is_served_from_the_root(client):
    """A worker's scope cannot be broader than the path it came from, so one under
    /static/ could never control /portal/. This is why it is a view."""
    response = client.get("/sw.js")

    assert response.status_code == 200
    assert response["Content-Type"].startswith("text/javascript")
    assert response["Cache-Control"] == "no-cache"


def test_the_service_worker_caches_no_photograph(client):
    """The security test in this file.

    The worker works from a positive allowlist of shell URLs. Nothing that could
    resolve to a child's photograph — the portal tree, the gated media view — may
    appear in it, because a cached response is one the consent gate never saw.
    """
    body = client.get("/sw.js").content.decode()

    shell = body.split("const SHELL = [", 1)[1].split("];", 1)[0]
    assert "/portal/" not in shell
    assert "/photo/" not in shell
    # And the only thing it will serve from cache is an entry in that list.
    assert "SHELL.includes(url.pathname)" in body


def test_the_offline_page_renders(client):
    """Cached by the worker, so it has to stand up with no session and no network."""
    response = client.get(reverse("offline"))

    assert response.status_code == 200
    assert "offline" in response.content.decode().lower()


def test_every_page_advertises_the_manifest(client):
    response = client.get(reverse("home"))

    assert b'rel="manifest"' in response.content


# --------------------------------------------------------------------------------
# The unread badge
# --------------------------------------------------------------------------------


def test_a_first_visit_shows_no_badge(client, branch, teacher, child_a, parent_a, consent_for):
    """Seeded to now on first sight, not to the epoch. A parent logging in for the
    first time should not meet a badge counting the school's whole history."""
    _consent_to_everything(consent_for, parent_a)
    _published_photo(branch, teacher, child_a, key="photos/1/badge/first.jpg")
    client.force_login(parent_a)

    response = client.get(reverse("my_children"))

    assert response.context["portal_unread"] == 0


def test_a_photo_published_after_the_last_visit_is_badged(
    client, branch, teacher, child_a, parent_a, consent_for
):
    _consent_to_everything(consent_for, parent_a)
    client.force_login(parent_a)
    client.get(reverse("my_children"))  # seeds last-visit

    _published_photo(branch, teacher, child_a, key="photos/1/badge/new.jpg")

    assert client.get(reverse("my_children")).context["portal_unread"] == 1


def test_opening_the_feed_clears_the_badge(client, branch, teacher, child_a, parent_a, consent_for):
    _consent_to_everything(consent_for, parent_a)
    client.force_login(parent_a)
    client.get(reverse("my_children"))
    _published_photo(branch, teacher, child_a, key="photos/1/badge/clear.jpg")
    assert client.get(reverse("my_children")).context["portal_unread"] == 1

    client.get(reverse("my_child_photos", args=[child_a.pk]))

    assert client.get(reverse("my_children")).context["portal_unread"] == 0


def test_the_badge_honours_the_same_gate_as_the_feed(
    client, branch, teacher, child_a, parent_a, consent_for
):
    """A count derived separately from the feed is how a badge comes to promise a
    photo the feed then withholds. Without `photos_in_app` both are empty."""
    consent_for(parent_a, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS)
    client.force_login(parent_a)
    client.get(reverse("my_children"))
    _published_photo(branch, teacher, child_a, key="photos/1/badge/gated.jpg")

    assert client.get(reverse("my_children")).context["portal_unread"] == 0


def test_another_familys_photo_never_reaches_the_badge(
    client, branch, teacher, child_b, parent_a, parent_b, consent_for
):
    _consent_to_everything(consent_for, parent_a)
    _consent_to_everything(consent_for, parent_b)
    client.force_login(parent_a)
    client.get(reverse("my_children"))

    _published_photo(branch, teacher, child_b, key="photos/1/badge/theirs.jpg")

    assert client.get(reverse("my_children")).context["portal_unread"] == 0


def test_an_htmx_page_of_the_feed_does_not_clear_the_badge(
    client, branch, teacher, child_a, parent_a, consent_for
):
    """A request for page four is the same visit still going. Clearing there would
    clear the badge against photographs published while the parent was mid-scroll."""
    _consent_to_everything(consent_for, parent_a)
    client.force_login(parent_a)
    client.get(reverse("my_children"))
    before = client.session[SESSION_KEY]

    client.get(reverse("my_child_photos", args=[child_a.pk]), HTTP_HX_REQUEST="true")

    assert client.session[SESSION_KEY] == before


def test_a_staff_user_gets_no_badge(client, teacher):
    """`unread_count` runs `children_of`, which is empty for a member of staff — but
    the context processor runs on their pages too, so it is worth proving it is 0
    rather than an error."""
    client.force_login(teacher)

    assert client.get(reverse("student_list")).context["portal_unread"] == 0


# --------------------------------------------------------------------------------
# Paging the feed
# --------------------------------------------------------------------------------


def test_the_feed_pages_and_offers_a_real_link_to_the_next(
    client, branch, teacher, child_a, parent_a, consent_for
):
    """htmx infinite scroll over a real paginator: the sentinel is an `<a href>` that
    works with JavaScript off, which is the same rule the student list follows."""
    _consent_to_everything(consent_for, parent_a)
    for index in range(views.FEED_PAGE_SIZE + 2):
        _published_photo(branch, teacher, child_a, key=f"photos/1/page/{index}.jpg")
    client.force_login(parent_a)

    response = client.get(reverse("my_child_photos", args=[child_a.pk]))
    body = response.content.decode()

    # `has_next` is a method on Django's Page; the template calls it for us.
    assert response.context["page"].has_next() is True
    assert len(response.context["page"].object_list) == views.FEED_PAGE_SIZE
    assert 'href="?page=2' in body
    assert 'hx-trigger="revealed"' in body


def test_the_second_page_comes_back_as_a_partial(
    client, branch, teacher, child_a, parent_a, consent_for
):
    _consent_to_everything(consent_for, parent_a)
    for index in range(views.FEED_PAGE_SIZE + 2):
        _published_photo(branch, teacher, child_a, key=f"photos/1/partial/{index}.jpg")
    client.force_login(parent_a)

    response = client.get(
        reverse("my_child_photos", args=[child_a.pk]) + "?page=2", HTTP_HX_REQUEST="true"
    )
    body = response.content.decode()

    assert response.status_code == 200
    # A partial never extends a layout — that is what makes it swappable into a target.
    assert "<html" not in body
    assert response.context["page"].number == 2


def test_a_day_split_across_two_pages_is_headed_only_once(
    client, branch, teacher, child_a, parent_a, consent_for
):
    """The one fiddly part of paging a grouped feed. Page two usually opens partway
    through a day page one already headed, and printing "Friday, 3 April" twice down
    the column is the tell that nobody scrolled it."""
    _consent_to_everything(consent_for, parent_a)
    for index in range(views.FEED_PAGE_SIZE + 2):
        _published_photo(branch, teacher, child_a, key=f"photos/1/sameday/{index}.jpg")
    client.force_login(parent_a)

    first = client.get(reverse("my_child_photos", args=[child_a.pk]))
    day = first.context["days"][-1]["day"].isoformat()

    second = client.get(
        f"{reverse('my_child_photos', args=[child_a.pk])}?page=2&after={day}",
        HTTP_HX_REQUEST="true",
    )

    assert second.context["continues_day"] is True
    # ...and the heading is genuinely absent from the markup, not merely flagged.
    assert first.context["days"][-1]["day"].strftime("%A") not in second.content.decode()


def test_a_stranger_cannot_page_another_familys_feed(client, child_b, parent_a, consent_for):
    """404 on every page, not just the first. A paging parameter is not a way round
    the gate."""
    _consent_to_everything(consent_for, parent_a)
    client.force_login(parent_a)

    url = reverse("my_child_photos", args=[child_b.pk])
    assert client.get(url).status_code == 404
    assert client.get(f"{url}?page=2").status_code == 404


# --------------------------------------------------------------------------------
# Thumbnails
# --------------------------------------------------------------------------------


def test_a_thumbnail_is_built_and_the_feed_prefers_it(branch, teacher, child_a):
    """The feed grid renders these at roughly 180px. Serving the 1600px original into
    that square is the difference between a few hundred KB and several megabytes."""
    key = "photos/1/thumb/big.jpg"
    byte_size = _jpeg_in_storage(key, size=(1600, 1200))

    media = services.register_upload(branch=branch, key=key, uploaded_by=teacher)
    services.confirm_upload(media=media, byte_size=byte_size)

    services.build_thumbnail(media=media)
    media.refresh_from_db()

    assert media.thumbnail_key == "photos/1/thumb/big_thumb.jpg"
    assert default_storage.exists(media.thumbnail_key)
    with default_storage.open(media.thumbnail_key, "rb") as handle:
        thumb = Image.open(io.BytesIO(handle.read()))
    assert max(thumb.size) == services.THUMBNAIL_EDGE
    # Smaller than the original, which is the entire point.
    assert default_storage.size(media.thumbnail_key) < default_storage.size(key)


def test_building_a_thumbnail_twice_is_free(branch, teacher):
    """Idempotent, so a retried task is not a second round trip to storage."""
    key = "photos/1/thumb/twice.jpg"
    _jpeg_in_storage(key, size=(800, 600), colour=(200, 200, 200))

    media = services.register_upload(branch=branch, key=key, uploaded_by=teacher)
    services.confirm_upload(media=media)
    services.build_thumbnail(media=media)
    first = default_storage.size(media.thumbnail_key)

    services.build_thumbnail(media=media)

    assert default_storage.size(media.thumbnail_key) == first


def test_a_pending_photo_gets_no_thumbnail(branch, teacher):
    """Nothing is known to exist in storage yet, so there is nothing to downscale."""
    media = services.register_upload(branch=branch, key="photos/1/thumb/pending.jpg")

    services.build_thumbnail(media=media)

    assert media.thumbnail_key == ""


def test_the_badge_pluralises(client, branch, teacher, child_a, parent_a, consent_for):
    """`portal_unread` is lazy, and the first lazy wrapper tried here was quietly
    wrong: `SimpleLazyObject` does not proxy `__float__`, so Django's `pluralize`
    fell through its own except clauses and returned the singular for every count.
    The badge read "12 new photo". Promising `int` fixes it — and this test is what
    stops the next person swapping it back."""
    _consent_to_everything(consent_for, parent_a)
    client.force_login(parent_a)
    client.get(reverse("my_children"))
    for index in range(2):
        _published_photo(branch, teacher, child_a, key=f"photos/1/plural/{index}.jpg")

    body = client.get(reverse("my_children")).content.decode()

    assert "2 new photos" in body


def test_every_url_the_worker_caches_actually_exists(client):
    """The failure this catches is silent by construction.

    `cache.add()` is wrapped in a `.catch()` so one bad URL cannot abort the whole
    install — which means a SHELL entry that 404s leaves the worker installed, the
    offline page uncached, and the one reason the worker exists quietly not working.
    Nothing in the browser complains.

    So: read the allowlist out of the rendered worker and prove every entry resolves
    to something real. Static URLs are checked through the staticfiles machinery
    rather than over HTTP, because nothing serves /static/ in tests — and that is also
    the check that matters, since under the deployed manifest storage the URL in this
    file is the HASHED one and it is the storage that knows whether it exists.
    """
    body = client.get("/sw.js").content.decode()
    shell = body.split("const SHELL = [", 1)[1].split("];", 1)[0]
    urls = re.findall(r'"([^"]+)"', shell)

    assert len(urls) >= 5, f"Suspiciously short allowlist: {urls}"

    missing = []
    for url in urls:
        if url.startswith(settings.STATIC_URL):
            name = url[len(settings.STATIC_URL) :]
            if not (finders.find(name) or staticfiles_storage.exists(name)):
                missing.append(url)
        elif client.get(url).status_code != 200:
            missing.append(url)

    assert not missing, (
        f"The service worker caches {missing}, which do not exist. The install "
        "swallows the failure, so this would ship as a worker that quietly never "
        "caches the offline page."
    )
