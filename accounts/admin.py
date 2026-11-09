"""Django Admin untuk accounts.

User biasa: is_staff=False, is_superuser=False (tidak bisa masuk /admin/).
Administrator memakai is_staff / is_superuser / groups / permissions.
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import SecurityEvent, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "username",
        "email",
        "first_name",
        "last_name",
        "phone_number",
        "is_staff",
        "is_active",
        "failed_login_attempts",
        "locked_until",
        "date_joined",
    )
    list_filter = ("is_staff", "is_superuser", "is_active", "groups")
    search_fields = ("username", "email", "first_name", "last_name", "phone_number")
    ordering = ("-date_joined",)

    fieldsets = BaseUserAdmin.fieldsets + (
        ("Data TrailGear", {"fields": ("phone_number",)}),
        (
            "Keamanan (account lockout)",
            {
                "fields": ("failed_login_attempts", "locked_until"),
                "description": "Dikelola otomatis oleh proses login. Ubah hanya bila perlu membuka kunci manual.",
            },
        ),
    )
    readonly_fields = ("failed_login_attempts", "locked_until")
    add_fieldsets = BaseUserAdmin.add_fieldsets + (
        ("Data TrailGear", {"fields": ("email", "first_name", "last_name", "phone_number")}),
    )


@admin.register(SecurityEvent)
class SecurityEventAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "event_type", "status", "user", "ip_address")
    list_filter = ("event_type", "status")
    search_fields = ("ip_address", "description", "user__username")
    date_hierarchy = "timestamp"
    readonly_fields = (
        "user",
        "event_type",
        "status",
        "ip_address",
        "user_agent",
        "description",
        "timestamp",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser
