"""Admin Django untuk Modul Keranjang & Pemesanan Sewa."""

from django.contrib import admin

from .models import Cart, CartItem, RentalOrder, RentalOrderItem


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0
    autocomplete_fields = ["product"]


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "session_key", "updated_at")
    list_filter = ("created_at",)
    search_fields = ("user__username", "session_key")
    inlines = [CartItemInline]


class RentalOrderItemInline(admin.TabularInline):
    model = RentalOrderItem
    extra = 0
    readonly_fields = ("subtotal",)
    autocomplete_fields = ["product"]


@admin.register(RentalOrder)
class RentalOrderAdmin(admin.ModelAdmin):
    list_display = (
        "order_code",
        "full_name",
        "user",
        "status",
        "payment_method",
        "proof_status",
        "pickup_plan_date",
        "return_plan_date",
        "grand_total",
        "created_at",
    )
    list_filter = ("status", "payment_method", "id_card_type", "pickup_plan_date")
    search_fields = ("order_code", "full_name", "phone_number", "id_card_number")
    date_hierarchy = "created_at"
    readonly_fields = (
        "order_code",
        "total_rental_fee",
        "grand_total",
        "stock_deducted",
        "payment_proof_uploaded_at",
        "created_at",
        "updated_at",
    )
    inlines = [RentalOrderItemInline]

    @admin.display(description="Bukti Bayar", boolean=True)
    def proof_status(self, obj):
        return obj.has_payment_proof()
