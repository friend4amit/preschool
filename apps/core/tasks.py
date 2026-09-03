"""Background entrypoints. Three lines each: pull arguments, call a service.

Web requests and background work then run identical code paths, which is why the
worker needs no separate testing strategy.
"""

from django_tasks import task

from apps.core import backups, services
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


@task()
def nightly_backup() -> str:
    """pg_dump to R2, and prune anything past the retention window.

    Three lines, like every other entrypoint here. Scheduling is the deployment's
    job — a cron entry on the VPS calling `manage.py backup_database` — rather than
    something this codebase tries to own, because django-tasks has no scheduler and
    inventing one is how a background queue becomes a distributed system.
    """
    return backups.run_backup()
