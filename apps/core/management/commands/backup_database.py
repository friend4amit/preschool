"""Run the nightly backup from cron, or by hand before a risky migration.

A command rather than only a task, because the thing that schedules it is cron on
the VPS, and cron cannot enqueue. The task exists for the day something in the app
wants to trigger one; this is the entrypoint that actually runs nightly.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.core import backups
from integrations import postgres, storage_r2


class Command(BaseCommand):
    help = "Dump the database to R2 and prune backups past the retention window."

    def add_arguments(self, parser):
        parser.add_argument(
            "--list",
            action="store_true",
            help="Show what is already in the bucket instead of writing a new dump.",
        )

    def handle(self, *args, **options):
        if not storage_r2.is_configured():
            raise CommandError(
                "R2 is not configured, so there is nowhere to put the backup. "
                "Set R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET and "
                "R2_ENDPOINT_URL in .env."
            )

        if options["list"]:
            return self._list()

        try:
            key = backups.run_backup()
        except (postgres.DumpFailed, storage_r2.NotConfigured) as failure:
            raise CommandError(str(failure)) from failure

        self.stdout.write(self.style.SUCCESS(f"Wrote {key}"))

    def _list(self):
        from django.conf import settings

        from integrations.storage_r2 import objects

        found = objects(prefix=settings.BACKUP_PREFIX)
        if not found:
            self.stdout.write("No backups in the bucket yet.")
            return
        for obj in found:
            size_mb = obj.size / 1_048_576
            self.stdout.write(f"{obj.last_modified:%Y-%m-%d %H:%M}  {size_mb:7.1f} MB  {obj.key}")
