"""Background entrypoints. Three lines each: pull arguments, call a service.

Web requests and background work then run identical code paths, which is why the
worker needs no separate testing strategy.
"""

from django_tasks import task

from apps.core import services
from apps.core.models import Branch, ConsentPurpose, User


@task()
def record_consent_task(*, guardian_id: int, branch_id: int, purpose: str, granted: bool) -> int:
    consent = services.record_consent(
        guardian=User.objects.get(pk=guardian_id),
        branch=Branch.objects.get(pk=branch_id),
        purpose=ConsentPurpose(purpose),
        granted=granted,
    )
    return consent.pk
