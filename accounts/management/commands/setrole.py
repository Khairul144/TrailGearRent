"""Set role user TrailGear lewat terminal.

Contoh:
    python manage.py setrole ujicoba Admin
    python manage.py setrole rina Cashier
    python manage.py setrole budi Customer --add
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from accounts.roles import ALL_ROLES, ROLE_ADMIN, assign_role, ensure_roles, primary_role

User = get_user_model()


class Command(BaseCommand):
    help = "Set role (Customer/Cashier/Admin) untuk satu user."

    def add_arguments(self, parser):
        parser.add_argument("username", help="Username target")
        parser.add_argument("role", choices=list(ALL_ROLES), help="Role yang diberikan")
        parser.add_argument(
            "--add",
            action="store_true",
            help="Tambahkan role tanpa mencabut role lain (default: mengganti role utama)",
        )

    def handle(self, *args, **options):
        ensure_roles()

        username = options["username"]
        role = options["role"]

        user = User.objects.filter(username__iexact=username).first()
        if user is None:
            raise CommandError(f"User {username!r} tidak ditemukan.")

        assign_role(user, role, exclusive=not options["add"])

        # Hanya Admin yang diberi akses Django Admin (is_staff).
        if role == ROLE_ADMIN:
            user.is_staff = True
            user.save(update_fields=["is_staff"])

        self.stdout.write(
            self.style.SUCCESS(
                f"{user.username}: role utama sekarang {primary_role(user)} "
                f"(is_staff={user.is_staff})"
            )
        )
