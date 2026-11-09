"""
Model database untuk Modul Keranjang & Pemesanan Sewa (rentals).

Alur bisnis:
    Cart / CartItem  -> keranjang sementara (session atau user)
    RentalOrder      -> pesanan sewa setelah checkout
    RentalOrderItem  -> salinan harga & deposit saat checkout

Mutasi stok inventaris dilakukan lewat RentalOrder (lihat services.py) dan
dicatat di catalog.InventoryLog supaya audit stok tetap lengkap.
"""

import secrets

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from .validators import payment_proof_upload_path


def rupiah(value) -> str:
    """Format angka menjadi Rupiah dengan pemisah titik (Rp 25.000)."""
    return "Rp " + f"{int(value or 0):,}".replace(",", ".")


def generate_order_code(prefix: str = "TG") -> str:
    """Kode booking unik: TG-YYYYMMDD-XXXX (huruf/angka tanpa karakter ambigu)."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    suffix = "".join(secrets.choice(alphabet) for _ in range(4))
    return f"{prefix}-{timezone.localdate():%Y%m%d}-{suffix}"


class Cart(models.Model):
    """Keranjang sewa.

    Satu keranjang milik user (bila login) atau milik session (bila belum
    login). Keranjang session diadopsi ke keranjang user saat login.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="carts",
        verbose_name="Pemilik (User)",
    )
    session_key = models.CharField(
        max_length=64,
        blank=True,
        default="",
        db_index=True,
        verbose_name="Session Key",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "rentals_cart"
        ordering = ["-updated_at"]
        verbose_name = "Keranjang"
        verbose_name_plural = "Keranjang"
        constraints = [
            models.UniqueConstraint(
                fields=["user"],
                condition=Q(user__isnull=False),
                name="uniq_cart_per_user",
            ),
            models.UniqueConstraint(
                fields=["session_key"],
                condition=Q(user__isnull=True),
                name="uniq_cart_per_session",
            ),
        ]

    def __str__(self):
        owner = self.user.username if self.user_id else f"session:{self.session_key[:8]}"
        return f"Cart #{self.pk} ({owner})"

    # ---- Ringkasan -----------------------------------------------------
    @property
    def total_quantity(self) -> int:
        return sum(item.quantity for item in self.items.all())

    @property
    def distinct_items_count(self) -> int:
        return self.items.count()

    @property
    def total_rental_fee(self) -> int:
        return sum(item.rental_price_total for item in self.items.all())

    @property
    def grand_total(self) -> int:
        """Total bayar = biaya sewa saja (tanpa deposit; jaminan = KTP asli)."""
        return self.total_rental_fee

    @property
    def formatted_total_rental_fee(self) -> str:
        return rupiah(self.total_rental_fee)

    @property
    def formatted_grand_total(self) -> str:
        return rupiah(self.grand_total)


class CartItem(models.Model):
    """Satu baris barang di keranjang sewa."""

    cart = models.ForeignKey(
        Cart,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Keranjang",
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.CASCADE,
        related_name="cart_items",
        verbose_name="Peralatan",
    )
    start_date = models.DateField(verbose_name="Tanggal Ambil")
    duration_days = models.PositiveIntegerField(
        default=1,
        verbose_name="Durasi Sewa (hari)",
    )
    quantity = models.PositiveIntegerField(default=1, verbose_name="Jumlah Unit")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "rentals_cart_item"
        ordering = ["created_at"]
        verbose_name = "Item Keranjang"
        verbose_name_plural = "Item Keranjang"
        constraints = [
            models.UniqueConstraint(
                fields=["cart", "product", "start_date", "duration_days"],
                name="uniq_cart_item_slot",
            ),
        ]

    def __str__(self):
        return f"{self.product.name} x{self.quantity} ({self.duration_days} hari)"

    def clean(self):
        super().clean()
        if self.duration_days is not None and self.duration_days < 1:
            raise ValidationError({"duration_days": "Durasi sewa minimal 1 hari."})
        if self.quantity is not None and self.quantity < 1:
            raise ValidationError({"quantity": "Jumlah unit minimal 1."})
        if self.product_id and self.quantity and self.quantity > self.product.available_stock:
            raise ValidationError(
                {
                    "quantity": (
                        f"Jumlah melebihi stok tersedia "
                        f"({self.product.available_stock} unit)."
                    )
                }
            )

    # ---- Kalkulasi -----------------------------------------------------
    @property
    def return_date(self):
        """Tanggal pengembalian: H + durasi + 1."""
        from datetime import timedelta

        return self.start_date + timedelta(days=self.duration_days + 1)

    @property
    def rental_price_total(self) -> int:
        return self.product.price_per_day * self.duration_days * self.quantity

    @property
    def subtotal(self) -> int:
        """Subtotal = biaya sewa saja."""
        return self.rental_price_total

    @property
    def formatted_rental_price_total(self) -> str:
        return rupiah(self.rental_price_total)

    @property
    def formatted_subtotal(self) -> str:
        return rupiah(self.subtotal)


class RentalOrder(models.Model):
    """Pesanan sewa (booking) yang dibuat setelah checkout."""

    class Status(models.TextChoices):
        MENUNGGU_PEMBAYARAN = "MENUNGGU_PEMBAYARAN", "Menunggu Pembayaran"
        DIKONFIRMASI = "DIKONFIRMASI", "Dikonfirmasi"
        DIAMBIL = "DIAMBIL", "Berjalan (Diambil)"
        KEMBALI = "KEMBALI", "Selesai (Dikembalikan)"
        DIBATALKAN = "DIBATALKAN", "Dibatalkan"

    class IdCardType(models.TextChoices):
        KTP = "KTP", "KTP (Kartu Tanda Penduduk)"

    class PaymentMethod(models.TextChoices):
        TRANSFER_BCA = "TRANSFER_BCA", "Transfer Bank BCA"
        TRANSFER_MANDIRI = "TRANSFER_MANDIRI", "Transfer Bank Mandiri"
        TRANSFER_BNI = "TRANSFER_BNI", "Transfer Bank BNI"
        QRIS = "QRIS", "QRIS TrailGear"
        CASH = "CASH", "Tunai di Toko (COD)"

    order_code = models.CharField(
        max_length=32,
        unique=True,
        editable=False,
        verbose_name="Kode Booking",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="rental_orders",
        verbose_name="Penyewa",
    )
    full_name = models.CharField(max_length=150, verbose_name="Nama Lengkap")
    phone_number = models.CharField(max_length=30, verbose_name="No. Telepon / WhatsApp")
    id_card_number = models.CharField(max_length=50, verbose_name="Nomor Identitas")
    id_card_type = models.CharField(
        max_length=10,
        choices=IdCardType.choices,
        default=IdCardType.KTP,
        verbose_name="Jenis Identitas",
    )
    pickup_plan_date = models.DateField(verbose_name="Rencana Tanggal Ambil")
    return_plan_date = models.DateField(verbose_name="Rencana Tanggal Kembali")
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.MENUNGGU_PEMBAYARAN,
        db_index=True,
        verbose_name="Status Pesanan",
    )
    total_rental_fee = models.PositiveIntegerField(
        default=0, verbose_name="Total Biaya Sewa (Rp)"
    )
    grand_total = models.PositiveIntegerField(default=0, verbose_name="Grand Total (Rp)")
    notes = models.TextField(blank=True, default="", verbose_name="Catatan Pelanggan")
    payment_method = models.CharField(
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
        verbose_name="Metode Pembayaran",
    )
    payment_proof = models.FileField(
        upload_to=payment_proof_upload_path,
        blank=True,
        null=True,
        verbose_name="Bukti Pembayaran",
    )
    payment_proof_uploaded_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="Waktu Unggah Bukti",
    )
    stock_deducted = models.BooleanField(
        default=False,
        verbose_name="Stok Sudah Dikurangi",
        help_text="Penanda internal agar mutasi stok tidak dihitung dua kali.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "rentals_rental_order"
        ordering = ["-created_at"]
        verbose_name = "Pesanan Sewa"
        verbose_name_plural = "Pesanan Sewa"
        indexes = [
            models.Index(fields=["status", "-created_at"], name="idx_order_status"),
            models.Index(fields=["user", "-created_at"], name="idx_order_user"),
        ]

    def __str__(self):
        return f"{self.order_code} — {self.full_name}"

    def save(self, *args, **kwargs):
        if not self.order_code:
            code = generate_order_code()
            for _ in range(11):
                if not RentalOrder.objects.filter(order_code=code).exists():
                    break
                code = generate_order_code()
            self.order_code = code
        super().save(*args, **kwargs)

    # ---- Status helpers ------------------------------------------------
    @property
    def is_active(self) -> bool:
        return self.status in {self.Status.DIKONFIRMASI, self.Status.DIAMBIL}

    @property
    def is_finished(self) -> bool:
        return self.status in {self.Status.KEMBALI, self.Status.DIBATALKAN}

    @property
    def can_confirm(self) -> bool:
        return self.status == self.Status.MENUNGGU_PEMBAYARAN

    @property
    def can_pickup(self) -> bool:
        return self.status == self.Status.DIKONFIRMASI

    @property
    def can_return(self) -> bool:
        return self.status == self.Status.DIAMBIL

    @property
    def can_cancel(self) -> bool:
        return self.status in {
            self.Status.MENUNGGU_PEMBAYARAN,
            self.Status.DIKONFIRMASI,
        }

    # ---- Bukti pembayaran ---------------------------------------------
    def has_payment_proof(self) -> bool:
        return bool(self.payment_proof)

    def can_upload_payment_proof(self) -> bool:
        return self.status == self.Status.MENUNGGU_PEMBAYARAN

    @property
    def payment_proof_ext(self) -> str:
        import os

        return os.path.splitext(self.payment_proof.name or "")[1].lower()

    @property
    def payment_proof_is_image(self) -> bool:
        return self.payment_proof_ext in {".jpg", ".jpeg", ".png", ".webp"}

    @property
    def formatted_payment_method(self) -> str:
        return self.get_payment_method_display()

    @property
    def status_value(self) -> str:
        """Label status dalam bentuk lowercase untuk CSS/JS."""
        return self.status.lower()

    @property
    def badge_class(self) -> str:
        """Class CSS badge untuk status pesanan."""
        return {
            self.Status.MENUNGGU_PEMBAYARAN: "pending",
            self.Status.DIKONFIRMASI: "paid",
            self.Status.DIAMBIL: "active",
            self.Status.KEMBALI: "returned",
            self.Status.DIBATALKAN: "cancelled",
        }.get(self.status, "pending")

    @property
    def items_summary(self) -> str:
        """Ringkasan nama barang, contoh: 'Tenda 4P, Carrier 60L'."""
        names = [item.product.name for item in self.items.all()]
        if not names:
            return "—"
        if len(names) <= 2:
            return ", ".join(names)
        return f"{names[0]}, {names[1]} +{len(names) - 2} lainnya"

    @property
    def total_units(self) -> int:
        return sum(item.quantity for item in self.items.all())

    @property
    def duration_days(self) -> int:
        """Durasi sewa (hari) berdasarkan rencana ambil & kembali."""
        if self.pickup_plan_date and self.return_plan_date:
            return (self.return_plan_date - self.pickup_plan_date).days
        return 0

    # ---- Format --------------------------------------------------------
    @property
    def formatted_total_rental_fee(self) -> str:
        return rupiah(self.total_rental_fee)

    @property
    def formatted_grand_total(self) -> str:
        return rupiah(self.grand_total)

    def get_absolute_url(self):
        return reverse("rentals:order_detail", kwargs={"order_code": self.order_code})

    def recalculate_totals(self, save: bool = True):
        """Hitung ulang total dari item yang tersimpan (tanpa deposit)."""
        rental = sum(item.rental_price_total for item in self.items.all())
        self.total_rental_fee = rental
        self.grand_total = rental
        if save:
            self.save(
                update_fields=[
                    "total_rental_fee",
                    "grand_total",
                    "updated_at",
                ]
            )
        return self


class RentalOrderItem(models.Model):
    """Baris barang pada pesanan sewa (harga dibekukan saat checkout)."""

    order = models.ForeignKey(
        RentalOrder,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Pesanan",
    )
    product = models.ForeignKey(
        "catalog.Product",
        on_delete=models.PROTECT,
        related_name="order_items",
        verbose_name="Peralatan",
    )
    unit_price = models.PositiveIntegerField(verbose_name="Harga Sewa / Hari (Rp)")
    quantity = models.PositiveIntegerField(default=1, verbose_name="Jumlah Unit")
    duration_days = models.PositiveIntegerField(default=1, verbose_name="Durasi (hari)")
    subtotal = models.PositiveIntegerField(
        default=0, verbose_name="Subtotal Biaya Sewa (Rp)"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "rentals_rental_order_item"
        ordering = ["id"]
        verbose_name = "Item Pesanan Sewa"
        verbose_name_plural = "Item Pesanan Sewa"

    def __str__(self):
        return f"{self.order.order_code} — {self.product.name} x{self.quantity}"

    def save(self, *args, **kwargs):
        self.subtotal = self.unit_price * self.duration_days * self.quantity
        super().save(*args, **kwargs)

    @property
    def rental_price_total(self) -> int:
        return self.unit_price * self.duration_days * self.quantity

    @property
    def formatted_subtotal(self) -> str:
        return rupiah(self.subtotal)
