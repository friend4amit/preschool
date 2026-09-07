"""Find and repair accounts the admin's plain-ModelAdmin bug locked out.

For four phases `/admin` registered `User` on `admin.ModelAdmin`, which renders
`password` as the ordinary CharField the model declares. An operator resetting a
parent's password there saved the RAW STRING into the hash column: the account could
never log in again, and the password sat readable in the database and in every
pg_dump taken afterwards.

The admin is fixed. This finds what it already broke.

    manage.py repair_passwords                  # report, change nothing
    manage.py repair_passwords --rehash         # keep the password, hash it properly
    manage.py repair_passwords --invalidate     # wipe it, hand out fresh links

Reports by default, like `prune_media`, and for the same reason: both flags do
something irreversible to somebody's account.

**Neither flag undoes the disclosure.** `--rehash` gets people logged in fastest and
leaves them using a password that was stored in clear text. `--invalidate` is the
right answer for anyone who might have reused that password anywhere else. Which one
applies is a judgement about real people, so the command refuses to guess.
"""

from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse

from apps.core import selectors, services


class Command(BaseCommand):
    help = "Find accounts whose password was stored unhashed, and repair them."

    def add_arguments(self, parser):
        parser.add_argument(
            "--rehash",
            action="store_true",
            help="Hash the stored value in place. The owner's password keeps working.",
        )
        parser.add_argument(
            "--invalidate",
            action="store_true",
            help="Wipe the password and print a fresh set-password link for each account.",
        )
        parser.add_argument(
            "--base-url",
            default="",
            help="Host to build set-password links against, e.g. https://aaroham.in",
        )

    def handle(self, *args, **options):
        if options["rehash"] and options["invalidate"]:
            raise CommandError("--rehash and --invalidate are opposite answers. Pick one.")

        damaged = selectors.accounts_with_plaintext_passwords()
        if not damaged:
            self.stdout.write(self.style.SUCCESS("No accounts with unhashed passwords."))
            return

        self.stdout.write(
            self.style.ERROR(f"{len(damaged)} account(s) cannot log in — password is not a hash:")
        )
        for user in damaged:
            # Never the value itself. It is somebody's password, and this output ends
            # up in terminal scrollback and CI logs.
            self.stdout.write(f"  id={user.pk:<4} {user.phone:<14} {user.full_name or '—'}")

        if not (options["rehash"] or options["invalidate"]):
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "Reporting only. --rehash keeps their password and makes it work again; "
                    "--invalidate wipes it and issues fresh links. Neither undoes the fact "
                    "that the password was readable in the database and in the backups taken "
                    "while it was there."
                )
            )
            return

        self.stdout.write("")
        for user in damaged:
            if options["rehash"]:
                services.rehash_password(user=user)
                self.stdout.write(self.style.SUCCESS(f"  rehashed   {user.phone}"))
            else:
                services.invalidate_password(user=user)
                uid, token = services.issue_set_password_token(user)
                path = reverse("set_password", kwargs={"uid": uid, "token": token})
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  wiped      {user.phone}  ->  {options['base_url']}{path}"
                    )
                )

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS("Done. Ask each person to sign in and confirm."))
