"""Proteksi view berbasis role (Django Groups).

Contoh:
    @role_required(ROLE_ADMIN)
    def admin_dashboard(request): ...

Superuser selalu lolos. User yang login tapi tidak punya role yang cocok
mendapat 403 (bukan 404), dan percobaannya dicatat sebagai ACCESS_DENIED.
"""

from functools import wraps

from django.shortcuts import render
from django.views.decorators.cache import never_cache

from .models import SecurityEvent
from .roles import has_role, primary_role
from .security import log_event


def role_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        @never_cache
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                # Biarkan login_required yang menangani redirect ke /login/.
                from django.contrib.auth.views import redirect_to_login

                return redirect_to_login(request.get_full_path())

            if has_role(request.user, *roles):
                return view_func(request, *args, **kwargs)

            log_event(
                request,
                SecurityEvent.ACCESS_DENIED,
                SecurityEvent.STATUS_BLOCKED,
                user=request.user,
                description=(
                    f"path={request.path} role={primary_role(request.user) or 'none'} "
                    f"butuh={','.join(roles)}"
                ),
            )
            return render(
                request,
                "accounts/403.html",
                {},
                status=403,
            )

        return _wrapped

    return decorator
