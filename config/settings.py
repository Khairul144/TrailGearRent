"""
Django settings untuk proyek TrailGear (config).

Django 6.1.3 + PostgreSQL + session authentication (TANPA JWT).

Semua nilai sensitif dibaca dari backend/.env:
  DJANGO_SECRET_KEY, DB_PASSWORD, dst. Tidak ada secret di file ini.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Muat variabel dari .env (kredensial DB, SECRET_KEY, dll).
load_dotenv(BASE_DIR / ".env")


def env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


# SECURITY WARNING: keep the secret key used in production secret!
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")

if not SECRET_KEY:
    raise RuntimeError(
        "DJANGO_SECRET_KEY belum diset. Pastikan file backend/.env ada dan berisi DJANGO_SECRET_KEY."
    )

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = env_bool("DJANGO_DEBUG", True)

ALLOWED_HOSTS = [
    h.strip()
    for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",")
    if h.strip()
]


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # App lokal: custom user model + security log
    'accounts',
    # App lokal: modul katalog & inventaris alat outdoor
    'catalog',
    # App lokal: keranjang, checkout, dan pemesanan sewa
    'rentals',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    # Password expired -> paksa ganti password (adaptasi MySQL PASSWORD EXPIRE)
    'accounts.middleware.PasswordExpiryMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        # Template Django hasil integrasi dari Frontend/*.html
        'DIRS': [BASE_DIR / "templates"],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'accounts.context_processors.roles',
                'catalog.context_processors.nav_categories',
                'rentals.context_processors.cart_summary',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.1/ref/settings/#databases
#
# Database TrailGear_auth dibuat khusus untuk implementasi custom user model.
# Database lama "TrailGear" (sudah terlanjur memakai auth.User default)
# dibiarkan utuh dan tidak dipakai oleh proyek ini.

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": os.environ.get("DB_NAME", "TrailGear_auth"),
        "USER": os.environ.get("DB_USER", "tg_user"),
        "PASSWORD": os.environ.get("DB_PASSWORD", ""),
        "HOST": os.environ.get("DB_HOST", "127.0.0.1"),
        "PORT": os.environ.get("DB_PORT", "5432"),
        "CONN_MAX_AGE": 60,
        "OPTIONS": {
            "connect_timeout": 10,
        },
    }
}

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Authentication

AUTH_USER_MODEL = "accounts.User"

# Login boleh memakai username ATAU email. ModelBackend tetap terpasang
# sebagai cadangan (pengecekan permission / verifikasi hash).
AUTHENTICATION_BACKENDS = [
    "accounts.backends.EmailOrUsernameBackend",
    "django.contrib.auth.backends.ModelBackend",
]

LOGIN_URL = "/login/"
LOGIN_REDIRECT_URL = "/"
LOGOUT_REDIRECT_URL = "/login/"


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators
#
# Kebijakan STRICT:
#   min 8, max 128, wajib huruf kecil + huruf besar + angka + simbol,
#   password umum ditolak, password mirip identitas user ditolak.
#
# Hashing tetap 100% Django (PBKDF2-SHA256 default, bergaram).

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
        'OPTIONS': {'max_similarity': 0.7},
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
        'OPTIONS': {'min_length': 8},
    },
    {
        'NAME': 'accounts.validators.MaximumLengthValidator',
        'OPTIONS': {'max_length': 128},
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
    {'NAME': 'accounts.validators.UppercaseValidator'},
    {'NAME': 'accounts.validators.LowercaseValidator'},
    {'NAME': 'accounts.validators.DigitValidator'},
    {'NAME': 'accounts.validators.SymbolValidator'},
]

# Password hashers: biarkan default Django. Jangan diganti MD5/SHA manual.
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher",
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.BCryptSHA256PasswordHasher",
    "django.contrib.auth.hashers.ScryptPasswordHasher",
]


# Session & cookie security
# https://docs.djangoproject.com/en/6.1/topics/http/sessions/

SESSION_ENGINE = "django.contrib.sessions.backends.db"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
SESSION_COOKIE_AGE = env_int("DJANGO_SESSION_COOKIE_AGE", 60 * 60 * 12)  # 12 jam
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = False
# Secure=True hanya saat HTTPS. Di localhost (HTTP) tetap False agar dev jalan.
SESSION_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", False)

CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SECURE = env_bool("DJANGO_SECURE_COOKIES", False)
CSRF_TRUSTED_ORIGINS = [
    o.strip()
    for o in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if o.strip()
]

# Header keamanan umum
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
# Redirect HTTP->HTTPS dimatikan untuk development; aktifkan di produksi.
SECURE_SSL_REDIRECT = env_bool("DJANGO_SECURE_SSL_REDIRECT", False)
SECURE_HSTS_SECONDS = env_int("DJANGO_SECURE_HSTS_SECONDS", 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = SECURE_HSTS_SECONDS > 0
SECURE_HSTS_PRELOAD = False


# Cache (dipakai rate limiting). Bukan LocMem supaya counter bertahan
# melewati restart runserver.

CACHE_DIR = BASE_DIR / ".cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.filebased.FileBasedCache",
        "LOCATION": str(CACHE_DIR),
        "TIMEOUT": 300,
        "OPTIONS": {"MAX_ENTRIES": 5000},
    }
}

# Rate limiting (sementara per IP, bukan permanent ban)
RATE_LIMIT_REGISTER_ATTEMPTS = env_int("RATE_LIMIT_REGISTER_ATTEMPTS", 3)
RATE_LIMIT_REGISTER_WINDOW = env_int("RATE_LIMIT_REGISTER_WINDOW", 600)  # detik
RATE_LIMIT_LOGIN_ATTEMPTS = env_int("RATE_LIMIT_LOGIN_ATTEMPTS", 5)
RATE_LIMIT_LOGIN_WINDOW = env_int("RATE_LIMIT_LOGIN_WINDOW", 600)  # detik

# Account lockout (lapisan kedua, berbasis akun & disimpan di database).
# Berbeda dari rate limiting: yang dikunci adalah AKUN-nya, bukan IP.
ACCOUNT_LOCKOUT_THRESHOLD = env_int("ACCOUNT_LOCKOUT_THRESHOLD", 10)  # kegagalan
ACCOUNT_LOCKOUT_DURATION = env_int("ACCOUNT_LOCKOUT_DURATION", 15)   # menit

# Password expiry (adaptasi MySQL PASSWORD EXPIRE INTERVAL 30 DAY).
# Dipakai oleh accounts.User.password_expired dan PasswordExpiryMiddleware.
PASSWORD_MAX_AGE_DAYS = env_int("PASSWORD_MAX_AGE_DAYS", 30)  # hari


# Logging
# Security event ditulis ke tabel SecurityEvent DAN ke logs/security.log.
# Password / session id tidak pernah masuk ke log.

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "security": {
            "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        },
        "verbose": {
            "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        },
    },
    "handlers": {
        "security_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "filename": str(LOG_DIR / "security.log"),
            "maxBytes": 5 * 1024 * 1024,
            "backupCount": 3,
            "encoding": "utf-8",
            "formatter": "security",
        },
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "verbose",
        },
    },
    "loggers": {
        "trailgear.security": {
            "handlers": ["security_file", "console"],
            "level": "INFO",
            "propagate": False,
        },
        "django.request": {
            "handlers": ["console"],
            "level": "ERROR",
            "propagate": False,
        },
    },
}


# Internationalization
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = 'id'

TIME_ZONE = 'Asia/Jakarta'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/
#
# Seluruh aset statis (CSS, JS, gambar) terpusat di direktori static/.

STATIC_URL = '/static/'
STATICFILES_DIRS = [
    BASE_DIR / "static",
]
STATIC_ROOT = BASE_DIR / "staticfiles"

# Media (bukti pembayaran). TIDAK dilayani publik: akses lewat view ber-otorisasi
# (rentals.views.payment_proof_file), bukan lewat static()/MEDIA_URL langsung.
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

# Batas unggahan (anti-DoS). Validasi bisnis 5 MB ada di rentals.validators;
# nilai Django dibuat sedikit di atasnya agar berkas 5 MB tidak ditolak lebih dulu.
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 6 * 1024 * 1024


# Email (belum dipakai: registrasi tanpa verifikasi email)

MAILERS = {
    'default': {
        'BACKEND': 'django.core.mail.backends.console.EmailBackend',
    },
}
