"""URL configuration untuk proyek TrailGear."""

from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView

from catalog import views as catalog_views

urlpatterns = [
    path("", catalog_views.home, name="home"),
    path("", include("accounts.urls")),
    path("", include("catalog.urls")),
    path("", include("rentals.urls")),
    path("admin/", admin.site.urls),
]

# Aset frontend yang direferensikan relatif oleh JavaScript lama
# (assets/js/main.js memakai path "assets/img/...") akan diminta dari akar
# domain, bukan dari /static/. Redirect permanen ke pipeline static Django
# supaya gambar produk/ikon tetap tampil tanpa menduplikasi file.
urlpatterns += [
    path(
        "assets/<path:path>",
        RedirectView.as_view(url="/static/assets/%(path)s", permanent=True),
        name="frontend-assets",
    ),
]

# Kompatibilitas URL statis lama (Frontend/*.html). Link/bookmark lama
# seperti /login.html tidak boleh berakhir 404.
LEGACY_PAGES = {
    "index.html": "/",
    "login.html": "/login/",
    "register.html": "/register/",
    "transaction.html": "/transaction/",
    "settings.html": "/settings/",
    "dashboard.html": "/dashboard/",
    "forgot-password.html": "/login/",
}
urlpatterns += [
    path(old, RedirectView.as_view(url=new, permanent=True), name=f"legacy-{old}")
    for old, new in LEGACY_PAGES.items()
]
