"""Delete photographs of children — carefully, and only when asked twice.

Three jobs that share one safety property, which is why they share one command:

    --retention          the DPDP sweep. Photos past MEDIA_RETENTION_DAYS.
    --student <id>       one family's erasure request.
    --orphans            bucket objects with no row (needs R2 configured).

**It reports and changes nothing unless you pass `--commit`.** That is the wrong
default for most commands and the right one for this: everything here is irreversible
and the subject is a photograph of a child. Read the list, then run it again.

A management command rather than a task for the same reason as `backup_database`: the
thing that would schedule the retention sweep is cron on the VPS, and cron cannot
enqueue. The erasure and orphan paths are not scheduled at all — a person runs them.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.activities import services
from apps.people.models import Student
from integrations import storage_r2


class Command(BaseCommand):
    help = "Report — or, with --commit, delete — photographs past retention or on request."

    def add_arguments(self, parser):
        parser.add_argument(
            "--retention",
            action="store_true",
            help="Sweep photographs past the retention window.",
        )
        parser.add_argument(
            "--student",
            type=int,
            help="Erase one child's photographs and activity entries (their id).",
        )
        parser.add_argument(
            "--orphans",
            action="store_true",
            help="List bucket objects with no database row. Requires R2.",
        )
        parser.add_argument(
            "--window-days",
            type=int,
            help="Override MEDIA_RETENTION_DAYS for this run.",
        )
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Actually delete. Without this the command only reports.",
        )

    def handle(self, *args, **options):
        jobs = [
            bool(options["retention"]),
            options["student"] is not None,
            bool(options["orphans"]),
        ]
        if sum(jobs) != 1:
            raise CommandError("Pass exactly one of --retention, --student <id> or --orphans.")

        commit = options["commit"]
        if not commit:
            self.stdout.write(
                self.style.WARNING("Dry run — nothing will be deleted. Add --commit to proceed.")
            )

        if options["retention"]:
            self._retention(window_days=options["window_days"], commit=commit)
        elif options["student"] is not None:
            self._student(student_id=options["student"], commit=commit)
        else:
            self._orphans(commit=commit)

    # --- the three jobs -----------------------------------------------------------

    def _retention(self, *, window_days, commit):
        result = services.prune_expired_media(window_days=window_days, commit=commit)
        self.stdout.write(f"Retention window: {result['window_days']} days.")
        self._report(result["media_deleted"], result["objects_removed"], commit)

    def _student(self, *, student_id, commit):
        student = Student.objects.filter(pk=student_id).first()
        if student is None:
            raise CommandError(f"No student with id {student_id}.")

        result = services.erase_student_media(student=student, commit=commit)
        self.stdout.write(f"Child: {student} (id {student.pk}).")
        self.stdout.write(f"  tags to remove:            {result['tags_removed']}")
        self.stdout.write(f"  activity entries to drop:  {result['entries_deleted']}")
        # The multi-child rule stated where the operator will actually read it.
        if result["media_kept"]:
            self.stdout.write(
                f"  photographs KEPT ({len(result['media_kept'])}) — other children are also "
                f"tagged in them: {result['media_kept']}"
            )
        self.stdout.write(
            self.style.WARNING(
                "  incident reports are NOT erased — a safety record the school may be "
                "required to hold. Raise it with them if this request covers those too."
            )
        )
        self._report(result["media_deleted"], result["objects_removed"], commit)

    def _orphans(self, *, commit):
        if not storage_r2.is_configured():
            raise CommandError("R2 is not configured; there is no bucket to compare against.")

        keys = services.orphan_objects()
        if not keys:
            self.stdout.write(self.style.SUCCESS("No orphan objects."))
            return
        self.stdout.write(f"{len(keys)} object(s) in the bucket with no row:")
        for key in keys:
            self.stdout.write(f"  {key}")
        result = services.delete_objects(keys=keys, commit=commit)
        self._report([], result["objects_removed"], commit)

    # --- shared reporting ---------------------------------------------------------

    def _report(self, media_ids, object_keys, commit):
        verb = "Deleted" if commit else "Would delete"
        self.stdout.write(f"{verb} {len(media_ids)} photograph row(s).")
        self.stdout.write(f"{verb} {len(object_keys)} stored object(s).")
        for key in object_keys:
            self.stdout.write(f"  {key}")
        if commit:
            self.stdout.write(self.style.SUCCESS("Done."))
