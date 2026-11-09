"""Authentication backend: login dengan username ATAU email.

Django default hanya menerima username. Backend ini mencari user berdasarkan
username (case-insensitive) atau email (case-insensitive). Pesan error tetap
generik di layer view agar tidak terjadi user enumeration.

Password selalu diverifikasi oleh Django (`check_password`) — tidak ada
perbandingan plaintext.
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db.models import Q


class EmailOrUsernameBackend(ModelBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()

        if username is None:
            username = kwargs.get(UserModel.USERNAME_FIELD)
        if not username or password is None:
            return None

        identifier = username.strip()
        if not identifier:
            return None

        user = (
            UserModel._default_manager.filter(
                Q(username__iexact=identifier) | Q(email__iexact=identifier)
            )
            .order_by("id")
            .first()
        )

        if user is None:
            # Kurangi perbedaan waktu respons antara "user tidak ada" dan
            # "password salah" (mitigasi timing-based user enumeration).
            UserModel().set_password(password)
            return None

        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
