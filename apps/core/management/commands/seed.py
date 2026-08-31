from django.core.management.base import BaseCommand
from django.db import transaction

from apps.core.models import Organization, Role, User
from apps.core.services import create_branch, grant_membership


class Command(BaseCommand):
    help = "Seed one Organization, one Branch, and a superadmin. Idempotent."

    def add_arguments(self, parser):
        parser.add_argument("--phone", default="9000000000")
        parser.add_argument("--password", default="aaroham")

    @transaction.atomic
    def handle(self, *args, **options):
        org, _ = Organization.objects.get_or_create(slug="aaroham", defaults={"name": "Aaroham"})
        branch = org.branches.first() or create_branch(
            organization=org, name="Aaroham — Main", slug="main"
        )

        user = User.objects.filter(phone=options["phone"]).first()
        if user is None:
            user = User.objects.create_superuser(
                phone=options["phone"], password=options["password"], full_name="Operator"
            )
            self.stdout.write(self.style.SUCCESS(f"Created superadmin {user.phone}"))

        grant_membership(user=user, branch=branch, role=Role.SUPERADMIN)
        self.stdout.write(self.style.SUCCESS(f"Seeded {org.name} / {branch.name}"))
