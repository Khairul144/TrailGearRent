"""Middleware password expiry (adaptasi MySQL PASSWORD EXPIRE INTERVAL 30 DAY).

User yang password-nya sudah melewati PASSWORD_MAX_AGE_DAYS hanya boleh:
- mengakses halaman ganti password,
- logout,
- aset statis.

Semua request lain dialihkan ke halaman ganti password. Middleware ini TIDAK
menyentuh user anonim, dan tidak mengubah mekanisme authentication lain
(rate limiting, lockout, RBAC).
"""

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse


class PasswordExpiryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response
        self.change_path = reverse("accounts:password_change")

    def __call__(self, request):
        user = getattr(request, "user", None)

        if (
            user is not None
            and user.is_authenticated
            and not self._is_allowed(request)
            and user.password_expired
        ):
            return redirect(f"{self.change_path}?expired=1")

        return self.get_response(request)

    def _is_allowed(self, request):
        path = request.path

        # Aset statis tidak boleh dialihkan.
        if path.startswith(settings.STATIC_URL) or path.startswith("/static/"):
            return True

        # Halaman ganti password itu sendiri.
        if path == self.change_path or path.startswith(self.change_path):
            return True

        # Proses yang dibutuhkan: login/logout/registrasi.
        if path.startswith(("/login/", "/logout/", "/register/")):
            return True

        # Django admin: hanya ganti password & logout yang diizinkan.
        if path.startswith("/admin/password_change/") or path == "/admin/logout/":
            return True

        return False
