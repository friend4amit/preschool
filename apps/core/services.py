"""Business logic. Plain functions that take arguments, return objects, own their
transactions, and know nothing about HTTP.

This is the layer a future django-ninja API calls, which is why adding mobile later
is mechanical rather than archaeological. It is also the layer that is pleasant to
unit-test: every test below constructs no HttpRequest.
"""

from django.contrib.auth.tokens import default_token_generator
from django.db import transaction
from django.utils import timezone
from django.utils.encoding import DjangoUnicodeDecodeError, force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from apps.core.models import Branch, BranchMembership, Consent, ConsentPurpose, Organization, User


@transaction.atomic
def create_branch(*, organization: Organization, name: str, slug: str, **fields) -> Branch:
    return Branch.objects.create(organization=organization, name=name, slug=slug, **fields)


@transaction.atomic
def grant_membership(*, user: User, branch: Branch, role: str) -> BranchMembership:
    membership, _ = BranchMembership.objects.get_or_create(user=user, branch=branch, role=role)
    return membership


@transaction.atomic
def record_consent(
    *,
    guardian: User,
    branch: Branch,
    purpose: ConsentPurpose,
    granted: bool,
    recorded_by: User | None = None,
) -> Consent:
    """Record a guardian's answer to one consent question.

    Re-answering bumps the version rather than overwriting: what was consented to,
    and when, has to survive being changed. Revoking stamps revoked_at so the record
    shows a withdrawal rather than an absence.
    """
    consent = (
        Consent.objects.select_for_update()
        .filter(guardian=guardian, branch=branch, purpose=purpose)
        .first()
    ) or Consent(guardian=guardian, branch=branch, purpose=purpose, version=0)

    consent.version += 1
    consent.granted = granted
    consent.recorded_by = recorded_by
    if granted:
        consent.granted_at = timezone.now()
        consent.revoked_at = None
    else:
        consent.revoked_at = timezone.now()

    # Exactly one save, so exactly one history row per answer. get_or_create with a
    # follow-up save would write two on the first answer and leave the audit trail
    # showing a change nobody made.
    consent.save()
    return consent


@transaction.atomic
def create_account(
    *, phone: str, full_name: str = "", email: str = "", branch: Branch, role: str
) -> User:
    """Create a login for a parent or a member of staff. There is no signup page.

    The account starts with an *unusable* password rather than a temporary one: a
    temporary password is a shared secret that gets forwarded, written down and
    reused. The admin hands over a one-time link instead — see
    `issue_set_password_token`.

    Idempotent on phone, because the office will click the button twice.
    """
    user, created = User.objects.get_or_create(
        phone=phone.strip(), defaults={"full_name": full_name.strip(), "email": email.strip()}
    )
    if created:
        user.set_unusable_password()
        user.save(update_fields=["password"])
    elif full_name and not user.full_name:
        user.full_name = full_name.strip()
        user.save(update_fields=["full_name"])

    grant_membership(user=user, branch=branch, role=role)
    return user


def issue_set_password_token(user: User) -> tuple[str, str]:
    """The one-time, signed, expiring credential behind a set-password link.

    Returns `(uid, token)` and not a URL: building a URL needs `reverse`, which is
    HTTP, which does not belong at this layer. The view assembles the link.

    One-time-ness is not a flag we maintain. Django's token generator hashes the
    user's current password hash and `last_login` into the token, so the moment a
    password is set the token stops validating — no state to clean up, and no window
    where a forwarded link still works. Expiry is `PASSWORD_RESET_TIMEOUT`.
    """
    return (
        urlsafe_base64_encode(force_bytes(user.pk)),
        default_token_generator.make_token(user),
    )


def resolve_set_password_token(uid: str, token: str) -> User | None:
    """The user a link belongs to, or None if it is spent, expired or forged.

    None covers every failure on purpose. Telling the holder of a bad link *why*
    it failed tells them whether the account exists.
    """
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uid)))
    except (User.DoesNotExist, ValueError, TypeError, DjangoUnicodeDecodeError):
        return None
    return user if default_token_generator.check_token(user, token) else None


@transaction.atomic
def set_password(*, user: User, raw_password: str) -> User:
    """Spends the link: changing the hash is what invalidates the token."""
    user.set_password(raw_password)
    user.save(update_fields=["password"])
    return user
