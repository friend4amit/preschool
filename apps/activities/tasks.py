"""Background entrypoints for the day and the photographs.

Three lines each: pull arguments, call a service. Web requests and background work
then run identical code paths, which is why the worker needs no separate testing
strategy — see apps/core/tasks.py, which established the shape.
"""

from django_tasks import task

from apps.activities import services
from apps.activities.models import MediaAsset


@task()
def build_thumbnail_task(*, media_id: int) -> str:
    """Downscale one stored photograph for the feed grid.

    A row that has vanished between enqueue and run is not an error — an erasure
    request or the retention sweep can legitimately delete a photograph while its
    thumbnail job is still in the queue.
    """
    media = MediaAsset.objects.filter(pk=media_id).first()
    if media is None:
        return ""
    return services.build_thumbnail(media=media).thumbnail_key


@task()
def reconcile_uploads_task() -> dict:
    """Confirm PENDING rows against the bucket. Nightly, scheduled by cron on the VPS
    calling `manage.py` — django-tasks has no scheduler and inventing one is how a
    background queue becomes a distributed system."""
    return services.reconcile_uploads()
