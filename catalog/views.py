"""
Views publik Modul Katalog & Inventaris Alat.

- product_list  : /products/          -> Daftar Peralatan (filter kategori, cari,
                                         urutkan, jadwal sewa, paginasi)
- product_detail: /product/<slug>/    -> Detail peralatan + estimasi biaya sewa

Semua parameter GET divalidasi dengan whitelist sebelum dipakai di ORM,
sehingga input pengguna tidak pernah disusun langsung menjadi query.
"""

from datetime import date, datetime, timedelta

from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import get_object_or_404, render

from .models import Category, Product

PRODUCTS_PER_PAGE = 20  # sama seperti limitPerPage di Foresta
MAX_SEARCH_LENGTH = 100
MIN_DURATION = 1
MAX_DURATION = 30

SORT_OPTIONS = {
    "populer": ("Paling Populer", ("-is_featured", "category__order", "name")),
    "termurah": ("Harga Termurah", ("price_per_day", "name")),
    "termahal": ("Harga Termahal", ("-price_per_day", "name")),
    "nama": ("Nama A-Z", ("name",)),
    "terbaru": ("Terbaru", ("-created_at", "name")),
}
DEFAULT_SORT = "populer"


def _parse_schedule(request):
    """Ambil & validasi jadwal sewa (?tgl=YYYY-MM-DD&durasi=N) dari query string."""
    start = None
    raw_start = (request.GET.get("tgl") or "").strip()
    if raw_start:
        try:
            parsed = datetime.strptime(raw_start, "%Y-%m-%d").date()
            if parsed >= date.today():
                start = parsed
        except ValueError:
            start = None

    duration = None
    raw_duration = (request.GET.get("durasi") or "").strip()
    if raw_duration.isdigit():
        duration = min(max(int(raw_duration), MIN_DURATION), MAX_DURATION)

    # Aturan sewa: ambil hari H, sewa N hari, pengembalian maks. H + N + 1
    return_date = start + timedelta(days=duration + 1) if (start and duration) else None
    return {"start": start, "duration": duration, "return_date": return_date}


def _schedule_querystring(schedule):
    parts = []
    if schedule["start"]:
        parts.append(f"tgl={schedule['start'].isoformat()}")
    if schedule["duration"]:
        parts.append(f"durasi={schedule['duration']}")
    return "&".join(parts)


def home(request):
    """Beranda: tampilkan produk unggulan dari database (Pilihan Terbaik Minggu Ini)."""
    featured_products = (
        Product.objects.filter(is_active=True, is_featured=True, category__is_active=True)
        .select_related("category")
        .order_by("category__order", "name")[:16]
    )
    return render(request, "index.html", {"featured_products": featured_products})


def product_list(request):
    categories = list(Category.objects.filter(is_active=True).order_by("order", "name"))
    valid_slugs = {c.slug for c in categories}

    # Filter kategori (multi-select, sama seperti ?cat[]= di Foresta)
    selected_cats = [s for s in request.GET.getlist("cat") if s in valid_slugs]
    # Hilangkan duplikat dengan urutan tetap
    selected_cats = list(dict.fromkeys(selected_cats))

    query = (request.GET.get("q") or "").strip()[:MAX_SEARCH_LENGTH]

    sort = request.GET.get("sort") or DEFAULT_SORT
    if sort not in SORT_OPTIONS:
        sort = DEFAULT_SORT

    only_available = request.GET.get("tersedia") == "1"

    schedule = _parse_schedule(request)

    products = Product.objects.filter(is_active=True, category__is_active=True).select_related(
        "category"
    )
    if selected_cats:
        products = products.filter(category__slug__in=selected_cats)
    if query:
        products = products.filter(
            Q(name__icontains=query)
            | Q(brand_name__icontains=query)
            | Q(description__icontains=query)
            | Q(category__name__icontains=query)
        )
    if only_available:
        products = products.filter(available_stock__gt=0)

    products = products.order_by(*SORT_OPTIONS[sort][1])

    paginator = Paginator(products, PRODUCTS_PER_PAGE)
    page_obj = paginator.get_page(request.GET.get("page"))

    # Querystring tanpa "page" untuk link paginasi agar filter tetap terbawa
    params = request.GET.copy()
    params.pop("page", None)
    base_querystring = params.urlencode()

    selected_cat_objs = [c for c in categories if c.slug in selected_cats]
    if len(selected_cat_objs) == 1:
        page_title = selected_cat_objs[0].name
    else:
        page_title = "Daftar Peralatan"

    context = {
        "categories": categories,
        "selected_cats": selected_cats,
        "selected_cat_objs": selected_cat_objs,
        "query": query,
        "sort": sort,
        "sort_options": [(key, label) for key, (label, _) in SORT_OPTIONS.items()],
        "only_available": only_available,
        "schedule": schedule,
        "schedule_qs": _schedule_querystring(schedule),
        "page_obj": page_obj,
        "products": page_obj.object_list,
        "paginator": paginator,
        "page_range": paginator.get_elided_page_range(page_obj.number, on_each_side=2, on_ends=1),
        "base_querystring": base_querystring,
        "page_title": page_title,
        "has_filters": bool(selected_cats or query or only_available),
    }
    return render(request, "catalog/product_list.html", context)


def product_detail(request, slug):
    product = get_object_or_404(
        Product.objects.select_related("category"),
        slug=slug,
        is_active=True,
        category__is_active=True,
    )
    schedule = _parse_schedule(request)
    duration = schedule["duration"] or 2
    estimated_total = product.price_per_day * duration

    related_products = (
        Product.objects.filter(category=product.category, is_active=True)
        .exclude(pk=product.pk)
        .order_by("-is_featured", "name")[:4]
    )

    context = {
        "product": product,
        "schedule": schedule,
        "schedule_qs": _schedule_querystring(schedule),
        "duration": duration,
        "duration_choices": range(MIN_DURATION, MAX_DURATION + 1),
        "estimated_total": estimated_total,
        "estimated_total_fmt": "Rp " + f"{estimated_total:,}".replace(",", "."),
        "related_products": related_products,
    }
    return render(request, "catalog/product_detail.html", context)
