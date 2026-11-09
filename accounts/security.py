"""Security event logging TrailGear.

Dua lapis:
1. Tabel `accounts_securityevent` (bisa dilihat di Django Admin, dipakai test)
2. File log `logs/security.log` (rotating) lewat logger "trailgear.security"

Yang TIDAK boleh masuk log: password, password_confirmation, session id,
token, SECRET_KEY, kredensial database.
"""

import logging

from .models import SecurityEvent
from .ratelimit import client_ip

logger = logging.getLogger("trailgear.security")

MAX_DESCRIPTION = 500
MAX_USER_AGENT = 300


def _safe_text(value, limit):
    if not value:
        return ""
    # Buang newline agar satu event tetap satu baris di file log.
    return " ".join(str(value).split())[:limit]


def log_event(request, event_type, status, user=None, description=""):
    """Catat SecurityEvent. Gagal mencatat tidak boleh mematahkan request."""
    ip = client_ip(request) if request is not None else None
    user_agent = ""
    if request is not None:
        user_agent = _safe_text(request.META.get("HTTP_USER_AGENT", ""), MAX_USER_AGENT)

    description = _safe_text(description, MAX_DESCRIPTION)
    user_id = getattr(user, "pk", None)

    try:
        SecurityEvent.objects.create(
            user=user if user_id else None,
            event_type=event_type,
            status=status,
            ip_address=ip,
            user_agent=user_agent,
            description=description,
        )
    except Exception:  # pragma: no cover - DB down, dsb.
        logger.exception("Gagal menyimpan SecurityEvent event_type=%s", event_type)

    logger.info(
        "event=%s status=%s ip=%s user_id=%s desc=%s",
        event_type,
        status,
        ip,
        user_id,
        description,
    )
