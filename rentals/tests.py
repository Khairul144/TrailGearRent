"""
Unit test Modul Keranjang & Pemesanan Sewa (rentals).

Cakupan:
- penambahan keranjang (session & user), penggabungan item, validasi stok
- kalkulasi harga sewa, deposit, subtotal, tanggal kembali
- pembatasan checkout (wajib login) & pembuatan RentalOrder
- mutasi stok inventaris saat konfirmasi/ambil/kembali/batal
- hak akses nota pesanan & aksi staf
"""

import re
import shutil
import tempfile
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from accounts.models import SecurityEvent
from accounts.roles import ROLE_ADMIN, ROLE_CASHIER, ROLE_CUSTOMER, assign_role
from catalog.models import Category, InventoryLog, Product

from . import services
from .models import Cart, CartItem, RentalOrder, RentalOrderItem
from .services import CartError, OrderTransitionError, StockError

User = get_user_model()

TOMORROW = date.today() + timedelta(days=1)


class RentalTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.category = Category.objects.create(
            name="Tenda", slug="tenda", order=1, is_active=True
        )
        cls.product = Product.objects.create(
            category=cls.category,
            name="Tenda Dome 4P",
            slug="tenda-dome-4p",
            price_per_day=25000,
            total_stock=3,
            available_stock=3,
            is_active=True,
        )
        cls.product2 = Product.objects.create(
            category=cls.category,
            name="Carrier 60L",
            slug="carrier-60l",
            price_per_day=15000,
            total_stock=2,
            available_stock=2,
            is_active=True,
        )

        cls.customer = User.objects.create_user(
            username="budi", email="budi@example.com", password="Rahasia#123"
        )
        assign_role(cls.customer, ROLE_CUSTOMER)

        cls.cashier = User.objects.create_user(
            username="kasir", email="kasir@example.com", password="Rahasia#123"
        )
        assign_role(cls.cashier, ROLE_CASHIER)

        cls.admin_user = User.objects.create_user(
            username="admin", email="admin@example.com", password="Rahasia#123"
        )
        assign_role(cls.admin_user, ROLE_ADMIN)

    def make_order(self, quantity=2, duration=2, user=None, status=None):
        """Helper: buat order langsung via service (tanpa lewat view)."""
        user = user or self.customer
        cart, _ = Cart.objects.get_or_create(user=user)
        services.add_item_to_cart(
            cart,
            self.product,
            start_date=TOMORROW,
            duration_days=duration,
            quantity=quantity,
        )
        order = services.create_order_from_cart(
            cart,
            user,
            {
                "full_name": "Budi Santoso",
                "phone_number": "081234567890",
                "id_card_number": "3301234567890001",
                "id_card_type": RentalOrder.IdCardType.KTP,
                "pickup_plan_date": TOMORROW,
                "return_plan_date": TOMORROW + timedelta(days=duration + 1),
                "notes": "Ambil sore",
            },
        )
        if status:
            order.status = status
            order.save(update_fields=["status"])
        return order


class CartCalculationTests(RentalTestBase):
    def test_cart_item_calculation(self):
        cart = Cart.objects.create(user=self.customer)
        item = CartItem.objects.create(
            cart=cart,
            product=self.product,
            start_date=TOMORROW,
            duration_days=3,
            quantity=2,
        )
        self.assertEqual(item.rental_price_total, 25000 * 3 * 2)
        self.assertEqual(item.subtotal, 25000 * 3 * 2)
        self.assertEqual(item.return_date, TOMORROW + timedelta(days=4))
        self.assertEqual(cart.total_quantity, 2)
        self.assertEqual(cart.grand_total, item.subtotal)

    def test_multi_item_cart_totals(self):
        cart = Cart.objects.create(user=self.customer)
        services.add_item_to_cart(
            cart, self.product, start_date=TOMORROW, duration_days=2, quantity=1
        )
        services.add_item_to_cart(
            cart, self.product2, start_date=TOMORROW, duration_days=2, quantity=2
        )
        expected_rental = (25000 * 2) + (15000 * 2 * 2)
        self.assertEqual(cart.total_rental_fee, expected_rental)
        self.assertEqual(cart.grand_total, expected_rental)


class AddToCartViewTests(RentalTestBase):
    def test_add_to_cart_creates_session_cart(self):
        response = self.client.post(
            reverse("rentals:add_to_cart", args=[self.product.slug]),
            {"tgl": TOMORROW.isoformat(), "durasi": 2, "qty": 2},
        )
        self.assertEqual(response.status_code, 302)
        cart = Cart.objects.get(session_key__isnull=False, user__isnull=True)
        self.assertEqual(cart.items.count(), 1)
        self.assertEqual(cart.items.first().quantity, 2)

    def test_add_to_cart_ajax_returns_json_count(self):
        response = self.client.post(
            reverse("rentals:add_to_cart", args=[self.product.slug]),
            {"tgl": TOMORROW.isoformat(), "durasi": 1, "qty": 1},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["cart_items_count"], 1)

    def test_same_slot_merges_quantity(self):
        cart = Cart.objects.create(user=self.customer)
        services.add_item_to_cart(
            cart, self.product, start_date=TOMORROW, duration_days=2, quantity=1
        )
        services.add_item_to_cart(
            cart, self.product, start_date=TOMORROW, duration_days=2, quantity=1
        )
        self.assertEqual(cart.items.count(), 1)
        self.assertEqual(cart.items.first().quantity, 2)

    def test_quantity_exceeds_stock_rejected(self):
        cart = Cart.objects.create(user=self.customer)
        with self.assertRaises(StockError):
            services.add_item_to_cart(
                cart, self.product, start_date=TOMORROW, duration_days=1, quantity=99
            )
        self.assertEqual(cart.items.count(), 0)

    def test_merge_beyond_stock_rejected(self):
        cart = Cart.objects.create(user=self.customer)
        services.add_item_to_cart(
            cart, self.product, start_date=TOMORROW, duration_days=1, quantity=2
        )
        with self.assertRaises(StockError):
            services.add_item_to_cart(
                cart, self.product, start_date=TOMORROW, duration_days=1, quantity=2
            )
        self.assertEqual(cart.items.first().quantity, 2)

    def test_missing_date_rejected(self):
        response = self.client.post(
            reverse("rentals:add_to_cart", args=[self.product.slug]),
            {"durasi": 2, "qty": 1},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])

    def test_past_date_rejected(self):
        cart = Cart.objects.create(user=self.customer)
        with self.assertRaises(CartError):
            services.add_item_to_cart(
                cart,
                self.product,
                start_date=date.today() - timedelta(days=1),
                duration_days=1,
                quantity=1,
            )

    def test_out_of_stock_product_rejected(self):
        self.product.available_stock = 0
        self.product.save(update_fields=["available_stock"])
        cart = Cart.objects.create(user=self.customer)
        with self.assertRaises(StockError):
            services.add_item_to_cart(
                cart, self.product, start_date=TOMORROW, duration_days=1, quantity=1
            )


class CartPageTests(RentalTestBase):
    def test_cart_page_renders_totals(self):
        cart = Cart.objects.create(user=self.customer)
        services.add_item_to_cart(
            cart, self.product, start_date=TOMORROW, duration_days=2, quantity=1
        )
        self.client.force_login(self.customer)
        response = self.client.get(reverse("rentals:cart_detail"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Rp 50.000")  # murni sewa 25.000 x 2 hari
        self.assertContains(response, "Harga sewa Rp 25.000/kuantitas/hari")
        self.assertContains(response, "Maks. Pengembalian")
        self.assertContains(response, "KTP Asli Fisik")

    def test_update_cart_schedule_syncs_all_items(self):
        cart = Cart.objects.create(user=self.customer)
        services.add_item_to_cart(
            cart, self.product, start_date=TOMORROW, duration_days=1, quantity=1
        )
        services.add_item_to_cart(
            cart, self.product2, start_date=TOMORROW, duration_days=2, quantity=2
        )
        self.client.force_login(self.customer)
        new_start = TOMORROW + timedelta(days=2)
        response = self.client.post(
            reverse("rentals:update_cart_schedule"),
            {"tgl": new_start.isoformat(), "durasi": 4},
        )
        self.assertEqual(response.status_code, 302)
        for item in cart.items.all():
            self.assertEqual(item.start_date, new_start)
            self.assertEqual(item.duration_days, 4)

    def test_empty_cart_page(self):
        response = self.client.get(reverse("rentals:cart_detail"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Keranjang kamu masih kosong")

    def test_update_quantity(self):
        cart = Cart.objects.create(user=self.customer)
        item = services.add_item_to_cart(
            cart, self.product, start_date=TOMORROW, duration_days=1, quantity=1
        )
        self.client.force_login(self.customer)
        self.client.post(
            reverse("rentals:update_cart_item", args=[item.pk]), {"quantity": 3}
        )
        item.refresh_from_db()
        self.assertEqual(item.quantity, 3)

    def test_update_quantity_beyond_stock_keeps_old_value(self):
        cart = Cart.objects.create(user=self.customer)
        item = services.add_item_to_cart(
            cart, self.product, start_date=TOMORROW, duration_days=1, quantity=1
        )
        self.client.force_login(self.customer)
        self.client.post(
            reverse("rentals:update_cart_item", args=[item.pk]), {"quantity": 10}
        )
        item.refresh_from_db()
        self.assertEqual(item.quantity, 1)

    def test_remove_item(self):
        cart = Cart.objects.create(user=self.customer)
        item = services.add_item_to_cart(
            cart, self.product, start_date=TOMORROW, duration_days=1, quantity=1
        )
        self.client.force_login(self.customer)
        self.client.post(reverse("rentals:remove_from_cart", args=[item.pk]))
        self.assertEqual(cart.items.count(), 0)

    def test_anonymous_cart_adopted_after_login(self):
        self.client.post(
            reverse("rentals:add_to_cart", args=[self.product.slug]),
            {"tgl": TOMORROW.isoformat(), "durasi": 1, "qty": 2},
        )
        self.client.force_login(self.customer)
        # Akses halaman apa pun yang memakai get_cart -> keranjang diadopsi.
        response = self.client.get(reverse("rentals:cart_detail"))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Cart.objects.filter(user=self.customer).exists())
        self.assertFalse(Cart.objects.filter(user__isnull=True).exists())

    def test_guest_cart_survives_real_login(self):
        """Keranjang tamu harus ikut setelah login (session key berputar)."""
        self.client.post(
            reverse("rentals:add_to_cart", args=[self.product.slug]),
            {"tgl": TOMORROW.isoformat(), "durasi": 1, "qty": 2},
        )
        response = self.client.post(
            reverse("accounts:login"),
            {
                "username": "budi",
                "password": "Rahasia#123",
                "next": reverse("rentals:checkout"),
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("rentals:checkout"))

        checkout = self.client.get(reverse("rentals:checkout"))
        self.assertEqual(checkout.status_code, 200)

        cart = Cart.objects.get(user=self.customer)
        self.assertEqual(cart.items.count(), 1)
        self.assertEqual(cart.items.first().quantity, 2)

    def test_card_add_button_visible_only_when_logged_in(self):
        url = reverse("catalog:product_list")
        anon = self.client.get(url)
        self.assertNotContains(anon, 'class="btn-add-cart"')
        self.assertContains(anon, "Masuk untuk sewa")

        self.client.force_login(self.customer)
        logged = self.client.get(url)
        self.assertContains(logged, 'class="btn-add-cart"')
        self.assertContains(
            logged, reverse("rentals:add_to_cart", args=[self.product.slug])
        )
        self.assertNotContains(logged, "Masuk untuk sewa")

    def test_card_quick_add_requires_login(self):
        response = self.client.post(
            reverse("rentals:add_to_cart", args=[self.product.slug]),
            {"tgl": TOMORROW.isoformat(), "durasi": 1, "qty": 1},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertEqual(response.json()["cart_items_count"], 1)

    def test_navbar_badge_shows_count(self):
        cart = Cart.objects.create(user=self.customer)
        services.add_item_to_cart(
            cart, self.product, start_date=TOMORROW, duration_days=1, quantity=2
        )
        self.client.force_login(self.customer)
        response = self.client.get(reverse("catalog:product_list"))
        self.assertEqual(response.context["cart_items_count"], 2)


class CheckoutTests(RentalTestBase):
    def _payload(self, **overrides):
        data = {
            "full_name": "Budi Santoso",
            "phone_number": "081234567890",
            "id_card_type": "KTP",
            "id_card_number": "3301234567890001",
            "pickup_plan_date": TOMORROW.isoformat(),
            "return_plan_date": (TOMORROW + timedelta(days=4)).isoformat(),
            "payment_method": "TRANSFER_BCA",
            "notes": "Ambil sore",
        }
        data.update(overrides)
        return data

    def test_checkout_requires_login(self):
        response = self.client.get(reverse("rentals:checkout"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)
        self.assertIn("next=/checkout/", response.url)

    def test_checkout_creates_order_and_clears_cart(self):
        cart = Cart.objects.create(user=self.customer)
        services.add_item_to_cart(
            cart, self.product, start_date=TOMORROW, duration_days=3, quantity=2
        )
        self.client.force_login(self.customer)

        response = self.client.post(reverse("rentals:checkout"), self._payload())
        self.assertEqual(response.status_code, 302)

        order = RentalOrder.objects.get(user=self.customer)
        self.assertTrue(order.order_code.startswith("TG-"))
        self.assertEqual(order.status, RentalOrder.Status.MENUNGGU_PEMBAYARAN)
        self.assertEqual(order.total_rental_fee, 25000 * 3 * 2)
        self.assertEqual(order.grand_total, 25000 * 3 * 2)

        item = order.items.get()
        self.assertEqual(item.unit_price, 25000)
        self.assertEqual(item.quantity, 2)
        self.assertEqual(item.duration_days, 3)
        self.assertEqual(item.subtotal, 25000 * 3 * 2)

        # Keranjang dikosongkan setelah checkout.
        self.assertEqual(cart.items.count(), 0)
        # Stok belum berubah sebelum konfirmasi.
        self.product.refresh_from_db()
        self.assertEqual(self.product.available_stock, 3)

        # Nota dapat dibuka.
        detail = self.client.get(
            reverse("rentals:order_detail", args=[order.order_code])
        )
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, order.order_code)

    def test_checkout_blocks_when_stock_changed(self):
        cart = Cart.objects.create(user=self.customer)
        services.add_item_to_cart(
            cart, self.product, start_date=TOMORROW, duration_days=1, quantity=3
        )
        self.product.available_stock = 1
        self.product.save(update_fields=["available_stock"])

        self.client.force_login(self.customer)
        response = self.client.post(reverse("rentals:checkout"), self._payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(RentalOrder.objects.count(), 0)

    def test_checkout_rejects_past_pickup_date(self):
        cart = Cart.objects.create(user=self.customer)
        services.add_item_to_cart(
            cart, self.product, start_date=TOMORROW, duration_days=1, quantity=1
        )
        self.client.force_login(self.customer)
        self.client.post(
            reverse("rentals:checkout"),
            self._payload(
                pickup_plan_date=(date.today() - timedelta(days=2)).isoformat()
            ),
        )
        self.assertEqual(RentalOrder.objects.count(), 0)

    def test_order_detail_forbidden_for_other_customer(self):
        order = self.make_order()
        other = User.objects.create_user(
            username="siti", email="siti@example.com", password="Rahasia#123"
        )
        assign_role(other, ROLE_CUSTOMER)
        self.client.force_login(other)
        response = self.client.get(
            reverse("rentals:order_detail", args=[order.order_code])
        )
        self.assertEqual(response.status_code, 403)

    def test_transaction_page_lists_own_orders(self):
        order = self.make_order()
        self.client.force_login(self.customer)
        response = self.client.get(reverse("accounts:transaction_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, order.order_code)

    def test_checkout_nik_16_digits_validation(self):
        cart = Cart.objects.create(user=self.customer)
        services.add_item_to_cart(
            cart, self.product, start_date=TOMORROW, duration_days=1, quantity=1
        )
        self.client.force_login(self.customer)

        for bad_nik in ("1234567890", "33012345678900012", "330123456789000A", "3301 2345 6789 0001"):
            with self.subTest(bad_nik=bad_nik):
                resp = self.client.post(
                    reverse("rentals:checkout"),
                    self._payload(id_card_number=bad_nik),
                )
                self.assertEqual(resp.status_code, 200)
                self.assertEqual(RentalOrder.objects.count(), 0)

        # Pilihan selain KTP juga ditolak
        resp_sim = self.client.post(
            reverse("rentals:checkout"),
            self._payload(id_card_type="SIM"),
        )
        self.assertEqual(resp_sim.status_code, 200)
        self.assertEqual(RentalOrder.objects.count(), 0)

    def test_cod_order_hides_upload_form_and_shows_cod_message(self):
        cart = Cart.objects.create(user=self.customer)
        services.add_item_to_cart(
            cart, self.product, start_date=TOMORROW, duration_days=2, quantity=1
        )
        self.client.force_login(self.customer)
        resp = self.client.post(
            reverse("rentals:checkout"),
            self._payload(payment_method="CASH"),
        )
        self.assertEqual(resp.status_code, 302)
        order = RentalOrder.objects.get(user=self.customer)
        self.assertEqual(order.payment_method, RentalOrder.PaymentMethod.CASH)

        detail = self.client.get(reverse("rentals:order_detail", args=[order.order_code]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(
            detail,
            "Pembayaran dilakukan langsung secara tunai di kasir toko saat pengambilan alat.",
        )
        self.assertNotContains(detail, "Unggah bukti transfer")
        self.assertContains(detail, "012-xxxxxxx")
        self.assertContains(detail, "QR Code QRIS Dummy TrailGear Rent")
        self.assertContains(detail, "BERITA ACARA SERAH TERIMA ALAT")


class StockMutationTests(RentalTestBase):
    def test_confirm_deducts_stock_and_logs(self):
        order = self.make_order(quantity=2)
        services.set_order_status(
            order, RentalOrder.Status.DIKONFIRMASI, actor=self.cashier
        )
        self.product.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(self.product.available_stock, 1)
        self.assertTrue(order.stock_deducted)

        log = InventoryLog.objects.get(product=self.product, action="RENTED")
        self.assertEqual(log.quantity_change, -2)
        self.assertEqual(log.stock_before, 3)
        self.assertEqual(log.stock_after, 1)
        self.assertEqual(log.notes, f"Order {order.order_code}")
        self.assertEqual(log.changed_by, self.cashier)

    def test_pickup_does_not_double_deduct(self):
        order = self.make_order(quantity=2)
        services.set_order_status(order, RentalOrder.Status.DIKONFIRMASI)
        services.set_order_status(order, RentalOrder.Status.DIAMBIL)
        self.product.refresh_from_db()
        self.assertEqual(self.product.available_stock, 1)
        self.assertEqual(
            InventoryLog.objects.filter(action="RENTED").count(), 1
        )

    def test_return_restores_stock(self):
        order = self.make_order(quantity=2)
        services.set_order_status(order, RentalOrder.Status.DIKONFIRMASI)
        services.set_order_status(order, RentalOrder.Status.DIAMBIL)
        services.set_order_status(
            order, RentalOrder.Status.KEMBALI, actor=self.cashier
        )

        self.product.refresh_from_db()
        order.refresh_from_db()
        self.assertEqual(self.product.available_stock, 3)
        self.assertFalse(order.stock_deducted)

        log = InventoryLog.objects.get(action="RETURNED")
        self.assertEqual(log.quantity_change, 2)
        self.assertEqual(log.stock_before, 1)
        self.assertEqual(log.stock_after, 3)

    def test_cancel_confirmed_order_restores_stock(self):
        order = self.make_order(quantity=2)
        services.set_order_status(order, RentalOrder.Status.DIKONFIRMASI)
        services.set_order_status(order, RentalOrder.Status.DIBATALKAN)
        self.product.refresh_from_db()
        self.assertEqual(self.product.available_stock, 3)
        self.assertTrue(InventoryLog.objects.filter(action="RETURNED").exists())

    def test_cancel_before_confirm_keeps_stock(self):
        order = self.make_order(quantity=2)
        services.set_order_status(order, RentalOrder.Status.DIBATALKAN)
        self.product.refresh_from_db()
        self.assertEqual(self.product.available_stock, 3)
        self.assertEqual(InventoryLog.objects.count(), 0)

    def test_invalid_transition_rejected(self):
        order = self.make_order()
        with self.assertRaises(OrderTransitionError):
            services.set_order_status(order, RentalOrder.Status.KEMBALI)
        order.refresh_from_db()
        self.assertEqual(order.status, RentalOrder.Status.MENUNGGU_PEMBAYARAN)

    def test_confirm_fails_when_stock_insufficient(self):
        order = self.make_order(quantity=2)
        self.product.available_stock = 1
        self.product.save(update_fields=["available_stock"])
        with self.assertRaises(StockError):
            services.set_order_status(order, RentalOrder.Status.DIKONFIRMASI)
        order.refresh_from_db()
        self.assertEqual(order.status, RentalOrder.Status.MENUNGGU_PEMBAYARAN)
        self.assertFalse(order.stock_deducted)


class StaffActionTests(RentalTestBase):
    def test_cashier_confirm_via_dashboard_action(self):
        order = self.make_order(quantity=2)
        self.client.force_login(self.cashier)
        response = self.client.post(
            reverse(
                "rentals:staff_order_action", args=[order.order_code, "confirm"]
            )
        )
        self.assertEqual(response.status_code, 302)
        order.refresh_from_db()
        self.assertEqual(order.status, RentalOrder.Status.DIKONFIRMASI)
        self.product.refresh_from_db()
        self.assertEqual(self.product.available_stock, 1)

    def test_full_flow_to_return(self):
        order = self.make_order(quantity=2)
        self.client.force_login(self.cashier)
        for action in ("confirm", "pickup", "return"):
            self.client.post(
                reverse("rentals:staff_order_action", args=[order.order_code, action])
            )
        order.refresh_from_db()
        self.assertEqual(order.status, RentalOrder.Status.KEMBALI)
        self.product.refresh_from_db()
        self.assertEqual(self.product.available_stock, 3)

    def test_customer_cannot_perform_staff_action(self):
        order = self.make_order()
        self.client.force_login(self.customer)
        response = self.client.post(
            reverse(
                "rentals:staff_order_action", args=[order.order_code, "confirm"]
            )
        )
        self.assertEqual(response.status_code, 403)
        order.refresh_from_db()
        self.assertEqual(order.status, RentalOrder.Status.MENUNGGU_PEMBAYARAN)

    def test_action_requires_post(self):
        order = self.make_order()
        self.client.force_login(self.cashier)
        response = self.client.get(
            reverse("rentals:staff_order_action", args=[order.order_code, "confirm"])
        )
        self.assertEqual(response.status_code, 405)

    def test_staff_dashboard_lists_open_orders(self):
        order = self.make_order()
        self.client.force_login(self.cashier)
        response = self.client.get(reverse("accounts:cashier_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, order.order_code)
        response = self.client.get(reverse("rentals:staff_order_list"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, order.order_code)

    def test_admin_dashboard_lists_open_orders(self):
        order = self.make_order()
        self.client.force_login(self.admin_user)
        response = self.client.get(reverse("accounts:admin_dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, order.order_code)


# ---------------------------------------------------------------------------
# Fase 2.5 — upload bukti pembayaran & hardening berkas
# ---------------------------------------------------------------------------
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"0" * 64
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"0" * 64
PDF_BYTES = b"%PDF-1.4\n" + b"0" * 64
WEBP_BYTES = b"RIFF" + b"\x00\x00\x00\x00" + b"WEBP" + b"0" * 64
FAKE_TEXT = b"<?php system($_GET['cmd']); ?>"


class PaymentProofTests(RentalTestBase):
    def setUp(self):
        super().setUp()
        self.media_root = tempfile.mkdtemp(prefix="tg-proof-")
        self.media_override = override_settings(MEDIA_ROOT=self.media_root)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.addCleanup(shutil.rmtree, self.media_root, True)

        self.order = self.make_order(quantity=1)
        self.client.force_login(self.customer)

    # ---- helpers -------------------------------------------------------
    def upload_url(self, order=None):
        return reverse(
            "rentals:upload_payment_proof",
            args=[(order or self.order).order_code],
        )

    def do_upload(self, name="bukti.jpg", content=JPEG_BYTES, method="TRANSFER_BCA", order=None):
        return self.client.post(
            self.upload_url(order=order),
            {
                "payment_method": method,
                "payment_proof": SimpleUploadedFile(name, content),
            },
        )

    # ---- happy path ----------------------------------------------------
    def test_valid_jpeg_saved_with_uuid_name(self):
        response = self.do_upload()
        self.assertEqual(response.status_code, 302)

        self.order.refresh_from_db()
        self.assertTrue(self.order.has_payment_proof())
        self.assertEqual(self.order.payment_method, "TRANSFER_BCA")
        self.assertIsNotNone(self.order.payment_proof_uploaded_at)
        self.assertRegex(
            self.order.payment_proof.name,
            r"^payment_proofs/\d{4}/\d{2}/[0-9a-f]{32}\.jpg$",
        )
        # nama asli tidak pernah dipakai
        self.assertNotIn("bukti", self.order.payment_proof.name.split("/")[-1])
        import os

        self.assertTrue(os.path.isfile(self.order.payment_proof.path))
        self.assertTrue(
            SecurityEvent.objects.filter(
                event_type=SecurityEvent.PAYMENT_PROOF_UPLOADED,
                status=SecurityEvent.STATUS_SUCCESS,
            ).exists()
        )

    def test_valid_png_pdf_webp_accepted(self):
        cases = [
            ("bukti.png", PNG_BYTES, "image/png"),
            ("bukti.pdf", PDF_BYTES, "application/pdf"),
            ("bukti.webp", WEBP_BYTES, "image/webp"),
        ]
        for name, content, _ctype in cases:
            with self.subTest(name=name):
                self.order.payment_proof = None
                self.order.payment_method = "TRANSFER_BCA"
                self.order.save(update_fields=["payment_proof", "payment_method"])
                response = self.do_upload(name=name, content=content)
                self.assertEqual(response.status_code, 302)
                self.order.refresh_from_db()
                self.assertTrue(self.order.payment_proof.name.endswith(name.split(".")[-1]))

    def test_reupload_replaces_old_file(self):
        self.do_upload(name="first.jpg", content=JPEG_BYTES)
        self.order.refresh_from_db()
        import os

        old_path = self.order.payment_proof.path
        self.assertTrue(os.path.isfile(old_path))

        self.do_upload(name="second.png", content=PNG_BYTES)
        self.order.refresh_from_db()
        self.assertTrue(self.order.payment_proof.name.endswith(".png"))
        self.assertFalse(os.path.isfile(old_path))

    # ---- penolakan berkas ---------------------------------------------
    def test_reject_file_over_5mb(self):
        big = b"\xff\xd8\xff\xe0" + b"0" * (5 * 1024 * 1024)
        response = self.do_upload(name="besar.jpg", content=big)
        self.assertEqual(response.status_code, 400)
        self.order.refresh_from_db()
        self.assertFalse(self.order.has_payment_proof())
        self.assertTrue(
            SecurityEvent.objects.filter(
                event_type=SecurityEvent.PAYMENT_PROOF_REJECTED
            ).exists()
        )

    def test_reject_empty_file(self):
        response = self.do_upload(name="kosong.jpg", content=b"")
        self.assertEqual(response.status_code, 400)
        self.order.refresh_from_db()
        self.assertFalse(self.order.has_payment_proof())

    def test_reject_forbidden_extensions(self):
        for name in ("shell.php", "virus.exe", "run.sh", "page.html", "x.svg", "app.js"):
            with self.subTest(name=name):
                response = self.do_upload(name=name, content=JPEG_BYTES)
                self.assertEqual(response.status_code, 400)
                self.order.refresh_from_db()
                self.assertFalse(self.order.has_payment_proof())

    def test_reject_double_extension(self):
        for name in ("bukti.php.jpg", "shell.phtml.png", "a.exe.pdf"):
            with self.subTest(name=name):
                response = self.do_upload(name=name, content=JPEG_BYTES)
                self.assertEqual(response.status_code, 400)
                self.order.refresh_from_db()
                self.assertFalse(self.order.has_payment_proof())

    def test_reject_spoofed_jpg_by_magic_bytes(self):
        response = self.do_upload(name="tampak.jpg", content=FAKE_TEXT)
        self.assertEqual(response.status_code, 400)
        self.order.refresh_from_db()
        self.assertFalse(self.order.has_payment_proof())

    def test_reject_png_header_mismatch(self):
        response = self.do_upload(name="palsu.png", content=JPEG_BYTES)
        self.assertEqual(response.status_code, 400)
        self.order.refresh_from_db()
        self.assertFalse(self.order.has_payment_proof())

    # ---- otorisasi & status -------------------------------------------
    def test_idor_other_user_cannot_upload(self):
        other = User.objects.create_user(
            username="other_proof", email="other_proof@example.com", password="Rahasia#123"
        )
        assign_role(other, ROLE_CUSTOMER)
        self.client.force_login(other)

        response = self.do_upload()
        self.assertEqual(response.status_code, 403)
        self.order.refresh_from_db()
        self.assertFalse(self.order.has_payment_proof())
        self.assertTrue(
            SecurityEvent.objects.filter(
                event_type=SecurityEvent.ACCESS_DENIED
            ).exists()
        )

    def test_anonymous_redirected_to_login(self):
        self.client.logout()
        response = self.do_upload()
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_upload_rejected_when_confirmed_or_finished(self):
        for status in (RentalOrder.Status.DIKONFIRMASI, RentalOrder.Status.KEMBALI):
            with self.subTest(status=status):
                order = self.make_order(quantity=1, status=status)
                response = self.do_upload(order=order)
                self.assertEqual(response.status_code, 302)
                order.refresh_from_db()
                self.assertFalse(order.has_payment_proof())

    def test_upload_page_hides_form_after_confirmation(self):
        self.do_upload()
        self.client.force_login(self.cashier)
        self.client.post(
            reverse("rentals:staff_order_action", args=[self.order.order_code, "confirm"])
        )
        self.client.force_login(self.customer)
        response = self.client.get(
            reverse("rentals:order_detail", args=[self.order.order_code])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "bukti tidak dapat diubah lagi")

    # ---- akses berkas & nota ------------------------------------------
    def test_proof_file_access_control(self):
        self.do_upload(name="bukti.jpg", content=JPEG_BYTES)
        url = reverse("rentals:payment_proof", args=[self.order.order_code])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

        other = User.objects.create_user(
            username="spy_proof", email="spy_proof@example.com", password="Rahasia#123"
        )
        assign_role(other, ROLE_CUSTOMER)
        self.client.force_login(other)
        self.assertEqual(self.client.get(url).status_code, 403)

        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_order_page_shows_upload_form_and_wa_link(self):
        response = self.client.get(
            reverse("rentals:order_detail", args=[self.order.order_code])
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Unggah bukti transfer")
        self.assertContains(response, "Informasi Pembayaran")
        self.assertContains(response, "https://wa.me/6287812000155?text=")
        self.assertContains(response, self.order.order_code)

    def test_staff_table_shows_proof_badge(self):
        self.do_upload(name="bukti.jpg", content=JPEG_BYTES)
        self.client.force_login(self.cashier)
        response = self.client.get(reverse("rentals:staff_order_list"))
        self.assertContains(response, "Ada Struk")
        self.assertContains(
            response,
            reverse("rentals:payment_proof", args=[self.order.order_code]),
        )

    def test_filename_with_spaces_and_unicode_accepted(self):
        response = self.do_upload(name="bukti transfer café.jpg", content=JPEG_BYTES)
        self.assertEqual(response.status_code, 302)
        self.order.refresh_from_db()
        self.assertTrue(self.order.payment_proof.name.endswith(".jpg"))
        # nama asli tidak ikut tersimpan
        self.assertNotIn("caf", self.order.payment_proof.name)

    def test_path_traversal_filename_is_neutralized(self):
        """Django sudah membuang path; tetap pastikan simpanan tidak keluar folder."""
        import os

        for name in ("../../shell.jpg", "..\\..\\shell.jpg", "folder/bukti.jpg"):
            with self.subTest(name=name):
                self.order.payment_proof = None
                self.order.save(update_fields=["payment_proof"])
                response = self.do_upload(name=name, content=JPEG_BYTES)
                self.assertEqual(response.status_code, 302)
                self.order.refresh_from_db()
                stored = self.order.payment_proof.name
                self.assertTrue(stored.startswith("payment_proofs/"))
                self.assertNotIn("..", stored)
                self.assertTrue(
                    os.path.realpath(self.order.payment_proof.path).startswith(
                        os.path.realpath(self.media_root)
                    )
                )

    def test_csrf_token_required(self):
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.customer)
        response = csrf_client.post(
            self.upload_url(),
            {
                "payment_method": "TRANSFER_BCA",
                "payment_proof": SimpleUploadedFile("bukti.jpg", JPEG_BYTES),
            },
        )
        self.assertEqual(response.status_code, 403)
        self.order.refresh_from_db()
        self.assertFalse(self.order.has_payment_proof())
