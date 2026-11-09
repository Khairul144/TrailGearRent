"""
Management command untuk mengisi database katalog (Category, Product, InventoryLog)
dengan data peralatan outdoor Foresta Adventure (maksimal 7 produk per kategori).

Penggunaan:
    python manage.py seed_catalog
    python manage.py seed_catalog --reset
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from catalog.models import Category, InventoryLog, Product


class Command(BaseCommand):
    help = "Populasi database katalog peralatan outdoor (23 kategori, maks 7 produk/kategori)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Hapus seluruh data katalog sebelum melakukan seeding ulang.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        fixture_path = (
            Path(__file__).resolve().parent.parent.parent
            / "fixtures"
            / "foresta_catalog_seed.json"
        )
        if not fixture_path.exists():
            self.stderr.write(self.style.ERROR(f"File fixture tidak ditemukan: {fixture_path}"))
            return

        with open(fixture_path, "r", encoding="utf-8") as f:
            seed_data = json.load(f)

        if options["reset"]:
            InventoryLog.objects.all().delete()
            Product.objects.all().delete()
            Category.objects.all().delete()
            self.stdout.write(self.style.WARNING("Data katalog lama telah dihapus (--reset)."))

        categories_raw = seed_data.get("categories", [])
        products_raw = seed_data.get("products", [])

        cat_objs = {}
        cat_created = 0
        for c in categories_raw:
            obj, created = Category.objects.update_or_create(
                slug=c["slug"],
                defaults={
                    "name": c["name"],
                    "order": c.get("order", 0),
                    "show_in_menu": True,
                    "is_active": True,
                },
            )
            cat_objs[c["slug"]] = obj
            if created:
                cat_created += 1

        prod_created = 0
        prod_updated = 0
        per_cat_counter = {}

        for p in products_raw:
            c_slug = p["category_slug"]
            per_cat_counter[c_slug] = per_cat_counter.get(c_slug, 0)
            if per_cat_counter[c_slug] >= 7:
                continue  # Pastikan maksimal 7 barang per kategori

            category = cat_objs.get(c_slug)
            if not category:
                continue

            total_stock = max(1, int(p.get("total_stock", 5)))
            available_stock = max(0, min(total_stock, int(p.get("available_stock", total_stock))))
            price_per_day = max(1000, int(p.get("price_per_day", 15000)))
            price_type = p.get("price_type", "FLAT")
            price_type = p.get("price_type", "FLAT")
            if price_type not in {Product.PriceType.FLAT, Product.PriceType.VARIANT}:
                price_type = Product.PriceType.FLAT

            product, created = Product.objects.update_or_create(
                slug=p["slug"],
                defaults={
                    "category": category,
                    "name": p["name"],
                    "description": p.get("description") or p["name"],
                    "brand_name": p.get("brand_name") or "",
                    "price_per_day": price_per_day,
                    "price_type": price_type,
                    "total_stock": total_stock,
                    "available_stock": available_stock,
                    "image_filename": p.get("image_filename") or "",
                    "condition": Product.Condition.EXCELLENT,
                    "is_featured": bool(p.get("is_featured", False)),
                    "is_active": True,
                },
            )
            per_cat_counter[c_slug] += 1

            if created:
                prod_created += 1
                InventoryLog.objects.create(
                    product=product,
                    action=InventoryLog.Action.INITIAL_SEED,
                    quantity_change=available_stock,
                    stock_before=0,
                    stock_after=available_stock,
                    notes=f"Seeding awal katalog ({category.name})",
                )
            else:
                prod_updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeding selesai! Kategori: {len(cat_objs)} (baru: {cat_created}), "
                f"Produk: {prod_created + prod_updated} (baru: {prod_created}, diperbarui: {prod_updated})."
            )
        )
