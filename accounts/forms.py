"""Form registrasi & login TrailGear.

Semua validasi penting ada di backend. Validasi JavaScript di template hanya
tambahan UX.
"""

from django import forms
from django.contrib.auth import get_user_model, password_validation
from django.core.exceptions import ValidationError

from .validators import PHONE_PATTERN, validate_phone_number

User = get_user_model()

MAX_PASSWORD = 128
MIN_PASSWORD = 8


class RegistrationForm(forms.ModelForm):
    password = forms.CharField(
        label="Password",
        max_length=MAX_PASSWORD,
        widget=forms.PasswordInput,
        strip=False,
    )
    password_confirmation = forms.CharField(
        label="Konfirmasi password",
        max_length=MAX_PASSWORD,
        widget=forms.PasswordInput,
        strip=False,
    )

    class Meta:
        model = User
        fields = ["first_name", "last_name", "username", "email", "phone_number"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].max_length = 150
        self.fields["last_name"].max_length = 150
        self.fields["username"].max_length = 16
        self.fields["email"].max_length = 254
        self.fields["phone_number"].max_length = 20
        for name in ("first_name", "last_name", "phone_number"):
            self.fields[name].required = False
        self.fields["username"].required = True
        self.fields["email"].required = True

    # ---- field-level validation -------------------------------------------

    def clean_username(self):
        username = (self.cleaned_data.get("username") or "").strip()
        if not (3 <= len(username) <= 16):
            raise ValidationError("Username harus 3-16 karakter.")
        if not username.replace("_", "").isalnum():
            raise ValidationError(
                "Username hanya boleh berisi huruf, angka, dan underscore."
            )
        qs = User.objects.filter(username__iexact=username)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("Username sudah digunakan.")
        return username

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            raise ValidationError("Email wajib diisi.")
        qs = User.objects.filter(email__iexact=email)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("Email sudah terdaftar.")
        return email

    def clean_phone_number(self):
        phone = (self.cleaned_data.get("phone_number") or "").strip()
        if not phone:
            return ""
        validate_phone_number(phone)
        return phone

    def clean(self):
        cleaned = super().clean()
        password = cleaned.get("password")
        confirmation = cleaned.get("password_confirmation")

        if password and confirmation is not None and password != confirmation:
            self.add_error(
                "password_confirmation", "Konfirmasi password tidak cocok."
            )

        if password and len(password) > MAX_PASSWORD:
            self.add_error(
                "password", f"Password maksimal {MAX_PASSWORD} karakter."
            )

        return cleaned

    # ---- model-level validation (butuh instance terisi) --------------------

    def _post_clean(self):
        super()._post_clean()  # mengisi self.instance dari cleaned_data

        password = self.cleaned_data.get("password")
        if not password:
            return

        # Username/email/nama sudah menempel di instance sehingga
        # UserAttributeSimilarityValidator bisa bekerja.
        try:
            password_validation.validate_password(password, self.instance)
        except ValidationError as exc:
            self.add_error("password", exc)

    def save(self, commit=True):
        user = super().save(commit=False)
        # Melewati form -> backend bisa dipakai, tapi view memakai is_valid().
        user.set_password(self.cleaned_data["password"])
        if not self.cleaned_data.get("phone_number"):
            user.phone_number = ""
        if commit:
            user.save()
        return user


class LoginForm(forms.Form):
    """Form login: identifier = username atau email."""

    username = forms.CharField(max_length=254)
    password = forms.CharField(max_length=MAX_PASSWORD, strip=False)


class ProfileForm(forms.ModelForm):
    """Pengaturan akun: nama, email, nomor telepon, alamat."""

    class Meta:
        model = User
        fields = ["first_name", "last_name", "email", "phone_number", "address"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].max_length = 150
        self.fields["last_name"].max_length = 150
        self.fields["email"].max_length = 254
        self.fields["phone_number"].max_length = 20
        self.fields["address"].required = False
        self.fields["email"].required = True
        for name in ("first_name", "last_name", "phone_number"):
            self.fields[name].required = False

    def clean_email(self):
        email = (self.cleaned_data.get("email") or "").strip().lower()
        if not email:
            raise ValidationError("Email wajib diisi.")
        qs = User.objects.filter(email__iexact=email)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("Email sudah terdaftar.")
        return email

    def clean_phone_number(self):
        phone = (self.cleaned_data.get("phone_number") or "").strip()
        if not phone:
            return ""
        validate_phone_number(phone)
        return phone

    def clean_address(self):
        return (self.cleaned_data.get("address") or "").strip()[:500]


class PasswordChangeForm(forms.Form):
    current_password = forms.CharField(max_length=MAX_PASSWORD, strip=False)
    new_password = forms.CharField(max_length=MAX_PASSWORD, strip=False)
    new_password_confirmation = forms.CharField(max_length=MAX_PASSWORD, strip=False)

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_current_password(self):
        current = self.cleaned_data.get("current_password") or ""
        if not self.user.check_password(current):
            raise ValidationError("Password saat ini salah.")
        return current

    def clean(self):
        cleaned = super().clean()
        new_password = cleaned.get("new_password")
        confirmation = cleaned.get("new_password_confirmation")

        if new_password and confirmation is not None and new_password != confirmation:
            self.add_error(
                "new_password_confirmation", "Konfirmasi password tidak cocok."
            )

        if new_password:
            if new_password == cleaned.get("current_password"):
                self.add_error(
                    "new_password", "Password baru harus berbeda dari password lama."
                )
            try:
                password_validation.validate_password(new_password, self.user)
            except ValidationError as exc:
                self.add_error("new_password", exc)

        return cleaned
