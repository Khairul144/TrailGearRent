"""Model untuk aplikasi accounts TrailGear.

Berisi:
- User         : custom user model (AbstractUser) untuk AUTH_USER_MODEL
- SecurityEvent: catatan peristiwa keamanan (login, register, rate limit, dst)

Catatan keamanan:
- Password TIDAK PERNAH disimpan/di-log di sini; Django menangani hashing
  (PBKDF2-SHA256 default) beserta salt dan verifikasi.
"""

from datetime import timedelta

from django.contrib.auth.models import AbstractUser
from django.db import models, transaction
from django.utils import timezone


class User(AbstractUser):
    """Custom user model TrailGear.

    Mewarisi seluruh mekanisme Django (password hashing, permission, group,
    is_staff/is_superuser, last_login, date_joined) lalu menambahkan:
    - email unik
    - phone_number opsional
    """

    # AbstractUser.email hanya blank=True, di sini dibuat unik.
    email = models.EmailField("email address", max_length=254, unique=True)
    phone_number = models.CharField(
        "nomor telepon",
        max_length=20,
        blank=True,
        default="",
        help_text="Opsional. Contoh: 08123456789",
    )
    address = models.TextField(
        "alamat",
        blank=True,
        default="",
        help_text="Alamat pengiriman/pengambilan. Opsional.",
    )

    # --- Account lockout (lapisan kedua setelah rate limiting) -------------
    failed_login_attempts = models.PositiveIntegerField(
        "percobaan login gagal",
        default=0,
        help_text="Jumlah kegagalan login berturut-turut. Direset saat login berhasil.",
    )
    locked_until = models.DateTimeField(
        "terkunci sampai",
        null=True,
        blank=True,
        help_text="Akun menolak login sampai waktu ini (temporary lockout).",
    )

    # --- Password expiry (adaptasi MySQL PASSWORD EXPIRE INTERVAL 30 DAY) ---
    password_changed_at = models.DateTimeField(
        "password diubah pada",
        null=True,
        blank=True,
        help_text="Dipakai untuk menghitung masa berlaku password (PASSWORD_MAX_AGE_DAYS).",
    )

    class Meta:
        verbose_name = "user"
        verbose_name_plural = "users"
        ordering = ["-date_joined"]

    def __str__(self):
        return self.username

    # --- Account lockout ---------------------------------------------------
    @property
    def is_locked(self):
        """True bila akun sedang dalam masa lockout."""
        return bool(self.locked_until and self.locked_until > timezone.now())

    def register_failed_login(self):
        """Naikkan counter secara atomik; kunci akun bila mencapai threshold.

        Return True jika akun BARU terkunci pada pemanggilan ini.
        Counter dinaikkan dengan F() expression sehingga dua request paralel
        tidak saling menimpa (hindari lost update).
        """
        from django.conf import settings
        from django.db.models import F

        with transaction.atomic():
            User.objects.filter(pk=self.pk).update(
                failed_login_attempts=F("failed_login_attempts") + 1
            )
            self.refresh_from_db(fields=["failed_login_attempts", "locked_until"])

            # Sudah terkunci -> jangan diperpanjang (hindari lock berkepanjangan).
            if self.is_locked:
                return False

            if self.failed_login_attempts >= settings.ACCOUNT_LOCKOUT_THRESHOLD:
                self.locked_until = timezone.now() + timedelta(
                    minutes=settings.ACCOUNT_LOCKOUT_DURATION
                )
                User.objects.filter(pk=self.pk).update(locked_until=self.locked_until)
                return True
        return False

    def reset_login_lock(self):
        """Reset counter dan lepaskan lock (dipanggil saat login berhasil)."""
        User.objects.filter(pk=self.pk).update(
            failed_login_attempts=0, locked_until=None
        )
        self.failed_login_attempts = 0
        self.locked_until = None

    # --- Password expiry ---------------------------------------------------
    def set_password(self, raw_password):
        """Hash password lewat Django, sekaligus catat waktu perubahan."""
        super().set_password(raw_password)
        self.password_changed_at = timezone.now()

    def save(self, *args, **kwargs):
        """Pastikan password_changed_at terisi untuk jalur yang melewati save().

        `User.objects.create_user()` / `create_superuser()` mengisi kolom
        password langsung (tanpa set_password), jadi timestamp distempel di
        sini. Tidak menimpa nilai yang sudah ada.
        """
        update_fields = kwargs.get("update_fields")
        if self.password_changed_at is None and self.password:
            self.password_changed_at = timezone.now()
            if update_fields is not None:
                kwargs["update_fields"] = set(update_fields) | {"password_changed_at"}
        super().save(*args, **kwargs)

    @property
    def password_expired(self):
        """True bila umur password melebihi PASSWORD_MAX_AGE_DAYS."""
        from django.conf import settings

        if self.password_changed_at is None:
            # User lama tanpa data historis: jangan dipaksa ganti.
            return False
        batas = timedelta(days=settings.PASSWORD_MAX_AGE_DAYS)
        return (timezone.now() - self.password_changed_at) > batas

    @property
    def password_expires_at(self):
        from django.conf import settings

        if self.password_changed_at is None:
            return None
        return self.password_changed_at + timedelta(days=settings.PASSWORD_MAX_AGE_DAYS)

    @property
    def display_name(self):
        full = f"{self.first_name} {self.last_name}".strip()
        return full or self.username


class SecurityEvent(models.Model):
    """Audit log peristiwa keamanan.

    Tidak boleh menyimpan password, password_confirmation, session id,
    token, atau SECRET_KEY.
    """

    REGISTER_SUCCESS = "REGISTER_SUCCESS"
    REGISTER_FAILED = "REGISTER_FAILED"
    LOGIN_SUCCESS = "LOGIN_SUCCESS"
    LOGIN_FAILED = "LOGIN_FAILED"
    LOGOUT = "LOGOUT"
    RATE_LIMIT_REGISTER = "RATE_LIMIT_REGISTER"
    RATE_LIMIT_LOGIN = "RATE_LIMIT_LOGIN"
    PASSWORD_CHANGED = "PASSWORD_CHANGED"
    ACCOUNT_DISABLED = "ACCOUNT_DISABLED"
    ACCESS_DENIED = "ACCESS_DENIED"
    ACCOUNT_LOCKED = "ACCOUNT_LOCKED"
    PAYMENT_PROOF_UPLOADED = "PAYMENT_PROOF_UPLOADED"
    PAYMENT_PROOF_REJECTED = "PAYMENT_PROOF_REJECTED"

    EVENT_CHOICES = [
        (REGISTER_SUCCESS, "Register berhasil"),
        (REGISTER_FAILED, "Register gagal"),
        (LOGIN_SUCCESS, "Login berhasil"),
        (LOGIN_FAILED, "Login gagal"),
        (LOGOUT, "Logout"),
        (RATE_LIMIT_REGISTER, "Rate limit register"),
        (RATE_LIMIT_LOGIN, "Rate limit login"),
        (PASSWORD_CHANGED, "Password diubah"),
        (ACCOUNT_DISABLED, "Akun dinonaktifkan"),
        (ACCESS_DENIED, "Akses ditolak"),
        (ACCOUNT_LOCKED, "Akun terkunci sementara"),
        (PAYMENT_PROOF_UPLOADED, "Bukti pembayaran diunggah"),
        (PAYMENT_PROOF_REJECTED, "Berkas bukti pembayaran ditolak"),
    ]

    STATUS_SUCCESS = "SUCCESS"
    STATUS_FAILURE = "FAILURE"
    STATUS_BLOCKED = "BLOCKED"

    STATUS_CHOICES = [
        (STATUS_SUCCESS, "Success"),
        (STATUS_FAILURE, "Failure"),
        (STATUS_BLOCKED, "Blocked"),
    ]

    user = models.ForeignKey(
        "accounts.User",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="security_events",
    )
    event_type = models.CharField(max_length=32, choices=EVENT_CHOICES, db_index=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, db_index=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True, default="")
    description = models.TextField(blank=True, default="")
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "security event"
        verbose_name_plural = "security events"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["event_type", "-timestamp"]),
            models.Index(fields=["ip_address", "-timestamp"]),
        ]

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M:%S} {self.event_type} {self.status}"
