"""Seed the public site's content.

The programme names come from the reference site; the age bands follow the usual
Indian convention and are MARKED FOR CONFIRMATION in the summary text, because
getting an admission age wrong on a public page is the kind of error a parent
notices before the school does.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.selectors import current_branch_fallback
from apps.website.models import Program, SiteSettings

PROGRAMS = [
    ("Playgroup", 18, 30, "First days away from home, at a gentle pace."),
    ("Nursery", 30, 42, "Routine, rhythm, and the beginnings of friendship."),
    ("LKG", 42, 54, "Pre-literacy and pre-numeracy through play."),
    ("UKG", 54, 66, "Readiness for school, without rushing childhood."),
    ("Daycare & Afterschool", 18, 120, "Extended care, homework support, and quiet time."),
]


class Command(BaseCommand):
    help = "Seed programmes and site settings for the public website. Idempotent."

    @transaction.atomic
    def handle(self, *args, **options):
        branch = current_branch_fallback()
        if branch is None:
            self.stderr.write(self.style.ERROR("No Branch found. Run `manage.py seed` first."))
            return

        settings_obj, _ = SiteSettings.objects.get_or_create(
            branch=branch,
            defaults={
                "tagline": "Pure beginnings. Thoughtful learning.",
                # CONFIRM before launch — carried over from the reference site.
                "email": "hello@aaroham.example",
                "address": "",
                "phone": "",
            },
        )

        for order, (name, lo, hi, summary) in enumerate(PROGRAMS):
            Program.objects.update_or_create(
                branch=branch,
                slug=name.lower().replace(" & ", "-").replace(" ", "-"),
                defaults={
                    "name": name,
                    "age_from_months": lo,
                    "age_to_months": hi,
                    "summary": summary,
                    "order": order,
                    "is_published": True,
                },
            )

        self.stdout.write(self.style.SUCCESS(f"Seeded {len(PROGRAMS)} programmes for {branch}"))
        self.stdout.write(
            self.style.WARNING(
                "CONFIRM BEFORE LAUNCH: programme age bands are conventional defaults, "
                "and address/phone/email in SiteSettings are empty."
            )
        )
        self.stdout.write(f"  Edit them at /admin/website/ — settings id {settings_obj.pk}")
