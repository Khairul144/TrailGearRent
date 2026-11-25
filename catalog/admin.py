"""Konfigurasi Django Admin untuk Modul Katalog & Inventaris Alat."""

from django.contrib import admin

from accounts.roles import ROLE_ADMIN, has_role

from .models import Category, InventoryLog, Product


class _AdminRolePermissionMixin:
    """Izinkan akun dengan role Admin TrailGear mengakses model di /admin/."""

    def _is_trailgear_admin(self, request):
        return bool(
            request.user
            and request.user.is_authenticated
            and (request.user.is_superuser or has_role(request.user, ROLE_ADMIN))
        )

    def has_module_permission(self, request):
        return self._is_trailgear_admin(request) or super().has_module_permission(request)

    def has_view_permission(self, request, obj=None):
        return self._is_trailgear_admin(request) or super().has_view_permission(request, obj)

    def has_add_permission(self, request):
        return self._is_trailgear_admin(request) or super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return self._is_trailgear_admin(request) or super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self._is_trailgear_admin(request) or super().has_delete_permission(request, obj)


@admin.register(Category)
class CategoryAdmin(_AdminRolePermissionMixin, admin.ModelAdmin):
    list_display = ("name", "slug", "order", "show_in_menu", "is_active", "product_count")
    list_editable = ("order", "show_in_menu", "is_active")
    list_filter = ("is_active", "show_in_menu")
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}
    ordering = ("order", "name")

    @admin.display(description="Jumlah Produk")
    def product_count(self, obj):
        return obj.products.count()


@admin.register(Product)
class ProductAdmin(_AdminRolePermissionMixin, admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "formatted_price",
        "available_stock",
        "total_stock",
        "condition",
        "is_featured",
        "is_active",
    )
    list_editable = ("available_stock", "total_stock", "is_featured", "is_active")
    list_filter = ("category", "condition", "is_featured", "is_active", "price_type")
    search_fields = ("name", "slug", "brand_name", "description")
    prepopulated_fields = {"slug": ("name",)}
    list_select_related = ("category",)
    ordering = ("category__order", "name")

    def save_model(self, request, obj, form, change):
        from accounts.models import SecurityEvent
        from accounts.security import log_event

        old_available = 0
        if change and obj.pk:
            old_available = (
                Product.objects.filter(pk=obj.pk)
                .values_list("available_stock", flat=True)
                .first()
                or 0
            )
        super().save_model(request, obj, form, change)
        actor = request.user if getattr(request.user, "is_authenticated", False) else None
        if not change:
            if obj.available_stock > 0:
                InventoryLog.objects.create(
                    product=obj,
                    changed_by=actor,
                    action=InventoryLog.Action.RESTOCK,
                    quantity_change=obj.available_stock,
                    stock_before=0,
                    stock_after=obj.available_stock,
                    notes="Produk baru ditambahkan via Django Admin",
                )
            log_event(
                request,
                SecurityEvent.ADMIN_CATALOG_UPDATED,
                SecurityEvent.STATUS_SUCCESS,
                user=actor,
                description=f"action=django_admin_add_product product_id={obj.pk} stock={obj.available_stock}/{obj.total_stock}",
            )
        elif obj.available_stock != old_available:
            delta = obj.available_stock - old_available
            InventoryLog.objects.create(
                product=obj,
                changed_by=actor,
                action=InventoryLog.Action.RESTOCK if delta > 0 else InventoryLog.Action.ADJUSTMENT,
                quantity_change=delta,
                stock_before=old_available,
                stock_after=obj.available_stock,
                notes="Perubahan stok via Django Admin",
            )
            log_event(
                request,
                SecurityEvent.ADMIN_CATALOG_UPDATED,
                SecurityEvent.STATUS_SUCCESS,
                user=actor,
                description=f"action=django_admin_stock_change product_id={obj.pk} stock={old_available}->{obj.available_stock}",
            )


@admin.register(InventoryLog)
class InventoryLogAdmin(_AdminRolePermissionMixin, admin.ModelAdmin):
    list_display = (
        "created_at",
        "product",
        "action",
        "quantity_change",
        "stock_before",
        "stock_after",
        "changed_by",
        "notes",
    )
    list_filter = ("action", "created_at")
    search_fields = ("product__name", "notes", "changed_by__username")
    readonly_fields = ("created_at",)
    list_select_related = ("product", "changed_by")
