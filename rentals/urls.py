"""Routing aplikasi rentals TrailGear."""

from django.urls import path

from . import views

app_name = "rentals"

urlpatterns = [
    # Keranjang
    path("cart/", views.cart_detail, name="cart_detail"),
    path("cart/add/<slug:slug>/", views.add_to_cart, name="add_to_cart"),
    path(
        "cart/item/<int:item_id>/update/",
        views.update_cart_item,
        name="update_cart_item",
    ),
    path(
        "cart/item/<int:item_id>/remove/",
        views.remove_from_cart,
        name="remove_from_cart",
    ),
    path(
        "cart/schedule/",
        views.update_cart_schedule,
        name="update_cart_schedule",
    ),
    # Checkout & pesanan pelanggan
    path("checkout/", views.checkout, name="checkout"),
    path("orders/", views.order_history, name="order_history"),
    path("orders/<str:order_code>/", views.order_detail, name="order_detail"),
    path(
        "orders/<str:order_code>/upload-proof/",
        views.upload_payment_proof,
        name="upload_payment_proof",
    ),
    path(
        "orders/<str:order_code>/proof/",
        views.payment_proof_file,
        name="payment_proof",
    ),
    # Dashboard staff (kasir & admin)
    path("dashboard/orders/", views.staff_order_list, name="staff_order_list"),
    path(
        "dashboard/orders/<str:order_code>/<str:action>/",
        views.staff_order_action,
        name="staff_order_action",
    ),
]
