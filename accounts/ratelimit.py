"""Rate limiting sederhana berbasis Django cache (tanpa layanan eksternal).

Sifat: sementara (sliding window kasar), BUKAN permanent IP ban.
Counter disimpan di cache; saat TTL habis, hitungan kembali nol.

Konfigurasi (settings.py):
- RATE_LIMIT_REGISTER_ATTEMPTS / RATE_LIMIT_REGISTER_WINDOW
- RATE_LIMIT_LOGIN_ATTEMPTS    / RATE_LIMIT_LOGIN_WINDOW

Catatan: CACHES di settings memakai FileBasedCache agar counter bertahan
melewati restart `runserver`.
"""

import hashlib

from django.conf import settings
from django.core.cache import cache


def client_ip(request):
    """Ambil IP klien.

    Sengaja hanya memakai REMOTE_ADDR: header X-Forwarded-For mudah dipalsukan
    dan akan membuat rate limit bisa dilewati. Jika nanti deploy di belakang
    reverse proxy tepercaya, aktifkan pembacaan XFF secara eksplisit.
    """
    return request.META.get("REMOTE_ADDR") or "0.0.0.0"


def identity_hash(identifier):
    """Hash identifier agar cache key tidak berisi email/username mentah."""
    return hashlib.sha256(identifier.strip().lower().encode("utf-8")).hexdigest()[:16]


def register_key(ip):
    return f"rl:register:{ip}"


def login_keys(ip, identifier):
    keys = [f"rl:login:ip:{ip}"]
    if identifier:
        keys.append(f"rl:login:id:{ip}:{identity_hash(identifier)}")
    return keys


def attempt_count(key):
    return int(cache.get(key, 0) or 0)


def is_blocked(key, limit):
    return attempt_count(key) >= limit


def bump(key, window):
    """Naikkan counter. Kembalikan nilai setelah dinaikkan."""
    if cache.add(key, 1, window):
        return 1
    try:
        return cache.incr(key)
    except ValueError:
        # Key hilang di antara get dan incr.
        cache.set(key, 1, window)
        return 1


def register_bump(ip):
    return bump(register_key(ip), settings.RATE_LIMIT_REGISTER_WINDOW)


def register_blocked(ip):
    return is_blocked(register_key(ip), settings.RATE_LIMIT_REGISTER_ATTEMPTS)


def login_blocked(ip, identifier):
    limit = settings.RATE_LIMIT_LOGIN_ATTEMPTS
    return any(is_blocked(k, limit) for k in login_keys(ip, identifier))


def login_bump(ip, identifier):
    window = settings.RATE_LIMIT_LOGIN_WINDOW
    for key in login_keys(ip, identifier):
        bump(key, window)


def login_reset(ip, identifier):
    for key in login_keys(ip, identifier):
        cache.delete(key)
