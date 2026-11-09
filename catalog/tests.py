"""Unit tests untuk model, seeder, dan views aplikasi catalog."""

from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db.models import Count
from django.test import TestCase
from django.urls import reverse

from .models import Category, InventoryLog, Product


class CatalogModelTests(TestCase):
    """Pengujian model Category, Product, dan InventoryLog."""

    def setUp(self):
        self.category = Category.objects.create(
            name="Carrier 50L - 100L",
            slug="Carrier",
            order=1,
        )

    def test_create_product_and_properties(self):
        p = Product.objects.create(
            category=self.category,
            name="Carrier Osprey Atmos 65L",
            slug="Carrier-Osprey-Atmos-65L",
            price_per_day=95000,
            total_stock=5,
            available_stock=4,
            image_filename="products_gIVPh1AX193uQVzBUZpT.jpg",
        )
        self.assertEqual(p.formatted_price, "Rp 95.000")
        self.assertTrue(p.in_stock)
        self.assertEqual(
            p.get_image_url(),
            "/static/assets/img/product/products_gIVPh1AX193uQVzBUZpT.jpg",
        )

    def test_available_stock_cannot_exceed_total_stock(self):
        p = Product(
            category=self.category,
            name="Tenda Invalid",
            slug="tenda-invalid",
            price_per_day=30000,
            total_stock=3,
            available_stock=5,
        )
        with self.assertRaises(ValidationError):
            p.full_clean()

    def test_seed_catalog_command_populates_max_7_per_category(self):
        call_command("seed_catalog", "--reset")
        self.assertEqual(Category.objects.count(), 23)
        self.assertEqual(Product.objects.count(), 156)
        self.assertEqual(InventoryLog.objects.count(), 156)

        cats = Category.objects.annotate(c=Count("products"))
        for cat in cats:
            self.assertLessEqual(cat.c, 7, f"Kategori {cat.name} melebihi 7 barang")
            self.assertGreaterEqual(cat.c, 1, f"Kategori {cat.name} kosong")


class CatalogViewTests(TestCase):
    """Pengujian halaman beranda, /products/, filter, pencarian, jadwal, dan detail produk."""

    @classmethod
    def setUpTestData(cls):
        call_command("seed_catalog", "--reset")

    def test_home_renders_featured_products_from_db(self):
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["featured_products"]), 16)
        self.assertContains(resp, "Carrier - Quenstown - 50L - Coklat Muda")

    def test_product_list_renders_paginated_items_and_categories(self):
        resp = self.client.get(reverse("catalog:product_list"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.context["categories"]), 23)
        self.assertEqual(resp.context["paginator"].count, 156)
        self.assertEqual(len(resp.context["products"]), 20)
        self.assertContains(resp, "Daftar Peralatan")

    def test_product_list_filter_by_category_and_search(self):
        url = reverse("catalog:product_list")
        resp = self.client.get(url, {"cat": ["Carrier", "Tenda4Orang"]})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["paginator"].count, 14)

        resp_search = self.client.get(url, {"q": "Osprey"})
        self.assertEqual(resp_search.status_code, 200)
        self.assertGreaterEqual(resp_search.context["paginator"].count, 1)
        for p in resp_search.context["products"]:
            self.assertIn("osprey", p.name.lower())

    def test_product_list_schedule_and_sorting(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        url = reverse("catalog:product_list")
        resp = self.client.get(url, {"tgl": tomorrow, "durasi": "3", "sort": "termurah"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["schedule"]["duration"], 3)
        prices = [p.price_per_day for p in resp.context["products"]]
        self.assertEqual(prices, sorted(prices))

    def test_product_detail_page(self):
        product = Product.objects.first()
        url = reverse("catalog:product_detail", kwargs={"slug": product.slug})
        resp = self.client.get(url, {"durasi": "4"})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, product.name)
        self.assertEqual(resp.context["estimated_total"], product.price_per_day * 4)
