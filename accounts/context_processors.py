"""Context processor: sediakan role user & konfigurasi keamanan di template.

Dipakai untuk menampilkan menu yang sesuai (mis. "Dashboard Admin" hanya
untuk role Admin) tanpa menambahkan context manual di setiap view.
"""

from django.conf import settings

from .roles import primary_role


def roles(request):
    user = getattr(request, "user", None)
    base = {
        "PASSWORD_MAX_AGE_DAYS": settings.PASSWORD_MAX_AGE_DAYS,
    }

    if user is None or not user.is_authenticated:
        base.update({"user_role": None, "is_staff_role": False})
        return base

    role = primary_role(user)
    base.update(
        {
            "user_role": role,
            "is_staff_role": role in ("Admin", "Cashier") or user.is_superuser,
        }
    )
    return base
