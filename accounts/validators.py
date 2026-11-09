"""Validator password kebijakan STRICT TrailGear.

Dipakai lewat AUTH_PASSWORD_VALIDATORS, sehingga berlaku juga untuk
createsuperuser / changepassword di Django Admin.
"""

import re

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _


class MaximumLengthValidator:
    """Password maksimum 128 karakter."""

    def __init__(self, max_length=128):
        self.max_length = max_length

    def validate(self, password, user=None):
        if len(password) > self.max_length:
            raise ValidationError(
                _("Password maksimal %(max)d karakter."),
                code="password_too_long",
                params={"max": self.max_length},
            )

    def get_help_text(self):
        return _("Password maksimal %(max)d karakter.") % {"max": self.max_length}


class UppercaseValidator:
    """Minimal satu huruf kapital."""

    def validate(self, password, user=None):
        if not any(char.isupper() for char in password):
            raise ValidationError(
                _("Password harus mengandung minimal satu huruf kapital."),
                code="password_no_upper",
            )

    def get_help_text(self):
        return _("Password harus mengandung minimal satu huruf kapital.")


class LowercaseValidator:
    """Minimal satu huruf kecil."""

    def validate(self, password, user=None):
        if not any(char.islower() for char in password):
            raise ValidationError(
                _("Password harus mengandung minimal satu huruf kecil."),
                code="password_no_lower",
            )

    def get_help_text(self):
        return _("Password harus mengandung minimal satu huruf kecil.")


class SymbolValidator:
    """Minimal satu simbol (bukan huruf/angka/spasi)."""

    SPECIAL_CHARS = r"""!@#$%^&*()_+-=[]{};:'",.<>/?\|`~"""

    def validate(self, password, user=None):
        if not any(char in self.SPECIAL_CHARS for char in password):
            raise ValidationError(
                _("Password harus mengandung minimal satu simbol, contoh: ! @ # $ %% & * _ - + ?"),
                code="password_no_symbol",
            )

    def get_help_text(self):
        return _("Password harus mengandung minimal satu simbol.")


class DigitValidator:
    """Minimal satu angka."""

    def validate(self, password, user=None):
        if not any(char.isdigit() for char in password):
            raise ValidationError(
                _("Password harus mengandung minimal satu angka."),
                code="password_no_digit",
            )

    def get_help_text(self):
        return _("Password harus mengandung minimal satu angka.")


class UsernameFormatValidator:
    """Username: 3-16 karakter, hanya huruf, angka, dan underscore."""

    pattern = re.compile(r"^[A-Za-z0-9_]{3,16}$")

    def __call__(self, value):
        if not self.pattern.match(value):
            raise ValidationError(
                _("Username harus 3-16 karakter dan hanya boleh berisi huruf, angka, dan underscore."),
                code="invalid_username_format",
            )


PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9\s\-()]{6,19}$")


def validate_phone_number(value):
    """Nomor telepon opsional: 7-20 karakter, angka dengan + - ( ) dan spasi."""
    if not value:
        return
    if not PHONE_PATTERN.match(value.strip()):
        raise ValidationError(
            _("Nomor telepon tidak valid. Gunakan 7-20 karakter angka, contoh: 08123456789."),
            code="invalid_phone_number",
        )
