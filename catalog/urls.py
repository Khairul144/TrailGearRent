"""Routing aplikasi catalog TrailGear."""

from django.urls import path

from . import views

app_name = "catalog"

urlpatterns = [
    path("products/", views.product_list, name="product_list"),
    path("product/<slug:slug>/", views.product_detail, name="product_detail"),
    path(
        "media/products/<str:filename>",
        views.product_media_file,
        name="product_media",
    ),
]
