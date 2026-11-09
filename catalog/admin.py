"""Konfigurasi Django Admin untuk Modul Katalog & Inventaris Alat."""

from django.contrib import admin

from .models import Category, InventoryLog, Product


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
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
class ProductAdmin(admin.ModelAdmin):
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


@admin.register(InventoryLog)
class InventoryLogAdmin(admin.ModelAdmin):
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
