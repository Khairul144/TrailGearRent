"""Context processor: kategori aktif untuk dropdown "Kategori" di navbar.

QuerySet bersifat lazy, jadi query hanya dijalankan ketika template
benar-benar merender menu kategori.
"""

from .models import Category


def nav_categories(request):
    return {
        "nav_categories": Category.objects.filter(is_active=True, show_in_menu=True).order_by(
            "order", "name"
        ),
    }
