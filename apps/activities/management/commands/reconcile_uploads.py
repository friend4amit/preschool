"""Settle PENDING photographs against the bucket. The nightly one.

A management command rather than only a task for the same reason as
`backup_database`: the thing that runs this on a timer is cron on the VPS, and cron
cannot enqueue. It calls the service directly, so it works whether or not a worker is
up — which is what you want from the job whose whole purpose is fixing half-finished
work.

Unlike `prune_media`, this one is safe to run unattended: it promotes rows whose
object landed and marks failed the ones whose object never did. It deletes nothing.
"""

from django.core.management.base import BaseCommand

from apps.activities import services


class Command(BaseCommand):
    help = "Confirm pending photo uploads against storage. Promotes or marks failed."

    def add_arguments(self, parser):
        parser.add_argument(
            "--older-than-minutes",
            type=int,
            default=60,
            help="Leave rows younger than this alone; an upload may still be in flight.",
        )

    def handle(self, *args, **options):
        result = services.reconcile_uploads(older_than_minutes=options["older_than_minutes"])
        self.stdout.write(f"Promoted to stored: {result['promoted']}")
        self.stdout.write(f"Marked failed:      {result['failed']}")
