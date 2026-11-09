"""Test suite authentication TrailGear.

Fokus: kebijakan password, registrasi, login/logout, rate limiting, CSRF,
SQL injection, XSS, authorization, dan session handling.

Jalankan:  python manage.py test accounts -v 2
"""

import re
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import SecurityEvent

User = get_user_model()

GOOD_PASSWORD = "Kuat!Sekali2026"
LOCMEM = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
        "LOCATION": "trailgear-tests",
    }
}


@override_settings(CACHES=LOCMEM)
class BaseAuthTest(TestCase):
    def setUp(self):
        cache.clear()

    def make_user(self, username="pendaki", email=None, password=GOOD_PASSWORD, **extra):
        return User.objects.create_user(
            username=username,
            email=email or f"{username}@example.com",
            password=password,
            **extra,
        )

    def register_payload(self, **overrides):
        data = {
            "first_name": "Budi",
            "last_name": "Santoso",
            "username": "budisan",
            "email": "budi@example.com",
            "phone_number": "081234567890",
            "password": GOOD_PASSWORD,
            "password_confirmation": GOOD_PASSWORD,
        }
        data.update(overrides)
        return data


class RegistrationTests(BaseAuthTest):
    def test_register_success_creates_user_and_logs_in(self):
        response = self.client.post(reverse("accounts:register"), self.register_payload())

        self.assertRedirects(response, reverse("home"))
        user = User.objects.get(username="budisan")
        self.assertEqual(user.email, "budi@example.com")
        self.assertEqual(user.phone_number, "081234567890")
        self.assertEqual(user.first_name, "Budi")
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        # Password di-hash Django, bukan plaintext.
        self.assertNotEqual(user.password, GOOD_PASSWORD)
        self.assertTrue(user.password.startswith("pbkdf2_sha256$"))
        self.assertTrue(user.check_password(GOOD_PASSWORD))
        # Langsung terautentikasi
        self.assertEqual(int(self.client.session["_auth_user_id"]), user.pk)
        # Security event tercatat
        self.assertTrue(
            SecurityEvent.objects.filter(
                event_type=SecurityEvent.REGISTER_SUCCESS, user=user
            ).exists()
        )

    def test_registration_does_not_store_password_in_security_log(self):
        self.client.post(reverse("accounts:register"), self.register_payload())
        dumped = " ".join(SecurityEvent.objects.values_list("description", flat=True))
        self.assertNotIn(GOOD_PASSWORD, dumped)

    def test_password_and_confirmation_not_saved_to_model(self):
        self.client.post(reverse("accounts:register"), self.register_payload())
        user = User.objects.get(username="budisan")
        self.assertFalse(hasattr(user, "password_confirmation"))
        self.assertNotIn(GOOD_PASSWORD, user.__dict__.values())

    def test_duplicate_username_rejected(self):
        self.make_user(username="budisan", email="lain@example.com")
        response = self.client.post(reverse("accounts:register"), self.register_payload())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.filter(username__iexact="budisan").count(), 1)
        self.assertContains(response, "sudah digunakan")

    def test_duplicate_username_case_insensitive(self):
        self.make_user(username="BudiSan", email="lain@example.com")
        response = self.client.post(
            reverse("accounts:register"), self.register_payload(username="budisan")
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.count(), 1)

    def test_duplicate_email_rejected(self):
        self.make_user(username="lain", email="budi@example.com")
        response = self.client.post(reverse("accounts:register"), self.register_payload())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "sudah terdaftar")
        self.assertEqual(User.objects.count(), 1)

    def test_invalid_email_rejected(self):
        response = self.client.post(
            reverse("accounts:register"), self.register_payload(email="bukan-email")
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.exists())

    def test_non_gmail_email_accepted(self):
        response = self.client.post(
            reverse("accounts:register"),
            self.register_payload(email="budi@contoh.co.id"),
        )
        self.assertRedirects(response, reverse("home"))

    def test_phone_number_optional(self):
        response = self.client.post(
            reverse("accounts:register"), self.register_payload(phone_number="")
        )
        self.assertRedirects(response, reverse("home"))
        self.assertEqual(User.objects.get(username="budisan").phone_number, "")

    def test_invalid_phone_number_rejected(self):
        response = self.client.post(
            reverse("accounts:register"), self.register_payload(phone_number="abc")
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.exists())

    def _assert_password_rejected(self, password, confirmation=None):
        response = self.client.post(
            reverse("accounts:register"),
            self.register_payload(
                password=password,
                password_confirmation=password if confirmation is None else confirmation,
            ),
        )
        self.assertEqual(
            response.status_code, 200, f"password {password!r} seharusnya ditolak"
        )
        self.assertFalse(User.objects.exists(), f"password {password!r} lolos validasi")

    def test_password_too_short(self):
        self._assert_password_rejected("Aa1!")

    def test_password_without_uppercase(self):
        self._assert_password_rejected("trail1!gear")

    def test_password_without_lowercase(self):
        self._assert_password_rejected("TRAIL1!GEAR")

    def test_password_without_digit(self):
        self._assert_password_rejected("TrailGear!!")

    def test_password_without_symbol(self):
        self._assert_password_rejected("TrailGear12")

    def test_common_password_rejected(self):
        from django.contrib.auth import password_validation
        from django.core.exceptions import ValidationError

        with self.assertRaises(ValidationError) as ctx:
            password_validation.validate_password("password123", None)
        self.assertIn("password_too_common", [e.code for e in ctx.exception.error_list])
        self.assertIn(
            "django.contrib.auth.password_validation.CommonPasswordValidator",
            [v["NAME"] for v in settings.AUTH_PASSWORD_VALIDATORS],
        )

    def test_numeric_only_password_rejected(self):
        self._assert_password_rejected("1234567890!")

    def test_password_too_long_rejected(self):
        self._assert_password_rejected("Aa1!" + "x" * 130)

    def test_password_similar_to_username_rejected(self):
        self._assert_password_rejected("Budisan123!")

    def test_confirmation_mismatch_rejected(self):
        self._assert_password_rejected(GOOD_PASSWORD, confirmation="Trail!Gear2027")

    def test_registration_rate_limited_after_three_attempts(self):
        for _ in range(3):
            self.client.post(
                reverse("accounts:register"), self.register_payload(username="x!")
            )
        response = self.client.post(
            reverse("accounts:register"), self.register_payload(username="x!")
        )
        self.assertEqual(response.status_code, 429)
        self.assertTrue(
            SecurityEvent.objects.filter(
                event_type=SecurityEvent.RATE_LIMIT_REGISTER
            ).exists()
        )
        self.assertFalse(User.objects.exists())


class LoginTests(BaseAuthTest):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()

    def test_login_with_username(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "pendaki", "password": GOOD_PASSWORD},
        )
        self.assertRedirects(response, reverse("home"))
        self.assertTrue(
            SecurityEvent.objects.filter(
                event_type=SecurityEvent.LOGIN_SUCCESS, user=self.user
            ).exists()
        )

    def test_login_with_email(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "pendaki@example.com", "password": GOOD_PASSWORD},
        )
        self.assertRedirects(response, reverse("home"))

    def test_login_with_email_case_insensitive(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "PENDAKI@Example.com", "password": GOOD_PASSWORD},
        )
        self.assertRedirects(response, reverse("home"))

    def test_wrong_password_generic_message(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "pendaki", "password": "Salah!Banget1"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "tidak valid")
        self.assertFalse(response.wsgi_request.user.is_authenticated)

    def test_unknown_user_gives_same_message(self):
        wrong_pw = self.client.post(
            reverse("accounts:login"),
            {"username": "pendaki", "password": "Salah!Banget1"},
        )
        unknown = self.client.post(
            reverse("accounts:login"),
            {"username": "tidakada", "password": "Salah!Banget1"},
        )
        content_a = wrong_pw.content.decode()
        content_b = unknown.content.decode()
        # Pesan sama -> tidak ada user enumeration lewat pesan.
        self.assertIn("Username/email atau password tidak valid.", content_a)
        self.assertIn("Username/email atau password tidak valid.", content_b)
        self.assertNotIn("tidak ditemukan", content_b.lower())

    def test_inactive_user_cannot_login_and_event_logged(self):
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])

        response = self.client.post(
            reverse("accounts:login"),
            {"username": "pendaki", "password": GOOD_PASSWORD},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        self.assertTrue(
            SecurityEvent.objects.filter(
                event_type=SecurityEvent.ACCOUNT_DISABLED, user=self.user
            ).exists()
        )

    def test_login_rate_limited_after_five_failures(self):
        for _ in range(5):
            self.client.post(
                reverse("accounts:login"),
                {"username": "pendaki", "password": "Salah!Banget1"},
            )
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "pendaki", "password": GOOD_PASSWORD},
        )
        self.assertEqual(response.status_code, 429)
        self.assertTrue(
            SecurityEvent.objects.filter(
                event_type=SecurityEvent.RATE_LIMIT_LOGIN
            ).exists()
        )

    def test_login_failed_event_logged(self):
        self.client.post(
            reverse("accounts:login"),
            {"username": "pendaki", "password": "Salah!Banget1"},
        )
        event = SecurityEvent.objects.filter(event_type=SecurityEvent.LOGIN_FAILED).first()
        self.assertIsNotNone(event)
        self.assertNotIn("Salah!Banget1", event.description)

    def test_open_redirect_blocked(self):
        response = self.client.post(
            reverse("accounts:login") + "?next=https://evil.example.com/",
            {"username": "pendaki", "password": GOOD_PASSWORD},
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response["Location"], reverse("home"))

    def test_logout_requires_post(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse("accounts:logout")).status_code, 405)

    def test_logout_then_dashboard_requires_login(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(response, reverse("accounts:login"))
        dashboard = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(dashboard.status_code, 302)
        self.assertIn("/login/", dashboard["Location"])

    def test_dashboard_requires_login(self):
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response["Location"].startswith("/login/"))


class SessionAndCookieTests(BaseAuthTest):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()

    def test_session_cookie_flags(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "pendaki", "password": GOOD_PASSWORD},
        )
        cookie = response.cookies[settings.SESSION_COOKIE_NAME]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        # Secure tidak dipaksa saat dev HTTP
        self.assertFalse(bool(cookie["secure"]))

    def test_session_key_rotates_on_login(self):
        self.client.get(reverse("accounts:login"))
        before = self.client.session.session_key
        self.client.post(
            reverse("accounts:login"),
            {"username": "pendaki", "password": GOOD_PASSWORD},
        )
        after = self.client.session.session_key
        self.assertNotEqual(before, after)

    def test_no_auth_data_in_local_storage(self):
        """Frontend tidak boleh menyimpan kredensial di localStorage."""
        from pathlib import Path

        templates = Path(settings.BASE_DIR) / "templates"
        for path in templates.rglob("*.html"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn(
                "localStorage.setItem", text, f"{path.name} memakai localStorage"
            )
            self.assertNotIn(
                "sessionStorage.setItem", text, f"{path.name} memakai sessionStorage"
            )


class SecurityTests(BaseAuthTest):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()

    def test_csrf_protection_enforced(self):
        csrf_client = Client(enforce_csrf_checks=True)
        response = csrf_client.post(
            reverse("accounts:login"),
            {"username": "pendaki", "password": GOOD_PASSWORD},
        )
        self.assertEqual(response.status_code, 403)

    def test_csrf_token_present_in_forms(self):
        for url in (reverse("accounts:login"), reverse("accounts:register")):
            response = self.client.get(url)
            self.assertContains(response, "csrfmiddlewaretoken")

    def test_csrf_middleware_active(self):
        self.assertIn("django.middleware.csrf.CsrfViewMiddleware", settings.MIDDLEWARE)

    def test_sql_injection_in_login_fails(self):
        payloads = [
            "' OR 1=1 --",
            "admin'--",
            "' OR '1'='1",
            "pendaki' OR '1'='1",
        ]
        for payload in payloads:
            response = self.client.post(
                reverse("accounts:login"),
                {"username": payload, "password": payload},
            )
            self.assertEqual(response.status_code, 200)
            self.assertFalse(
                response.wsgi_request.user.is_authenticated,
                f"SQL injection berhasil dengan payload {payload!r}",
            )

    def test_sql_injection_in_registration_does_not_break_orm(self):
        response = self.client.post(
            reverse("accounts:register"),
            self.register_payload(username="Robert'); DROP TABLE accounts_user;--"),
        )
        self.assertEqual(response.status_code, 200)
        # Tabel masih ada dan bisa di-query.
        self.assertEqual(User.objects.count(), 1)

    def test_xss_in_name_is_escaped(self):
        self.client.post(
            reverse("accounts:register"),
            self.register_payload(
                username="xsstest",
                email="xss@example.com",
                first_name="<script>alert('xss')</script>",
            ),
        )
        response = self.client.get(reverse("accounts:dashboard"))
        html = response.content.decode()
        self.assertNotIn("<script>alert('xss')</script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_xss_in_username_error_page_escaped(self):
        response = self.client.post(
            reverse("accounts:register"),
            self.register_payload(username='"><img src=x onerror=alert(1)>'),
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("<img src=x onerror=alert(1)>", response.content.decode())

    def test_authorization_dashboard_only_shows_own_data(self):
        other = self.make_user(username="oranglain", email="lain@example.com")
        SecurityEvent.objects.create(
            user=other,
            event_type=SecurityEvent.LOGIN_SUCCESS,
            status=SecurityEvent.STATUS_SUCCESS,
            ip_address="10.0.0.9",
        )
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertNotContains(response, "oranglain@example.com")
        self.assertNotContains(response, "10.0.0.9")

    def test_regular_user_cannot_open_admin(self):
        self.client.force_login(self.user)
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 302)  # diarahkan ke login admin

    def test_staff_can_open_admin(self):
        self.user.is_staff = True
        self.user.save(update_fields=["is_staff"])
        self.client.force_login(self.user)
        response = self.client.get("/admin/")
        self.assertEqual(response.status_code, 200)

    def test_password_stored_hashed_and_salted(self):
        a = self.make_user(username="salt1", email="salt1@example.com")
        b = self.make_user(username="salt2", email="salt2@example.com")
        self.assertNotEqual(a.password, b.password)  # salt berbeda
        self.assertTrue(a.password.startswith("pbkdf2_sha256$"))

    def test_no_jwt_dependency(self):
        self.assertNotIn("rest_framework", settings.INSTALLED_APPS)
        self.assertEqual(settings.SESSION_ENGINE, "django.contrib.sessions.backends.db")
        self.assertEqual(settings.AUTH_USER_MODEL, "accounts.User")


class PasswordChangeTests(BaseAuthTest):
    def setUp(self):
        super().setUp()
        self.user = self.make_user()
        self.client.force_login(self.user)

    def test_password_change_success(self):
        response = self.client.post(
            reverse("accounts:password_change"),
            {
                "current_password": GOOD_PASSWORD,
                "new_password": "Baru!Sekali2027",
                "new_password_confirmation": "Baru!Sekali2027",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Baru!Sekali2027"))
        self.assertTrue(
            SecurityEvent.objects.filter(
                event_type=SecurityEvent.PASSWORD_CHANGED, user=self.user
            ).exists()
        )

    def test_wrong_current_password_rejected(self):
        response = self.client.post(
            reverse("accounts:password_change"),
            {
                "current_password": "Salah!Banget1",
                "new_password": "Baru!Sekali2027",
                "new_password_confirmation": "Baru!Sekali2027",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(GOOD_PASSWORD))

    def test_weak_new_password_rejected(self):
        response = self.client.post(
            reverse("accounts:password_change"),
            {
                "current_password": GOOD_PASSWORD,
                "new_password": "lemah",
                "new_password_confirmation": "lemah",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password(GOOD_PASSWORD))


class MemberAreaTests(BaseAuthTest):
    """Area member: homepage setelah login, dropdown akun, Pengaturan, Transaksi."""

    def setUp(self):
        super().setUp()
        self.user = self.make_user(
            first_name="Budi", last_name="Santoso", phone_number="081200001111"
        )

    def test_login_redirects_to_homepage(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "pendaki", "password": GOOD_PASSWORD},
        )
        self.assertRedirects(response, reverse("home"))
        homepage = self.client.get(reverse("home"))
        self.assertEqual(homepage.status_code, 200)
        # Header menampilkan nama user + menu akun, bukan tombol "Masuk"
        self.assertContains(homepage, 'id="accountItem"')
        self.assertContains(homepage, "pendaki")
        self.assertContains(homepage, "Transaksi")
        self.assertContains(homepage, "Pengaturan")
        self.assertContains(homepage, "Logout")

    def test_homepage_for_guest_shows_login_link_only(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'id="accountItem"')
        self.assertContains(response, "Masuk")

    def test_settings_requires_login(self):
        response = self.client.get(reverse("accounts:settings"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_settings_page_loads_with_current_values(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:settings"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "pendaki@example.com")
        self.assertContains(response, "081200001111")

    def test_settings_update_profile(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:settings"),
            {
                "first_name": "Budi",
                "last_name": "Pratama",
                "email": "budi.baru@contoh.co.id",
                "phone_number": "081299998888",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.last_name, "Pratama")
        self.assertEqual(self.user.email, "budi.baru@contoh.co.id")
        self.assertEqual(self.user.phone_number, "081299998888")

    def test_settings_rejects_duplicate_email(self):
        self.make_user(username="lain", email="dipakai@contoh.co.id")
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:settings"),
            {
                "first_name": "Budi",
                "last_name": "Santoso",
                "email": "dipakai@contoh.co.id",
                "phone_number": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "pendaki@example.com")

    def test_settings_rejects_invalid_phone(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:settings"),
            {
                "first_name": "Budi",
                "last_name": "Santoso",
                "email": "pendaki@example.com",
                "phone_number": "bukan-nomor",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.phone_number, "081200001111")

    def test_settings_escapes_xss(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("accounts:settings"),
            {
                "first_name": "<script>alert('x')</script>",
                "last_name": "Santoso",
                "email": "pendaki@example.com",
                "phone_number": "",
            },
        )
        self.assertNotIn("<script>alert('x')</script>", response.content.decode())
        self.assertIn("&lt;script&gt;", response.content.decode())

    def test_transaction_requires_login(self):
        response = self.client.get(reverse("accounts:transaction_list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_transaction_page_shows_empty_state(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("accounts:transaction_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Belum ada transaksi")

    def test_logout_from_header_menu_works(self):
        self.client.force_login(self.user)
        response = self.client.post(reverse("accounts:logout"))
        self.assertRedirects(response, reverse("accounts:login"))


class RoleSystemTests(BaseAuthTest):
    """Role berbasis Django Groups + proteksi dashboard."""

    def setUp(self):
        super().setUp()
        from accounts.roles import ensure_roles

        ensure_roles()
        self.customer = self.make_user(username="cust", email="cust@contoh.co.id")
        self.cashier = self.make_user(username="kasir", email="kasir@contoh.co.id")
        self.admin = self.make_user(username="adm", email="adm@contoh.co.id")
        self.client_user = self.make_user(username="plain", email="plain@contoh.co.id")
        from accounts.roles import ROLE_ADMIN, ROLE_CASHIER, ROLE_CUSTOMER, assign_role

        assign_role(self.customer, ROLE_CUSTOMER)
        assign_role(self.cashier, ROLE_CASHIER)
        assign_role(self.admin, ROLE_ADMIN)

    def test_three_roles_exist_as_groups(self):
        from django.contrib.auth.models import Group

        names = set(Group.objects.values_list("name", flat=True))
        self.assertTrue({"Customer", "Cashier", "Admin"}.issubset(names))

    def test_no_boolean_role_fields_on_user(self):
        field_names = {f.name for f in User._meta.get_fields()}
        for bad in ("is_customer", "is_cashier", "is_admin"):
            self.assertNotIn(bad, field_names)

    def test_registration_assigns_customer_role(self):
        self.client.post(
            reverse("accounts:register"),
            self.register_payload(username="baru", email="baru@contoh.co.id"),
        )
        from accounts.roles import primary_role

        user = User.objects.get(username="baru")
        self.assertEqual(primary_role(user), "Customer")

    def test_customer_blocked_from_admin_dashboard(self):
        self.client.force_login(self.customer)
        response = self.client.get(reverse("accounts:admin_dashboard"))
        self.assertEqual(response.status_code, 403)
        self.assertTrue(
            SecurityEvent.objects.filter(
                event_type=SecurityEvent.ACCESS_DENIED, user=self.customer
            ).exists()
        )

    def test_customer_blocked_from_cashier_dashboard(self):
        self.client.force_login(self.customer)
        self.assertEqual(
            self.client.get(reverse("accounts:cashier_dashboard")).status_code, 403
        )

    def test_cashier_can_open_cashier_dashboard_only(self):
        self.client.force_login(self.cashier)
        self.assertEqual(
            self.client.get(reverse("accounts:cashier_dashboard")).status_code, 200
        )
        self.assertEqual(
            self.client.get(reverse("accounts:admin_dashboard")).status_code, 403
        )

    def test_admin_can_open_both_dashboards(self):
        self.client.force_login(self.admin)
        self.assertEqual(
            self.client.get(reverse("accounts:admin_dashboard")).status_code, 200
        )
        self.assertEqual(
            self.client.get(reverse("accounts:cashier_dashboard")).status_code, 200
        )

    def test_user_without_role_blocked_everywhere(self):
        self.client.force_login(self.client_user)
        self.assertEqual(
            self.client.get(reverse("accounts:admin_dashboard")).status_code, 403
        )
        self.assertEqual(
            self.client.get(reverse("accounts:cashier_dashboard")).status_code, 403
        )

    def test_superuser_bypasses_role_check(self):
        su = User.objects.create_superuser(
            username="root", email="root@contoh.co.id", password=GOOD_PASSWORD
        )
        self.client.force_login(su)
        self.assertEqual(
            self.client.get(reverse("accounts:admin_dashboard")).status_code, 200
        )

    def test_anonymous_redirected_to_login(self):
        for name in ("accounts:admin_dashboard", "accounts:cashier_dashboard"):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 302)
            self.assertIn("/login/", response["Location"])

    def test_admin_dashboard_shows_real_users_not_demo_data(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("accounts:admin_dashboard"))
        html = response.content.decode()
        self.assertIn("Total User", html)
        self.assertNotIn("Rina Kartika", html)   # data demo dashboard.js
        self.assertNotIn("Bagus Setiawan", html)

        # Daftar user asli ada di halaman menu Users (bukan ditumpuk di dashboard)
        users_html = self.client.get(reverse("accounts:admin_users")).content.decode()
        self.assertIn("kasir", users_html)          # user asli dari DB
        self.assertIn("Customer", users_html)       # badge role

    def test_cashier_dashboard_has_no_demo_data(self):
        self.client.force_login(self.cashier)
        html = self.client.get(reverse("accounts:cashier_dashboard")).content.decode()
        self.assertNotIn("Rina Kartika", html)
        self.assertIn("Belum ada", html)

    def test_setrole_command(self):
        from django.core.management import call_command

        call_command("setrole", "plain", "Cashier")
        from accounts.roles import primary_role

        self.client_user.refresh_from_db()
        self.assertEqual(primary_role(self.client_user), "Cashier")

    def test_assign_role_exclusive_replaces_other_roles(self):
        from accounts.roles import ROLE_CASHIER, ROLE_CUSTOMER, assign_role, primary_role

        assign_role(self.customer, ROLE_CASHIER)
        self.assertEqual(primary_role(self.customer), "Cashier")
        self.assertFalse(self.customer.groups.filter(name=ROLE_CUSTOMER).exists())

    def test_assign_role_add_keeps_other_roles(self):
        from accounts.roles import ROLE_ADMIN, ROLE_CUSTOMER, assign_role, primary_role

        assign_role(self.customer, ROLE_ADMIN, exclusive=False)
        self.assertEqual(primary_role(self.customer), "Admin")
        self.assertTrue(self.customer.groups.filter(name=ROLE_CUSTOMER).exists())

    def test_login_redirects_admin_to_admin_dashboard(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "adm", "password": GOOD_PASSWORD},
        )
        self.assertRedirects(response, reverse("accounts:admin_dashboard"))

    def test_login_redirects_cashier_to_cashier_dashboard(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "kasir", "password": GOOD_PASSWORD},
        )
        self.assertRedirects(response, reverse("accounts:cashier_dashboard"))

    def test_login_redirects_customer_to_home(self):
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "cust", "password": GOOD_PASSWORD},
        )
        self.assertRedirects(response, reverse("home"))

    def test_authenticated_admin_visiting_login_goes_to_dashboard(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("accounts:login"))
        self.assertRedirects(response, reverse("accounts:admin_dashboard"))

    def test_next_parameter_still_wins_over_role_redirect(self):
        response = self.client.post(
            reverse("accounts:login") + "?next=/settings/",
            {"username": "adm", "password": GOOD_PASSWORD},
        )
        self.assertRedirects(response, "/settings/")

    def test_staff_sees_dashboard_link_in_account_menu(self):
        self.client.force_login(self.admin)
        html = self.client.get(reverse("home")).content.decode()
        self.assertIn("Dashboard Admin", html)
        self.assertIn(reverse("accounts:admin_dashboard"), html)

    def test_customer_does_not_see_dashboard_links(self):
        self.client.force_login(self.customer)
        html = self.client.get(reverse("home")).content.decode()
        self.assertNotIn("Dashboard Admin", html)
        self.assertNotIn("Dashboard Kasir", html)

class AccountLockoutTests(BaseAuthTest):
    """Temporary account lockout: lapisan kedua di atas rate limiting."""

    def setUp(self):
        super().setUp()
        self.user = self.make_user(username="lockuser", email="lock@contoh.co.id")

    def attempt(self, password, identifier="lockuser"):
        """Login gagal/berhasil.

        cache.clear() memisahkan pengujian lockout dari rate limiting IP,
        karena rate limit 5/10 menit akan menutup jalur sebelum 10 kegagalan.
        """
        cache.clear()
        return self.client.post(
            reverse("accounts:login"),
            {"username": identifier, "password": password},
        )

    def lock_now(self, minutes=15):
        self.user.locked_until = timezone.now() + timedelta(minutes=minutes)
        self.user.save(update_fields=["locked_until"])

    # --- Test 1: increment ------------------------------------------------
    def test_failed_attempt_increments_counter(self):
        response = self.attempt("Salah#Banget1")
        self.assertEqual(response.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 1)

    # --- Test 2: success resets -------------------------------------------
    def test_successful_login_resets_counter(self):
        self.user.failed_login_attempts = 5
        self.user.save(update_fields=["failed_login_attempts"])
        response = self.attempt(GOOD_PASSWORD)
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 0)
        self.assertIsNone(self.user.locked_until)

    # --- Test 3: threshold ------------------------------------------------
    def test_threshold_locks_account(self):
        for _ in range(10):
            self.attempt("Salah#Banget1")
        self.user.refresh_from_db()
        self.assertEqual(self.user.failed_login_attempts, 10)
        self.assertIsNotNone(self.user.locked_until)
        self.assertTrue(self.user.is_locked)
        sisa = self.user.locked_until - timezone.now()
        self.assertGreater(sisa, timedelta(minutes=14))
        self.assertLessEqual(sisa, timedelta(minutes=15))

    # --- Test 4: correct password while locked ----------------------------
    def test_correct_password_rejected_while_locked(self):
        self.lock_now()
        response = self.attempt(GOOD_PASSWORD)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Akun sementara tidak dapat digunakan")
        self.assertFalse(response.wsgi_request.user.is_authenticated)
        # sesi tidak dibuat
        self.assertNotIn("_auth_user_id", self.client.session)

    # --- Test 5: wrong password while locked (tidak memperpanjang) --------
    def test_wrong_password_while_locked_is_rejected_without_extending(self):
        self.lock_now(minutes=10)
        self.user.refresh_from_db()
        locked_before = self.user.locked_until

        response = self.attempt("Salah#Banget1")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Akun sementara tidak dapat digunakan")

        self.user.refresh_from_db()
        self.assertEqual(self.user.locked_until, locked_before)
        self.assertEqual(self.user.failed_login_attempts, 0)

    # --- Test 6: lock expiration -----------------------------------------
    def test_lock_expires_allows_login(self):
        self.user.locked_until = timezone.now() - timedelta(seconds=5)
        self.user.failed_login_attempts = 10
        self.user.save(update_fields=["locked_until", "failed_login_attempts"])

        response = self.attempt(GOOD_PASSWORD)
        self.assertEqual(response.status_code, 302)
        self.user.refresh_from_db()
        self.assertIsNone(self.user.locked_until)
        self.assertEqual(self.user.failed_login_attempts, 0)

    # --- Test 7: rate limiting tetap berjalan -----------------------------
    def test_rate_limiting_still_blocks_sixth_attempt(self):
        for _ in range(5):
            self.client.post(
                reverse("accounts:login"),
                {"username": "lockuser", "password": "Salah#Banget1"},
            )
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "lockuser", "password": "Salah#Banget1"},
        )
        self.assertEqual(response.status_code, 429)
        self.assertTrue(
            SecurityEvent.objects.filter(
                event_type=SecurityEvent.RATE_LIMIT_LOGIN
            ).exists()
        )

    # --- Test 8: pesan generik, tanpa kebocoran ---------------------------
    def test_error_messages_do_not_leak_internal_details(self):
        known = self.attempt("Salah#Banget1", identifier="lockuser")
        unknown = self.attempt("Salah#Banget1", identifier="tidak_ada_user_zz")

        msg_known = known.content.decode()
        msg_unknown = unknown.content.decode()
        self.assertIn("Username/email atau password tidak valid.", msg_known)
        self.assertIn("Username/email atau password tidak valid.", msg_unknown)
        for bodi in (msg_known, msg_unknown):
            self.assertNotIn("failed_login_attempts", bodi)
            self.assertNotIn("locked_until", bodi)
            self.assertNotIn("threshold", bodi)

    def test_locked_message_is_safe(self):
        self.lock_now()
        response = self.attempt(GOOD_PASSWORD)
        html = response.content.decode()
        pesan = re.search(r'id="authMsg"[^>]*>([^<]*)<', html).group(1).strip()

        self.assertEqual(
            pesan, "Akun sementara tidak dapat digunakan. Silakan coba lagi nanti."
        )
        # Pesan tidak memuat angka (counter/timestamp) maupun istilah internal.
        self.assertFalse(any(ch.isdigit() for ch in pesan))
        self.assertNotIn("locked", pesan.lower())
        self.assertNotIn("attempt", pesan.lower())

    # --- Test 9: security logging ----------------------------------------
    def test_account_locked_event_logged_without_sensitive_data(self):
        for _ in range(10):
            self.attempt("Salah#Banget1")

        event = SecurityEvent.objects.filter(
            event_type=SecurityEvent.ACCOUNT_LOCKED
        ).first()
        self.assertIsNotNone(event)
        self.assertEqual(event.user, self.user)
        self.assertEqual(event.status, SecurityEvent.STATUS_BLOCKED)
        self.assertEqual(event.ip_address, "127.0.0.1")
        self.assertNotIn("Salah#Banget1", event.description or "")
        self.assertNotIn("password", (event.description or "").lower())

    def test_existing_users_still_login_normally(self):
        fresh = self.make_user(username="userbaru", email="userbaru@contoh.co.id")
        cache.clear()
        response = self.client.post(
            reverse("accounts:login"),
            {"username": "userbaru", "password": GOOD_PASSWORD},
        )
        self.assertEqual(response.status_code, 302)
        fresh.refresh_from_db()
        self.assertEqual(fresh.failed_login_attempts, 0)
        self.assertIsNone(fresh.locked_until)

class PasswordExpiryTests(BaseAuthTest):
    """Password expiry (adaptasi MySQL PASSWORD EXPIRE INTERVAL 30 DAY)."""

    def setUp(self):
        super().setUp()
        self.user = self.make_user(username="expuser", email="exp@contoh.co.id")

    # --- helper -----------------------------------------------------------
    def set_age(self, days):
        User.objects.filter(pk=self.user.pk).update(
            password_changed_at=timezone.now() - timedelta(days=days)
        )
        self.user.refresh_from_db()

    def login(self, username="expuser", password=GOOD_PASSWORD):
        cache.clear()
        return self.client.post(
            reverse("accounts:login"), {"username": username, "password": password}
        )

    # --- 1. user baru punya password_changed_at ---------------------------
    def test_new_user_has_password_changed_at(self):
        self.assertIsNotNone(self.user.password_changed_at)

        cache.clear()
        response = self.client.post(
            reverse("accounts:register"),
            self.register_payload(username="pwreg", email="pwreg@contoh.co.id"),
        )
        self.assertEqual(response.status_code, 302)
        baru = User.objects.get(username="pwreg")
        self.assertIsNotNone(baru.password_changed_at)
        self.assertFalse(baru.password_expired)

    # --- 2. belum expired -> login normal ---------------------------------
    def test_not_expired_can_login_normally(self):
        self.set_age(1)
        self.assertFalse(self.user.password_expired)

        response = self.login()
        self.assertEqual(response.status_code, 302)
        dashboard = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(dashboard.status_code, 200)

    # --- 3. tepat/lebih dari 30 hari -> expired ---------------------------
    def test_exactly_thirty_days_is_expired(self):
        self.set_age(30)
        self.assertTrue(self.user.password_expired)

    def test_more_than_thirty_days_is_expired(self):
        self.set_age(31)
        self.assertTrue(self.user.password_expired)

    def test_twenty_nine_days_still_valid(self):
        self.set_age(29)
        self.assertFalse(self.user.password_expired)

    def test_config_is_used_not_hardcoded(self):
        from django.test import override_settings

        self.set_age(10)
        self.assertFalse(self.user.password_expired)
        with override_settings(PASSWORD_MAX_AGE_DAYS=7):
            self.assertTrue(self.user.password_expired)

    # --- 4. user expired diarahkan ke change-password ---------------------
    def test_expired_user_redirected_to_change_password(self):
        self.set_age(31)
        self.login()

        response = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:password_change"), response["Location"])
        self.assertIn("expired=1", response["Location"])

    # --- 5. tidak bisa bypass dengan membuka URL lain ---------------------
    def test_expired_user_cannot_bypass_protected_pages(self):
        self.set_age(31)
        self.login()

        for url in (
            reverse("accounts:dashboard"),
            reverse("accounts:admin_dashboard"),
            reverse("accounts:cashier_dashboard"),
            reverse("accounts:settings"),
            reverse("accounts:transaction_list"),
            "/",
        ):
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302, f"{url} tidak dialihkan")
                self.assertIn(reverse("accounts:password_change"), response["Location"])

    def test_change_password_page_is_allowed_when_expired(self):
        self.set_age(31)
        self.login()
        response = self.client.get(reverse("accounts:password_change"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "kedaluwarsa")

    # --- 6. ganti password -> timestamp diperbarui ------------------------
    def test_password_change_updates_timestamp(self):
        self.set_age(31)
        self.login()
        lama = self.user.password_changed_at

        response = self.client.post(
            reverse("accounts:password_change"),
            {
                "current_password": GOOD_PASSWORD,
                "new_password": "Baru!Sekali2027",
                "new_password_confirmation": "Baru!Sekali2027",
            },
        )
        self.assertEqual(response.status_code, 200)

        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password("Baru!Sekali2027"))
        self.assertGreater(self.user.password_changed_at, lama)
        self.assertFalse(self.user.password_expired)

    # --- 7. setelah ganti password, dashboard bisa diakses ----------------
    def test_dashboard_accessible_after_password_change(self):
        self.set_age(31)
        self.login()
        self.client.post(
            reverse("accounts:password_change"),
            {
                "current_password": GOOD_PASSWORD,
                "new_password": "Baru!Sekali2027",
                "new_password_confirmation": "Baru!Sekali2027",
            },
        )
        response = self.client.get(reverse("accounts:dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_settings_blocked_when_expired(self):
        """Halaman pengaturan juga diblokir selama password expired."""
        self.set_age(31)
        self.login()
        response = self.client.get(reverse("accounts:settings"))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse("accounts:password_change"), response["Location"])

    # --- 8. account lockout Phase 1 tetap bekerja -------------------------
    def test_account_lockout_still_works(self):
        self.set_age(1)  # password masih valid
        User.objects.filter(pk=self.user.pk).update(
            failed_login_attempts=10,
            locked_until=timezone.now() + timedelta(minutes=15),
        )
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Akun sementara tidak dapat digunakan")

    def test_expired_user_can_still_logout(self):
        self.set_age(31)
        self.login()
        response = self.client.post(reverse("accounts:logout"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get(reverse("accounts:dashboard")).status_code, 302)

    def test_expiry_not_logged_as_password_leak(self):
        self.set_age(31)
        self.login()
        self.client.get(reverse("accounts:dashboard"))
        dump = " ".join(SecurityEvent.objects.values_list("description", flat=True))
        self.assertNotIn(GOOD_PASSWORD, dump)
        self.assertNotIn("password_changed_at=", dump)


class AdminAreaPagesTest(TestCase):
    """Layout admin baru: satu halaman per menu sidebar."""

    ADMIN_PAGES = [
        "accounts:admin_dashboard",
        "accounts:admin_users",
        "accounts:admin_staff",
        "accounts:admin_products",
        "accounts:admin_rentals",
        "accounts:admin_payments",
        "accounts:admin_security",
        "accounts:admin_reports",
    ]

    @classmethod
    def setUpTestData(cls):
        from accounts.roles import ROLE_ADMIN, ROLE_CUSTOMER, assign_role
        from catalog.models import Category, Product

        cls.admin = User.objects.create_user(
            username="admin_area", email="admin_area@example.com", password=GOOD_PASSWORD
        )
        assign_role(cls.admin, ROLE_ADMIN)

        cls.customer = User.objects.create_user(
            username="cust_area", email="cust_area@example.com", password=GOOD_PASSWORD
        )
        assign_role(cls.customer, ROLE_CUSTOMER)

        cls.category = Category.objects.create(name="Kategori QA", slug="kategori-qa")
        cls.product = Product.objects.create(
            category=cls.category,
            name="Tenda QA",
            slug="tenda-qa",
            price_per_day=10000,
        )

    def test_admin_pages_render_with_sidebar(self):
        self.client.force_login(self.admin)
        for name in self.ADMIN_PAGES:
            with self.subTest(page=name):
                response = self.client.get(reverse(name))
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "admin-nav-label")

    def test_each_page_marks_its_own_menu_active(self):
        from accounts.views import admin_staff  # noqa: F401  (import sanity)

        self.client.force_login(self.admin)
        response = self.client.get(reverse("accounts:admin_products"))
        self.assertContains(response, 'href="/dashboard/admin/products/" class="active"')
        response = self.client.get(reverse("accounts:admin_users"))
        self.assertContains(response, 'href="/dashboard/admin/users/" class="active"')

    def test_non_admin_cannot_open_admin_pages(self):
        self.client.force_login(self.customer)
        for name in self.ADMIN_PAGES:
            with self.subTest(page=name):
                self.assertEqual(self.client.get(reverse(name)).status_code, 403)

    def test_anonymous_redirected_to_login(self):
        response = self.client.get(reverse("accounts:admin_users"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_user_toggle_deactivates_and_cannot_toggle_self(self):
        from accounts.roles import ROLE_CUSTOMER, assign_role

        victim = User.objects.create_user(
            username="victim_area", email="victim_area@example.com", password=GOOD_PASSWORD
        )
        assign_role(victim, ROLE_CUSTOMER)
        self.client.force_login(self.admin)

        self.client.post(reverse("accounts:admin_user_toggle", args=[victim.pk]))
        victim.refresh_from_db()
        self.assertFalse(victim.is_active)

        self.client.post(reverse("accounts:admin_user_toggle", args=[self.admin.pk]))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_active)

    def test_users_page_filters_by_role(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("accounts:admin_users"), {"role": "Customer"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-search="cust_area')
        # admin_area tetap muncul di header (akun login), tapi tidak di tabel
        self.assertNotContains(response, 'data-search="admin_area')

    def test_products_page_lists_items(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("accounts:admin_products"))
        self.assertContains(response, "Tenda QA")
