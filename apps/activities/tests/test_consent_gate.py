"""The consent gate. If one file in this app is right, it should be this one.

docs/plan.md: a photograph reaching a family who should not see it makes every other
permission rule in the product decorative. These tests are the ones that fail loudly
when that starts to happen.
"""

import pytest

from apps.activities import selectors, services
from apps.activities.models import UploadState
from apps.core.models import ConsentPurpose

pytestmark = pytest.mark.django_db


def _stored_photo(branch, teacher, *, key="photos/2026/06/a.webp"):
    media = services.register_upload(branch=branch, key=key, uploaded_by=teacher)
    return services.confirm_upload(media=media, byte_size=1024, width=800, height=600)


# --------------------------------------------------------------------------------
# photos_in_app — a property of the viewer
# --------------------------------------------------------------------------------


def test_feed_is_empty_without_photos_in_app(branch, teacher, child_a, parent_a, consent_for):
    """Consent is off by default, so the closed door is the default state."""
    media = _stored_photo(branch, teacher)
    services.tag(media=media, student=child_a, tagged_by=teacher)
    consent_for(parent_a, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS)
    services.publish_media(media=media)

    child, feed = selectors.feed_for_child_of(parent_a, child_a.pk)

    assert child == child_a
    assert list(feed) == []


def test_feed_shows_the_photo_once_both_consents_are_active(
    branch, teacher, child_a, parent_a, consent_for
):
    media = _stored_photo(branch, teacher)
    services.tag(media=media, student=child_a, tagged_by=teacher)
    consent_for(parent_a, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS)
    consent_for(parent_a, ConsentPurpose.PHOTOS_IN_APP)
    services.publish_media(media=media)

    _, feed = selectors.feed_for_child_of(parent_a, child_a.pk)

    assert list(feed) == [media]


def test_revoking_photos_in_app_empties_the_feed_on_the_next_request(
    branch, teacher, child_a, parent_a, consent_for
):
    """The plan's wording is "on the next request", so nothing may be cached."""
    media = _stored_photo(branch, teacher)
    services.tag(media=media, student=child_a, tagged_by=teacher)
    consent_for(parent_a, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS)
    consent_for(parent_a, ConsentPurpose.PHOTOS_IN_APP)
    services.publish_media(media=media)
    assert list(selectors.feed_for_child_of(parent_a, child_a.pk)[1]) == [media]

    consent_for(parent_a, ConsentPurpose.PHOTOS_IN_APP, granted=False)

    assert list(selectors.feed_for_child_of(parent_a, child_a.pk)[1]) == []


# --------------------------------------------------------------------------------
# photos_shared_with_class — a property of every child in the frame
# --------------------------------------------------------------------------------


def test_publish_refuses_when_one_tagged_child_lacks_sharing_consent(
    branch, teacher, child_a, child_b, parent_a, consent_for
):
    """Most classroom photos have several children in them. This is the rule that
    stops one family's yes from publishing another family's child."""
    from django.core.exceptions import ValidationError

    media = _stored_photo(branch, teacher)
    services.tag(media=media, student=child_a, tagged_by=teacher)
    services.tag(media=media, student=child_b, tagged_by=teacher)
    consent_for(parent_a, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS)

    with pytest.raises(ValidationError) as raised:
        services.publish_media(media=media)

    # The refusal names the child, because the teacher's next move is to drop that
    # tag or crop the photo and they need to know whose.
    assert child_b.display_name in str(raised.value)
    media.refresh_from_db()
    assert media.is_published is False


def test_a_two_child_photo_publishes_when_both_families_consented(
    branch, teacher, child_a, child_b, parent_a, parent_b, consent_for
):
    media = _stored_photo(branch, teacher)
    services.tag(media=media, student=child_a, tagged_by=teacher)
    services.tag(media=media, student=child_b, tagged_by=teacher)
    consent_for(parent_a, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS)
    consent_for(parent_b, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS)

    services.publish_media(media=media)

    media.refresh_from_db()
    assert media.is_published is True


def test_untagged_photo_is_never_publishable(branch, teacher):
    """No tags means no family it belongs to — publishing it would put an
    unattributed picture of children into every feed."""
    from django.core.exceptions import ValidationError

    media = _stored_photo(branch, teacher)

    assert selectors.is_publishable(media) is False
    with pytest.raises(ValidationError):
        services.publish_media(media=media)


def test_blocked_tags_names_the_children_at_tagging_time(
    branch, teacher, child_a, child_b, parent_a, consent_for
):
    """The teacher sees this while tagging, not when publish refuses. A rule
    discovered only at the end is a rule that gets worked around."""
    media = _stored_photo(branch, teacher)
    services.tag(media=media, student=child_a, tagged_by=teacher)
    services.tag(media=media, student=child_b, tagged_by=teacher)
    consent_for(parent_a, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS)

    assert selectors.blocked_tags(media) == [child_b]


# --------------------------------------------------------------------------------
# The multi-guardian rule, which plan.md does not settle and selectors.py does
# --------------------------------------------------------------------------------


def test_a_recorded_refusal_beats_another_guardians_grant(
    branch, teacher, child_a, parent_a, consent_for
):
    """Two guardians, one says yes and the other says no. The no wins — otherwise
    "revocable" means nothing for a child with more than one parent."""
    from apps.core.models import User
    from apps.people.services import create_guardian, link_guardian

    second = User.objects.create_user(phone="9100000009", full_name="Anil Sharma")
    who = create_guardian(branch=branch, full_name="Anil Sharma", phone="9876500009")
    who.user = second
    who.save(update_fields=["user"])
    link_guardian(student=child_a, guardian=who, relationship="father")

    consent_for(parent_a, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS)
    consent_for(second, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS, granted=False)

    assert selectors.student_carries(child_a, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS) is False


def test_a_guardian_with_no_account_is_not_a_refusal(
    branch, teacher, child_a, parent_a, consent_for
):
    """A guardian without a portal account cannot record consent, so their silence
    must not permanently block the child — that would be an absence read as a no."""
    from apps.people.services import create_guardian, link_guardian

    who = create_guardian(branch=branch, full_name="Sunita Devi", phone="9876500011")
    assert who.user is None
    link_guardian(student=child_a, guardian=who, relationship="grandparent")

    consent_for(parent_a, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS)

    assert selectors.student_carries(child_a, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS) is True


# --------------------------------------------------------------------------------
# Publish state and upload state both gate the feed
# --------------------------------------------------------------------------------


def test_an_unpublished_photo_never_reaches_a_parent(
    branch, teacher, child_a, parent_a, consent_for
):
    media = _stored_photo(branch, teacher)
    services.tag(media=media, student=child_a, tagged_by=teacher)
    consent_for(parent_a, ConsentPurpose.PHOTOS_IN_APP)
    consent_for(parent_a, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS)

    assert list(selectors.feed_for_child_of(parent_a, child_a.pk)[1]) == []


def test_a_pending_upload_never_reaches_a_parent(branch, teacher, child_a, parent_a, consent_for):
    """A row whose object may not have landed. Showing it gives the parent a broken
    image and no way to tell whether the photo exists."""
    media = services.register_upload(branch=branch, key="photos/pending.webp")
    assert media.upload_state == UploadState.PENDING
    services.tag(media=media, student=child_a, tagged_by=teacher)
    consent_for(parent_a, ConsentPurpose.PHOTOS_IN_APP)
    consent_for(parent_a, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS)
    services.publish_media(media=media)

    assert list(selectors.feed_for_child_of(parent_a, child_a.pk)[1]) == []


def test_unpublishing_pulls_a_photo_back_out_of_the_feed(
    branch, teacher, child_a, parent_a, consent_for
):
    """What happens when a consent is revoked after the fact."""
    media = _stored_photo(branch, teacher)
    services.tag(media=media, student=child_a, tagged_by=teacher)
    consent_for(parent_a, ConsentPurpose.PHOTOS_IN_APP)
    consent_for(parent_a, ConsentPurpose.PHOTOS_SHARED_WITH_CLASS)
    services.publish_media(media=media)

    services.unpublish_media(media=media)

    assert list(selectors.feed_for_child_of(parent_a, child_a.pk)[1]) == []
