"""Seed the public site's content.

The programme names come from the reference site; the age bands follow the usual
Indian convention and are MARKED FOR CONFIRMATION in the summary text, because
getting an admission age wrong on a public page is the kind of error a parent
notices before the school does.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.selectors import current_branch_fallback
from apps.website.models import Program, SiteSettings, TeamMember

PROGRAMS = [
    ("Playgroup", 18, 30, "First days away from home, at a gentle pace."),
    ("Nursery", 30, 42, "Routine, rhythm, and the beginnings of friendship."),
    ("LKG", 42, 54, "Pre-literacy and pre-numeracy through play."),
    ("UKG", 54, 66, "Readiness for school, without rushing childhood."),
    ("Daycare & Afterschool", 18, 120, "Extended care, homework support, and quiet time."),
]


# The team.
#
# Prachi's card carries over from the reference site — docs/implementation-plan.md
# says so explicitly, and the copy below is HER OWN, edited only to drop the old
# school's name. Her portrait is attached by `seed_media`, which is where every
# image out of that dump is handled; this command owns text.
#
# The reference site's second card was Dr. Surashree Shome, and it is NOT here.
# She is removed entirely, per the plan, and `seed_media` blocks her photograph by
# filename so it cannot arrive by another route.
#
# Preevi's entry is deliberately thin: name and role only, because nobody has given
# us her bio and inventing one for a real person is not a thing to ship. The card
# renders without a photograph — it falls back to an initial — so the page is
# correct today and better the moment someone writes two sentences.
TEAM = [
    (
        "Prachi Tamrakar",
        "Founder & Director",
        "NTT qualified · Cambridge Early Years educator",
        "Prachi is a mother first and then a trained early childhood educator. With an "
        "NTT qualification, volunteer experience across private and public kindergarten "
        "classrooms in the United States, and professional experience as a Cambridge "
        "Early Years educator at a leading world school in Bangalore, she brings a "
        "global perspective to early childhood education. Known for her natural ability "
        "to connect with children quickly, she holds a deep calling to protect childhood "
        "from growing screen dependency and the gradual loss of imagination, by creating "
        "spaces where children can explore, create, and experience joyful, real-world "
        "learning.",
    ),
    (
        "Preevi",
        "Co-founder",
        "",
        "",
    ),
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

        for order, (name, role, credentials, bio) in enumerate(TEAM):
            # Matched on name, so re-running never creates a second Prachi — and
            # never overwrites a photograph seed_media has already attached, because
            # `photo` is not in defaults.
            TeamMember.objects.update_or_create(
                branch=branch,
                name=name,
                defaults={
                    "role": role,
                    "credentials": credentials,
                    "bio": bio,
                    "order": order,
                    "is_published": True,
                },
            )

        self.stdout.write(self.style.SUCCESS(f"Seeded {len(PROGRAMS)} programmes for {branch}"))
        self.stdout.write(self.style.SUCCESS(f"Seeded {len(TEAM)} team members for {branch}"))
        self.stdout.write(
            self.style.WARNING(
                "CONFIRM BEFORE LAUNCH: programme age bands are conventional defaults, "
                "address/phone/email in SiteSettings are empty, and Preevi's card has "
                "only a name and a role — no surname, credentials, bio or photograph."
            )
        )
        self.stdout.write(f"  Edit them at /admin/website/ — settings id {settings_obj.pk}")
