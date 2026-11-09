"""Context processor: jumlah item keranjang untuk badge navbar.

Didaftarkan di settings.TEMPLATES agar `cart_items_count` tersedia di semua
halaman tanpa query tambahan saat keranjang kosong/tidak ada.
"""

from .services import get_cart


def cart_summary(request):
    if request.path.startswith(("/admin/", "/static/")):
        return {"cart_items_count": 0}

    cart = get_cart(request, create=False)
    if cart is None:
        return {"cart_items_count": 0}

    count = sum(item.quantity for item in cart.items.all())
    return {
        "cart_items_count": count,
        "cart": cart,
    }
