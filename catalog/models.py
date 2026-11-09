"""
Model database untuk Modul Katalog & Inventaris Alat (catalog).

Menyimpan kategori peralatan outdoor, data produk/alat sewa beserta stok
inventaris (total & tersedia), serta catatan mutasi stok (InventoryLog).
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.text import slugify


class Category(models.Model):
    """Kategori peralatan outdoor (contoh: Carrier 50L - 100L, Tenda 4 Orang)."""

    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Nama Kategori",
    )
    slug = models.SlugField(
        max_length=120,
        unique=True,
        verbose_name="Slug URL",
    )
    description = models.TextField(
        blank=True,
        default="",
        verbose_name="Deskripsi",
    )
    icon_class = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="Ikon / Class CSS",
    )
    order = models.PositiveIntegerField(
        default=0,
        verbose_name="Urutan Tampil",
    )
    show_in_menu = models.BooleanField(
        default=True,
        verbose_name="Tampilkan di Menu Navbar",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Status Aktif",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "catalog_category"
        ordering = ["order", "name"]
        verbose_name = "Kategori Alat"
        verbose_name_plural = "Kategori Alat"

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class Product(models.Model):
    """Item peralatan outdoor yang disewakan di TrailGear."""

    class PriceType(models.TextChoices):
        FLAT = "FLAT", "Harga Flat Harian"
        VARIANT = "VARIANT", "Harga Varian"

    class Condition(models.TextChoices):
        EXCELLENT = "SANGAT_BAIK", "Sangat Baik"
        GOOD = "BAIK", "Baik"
        MAINTENANCE = "PERLU_SERVIS", "Perlu Servis"

    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
        verbose_name="Kategori",
    )
    name = models.CharField(
        max_length=180,
        verbose_name="Nama Peralatan",
    )
    slug = models.SlugField(
        max_length=180,
        unique=True,
        verbose_name="Slug URL",
    )
    description = models.TextField(
        blank=True,
        default="",
        verbose_name="Deskripsi & Spesifikasi",
    )
    brand_name = models.CharField(
        max_length=100,
        blank=True,
        default="",
        verbose_name="Merek / Brand",
    )
    price_per_day = models.PositiveIntegerField(
        verbose_name="Harga Sewa per Hari (Rp)",
        help_text="Harga sewa per hari dalam Rupiah (contoh: 25000).",
    )
    price_type = models.CharField(
        max_length=20,
        choices=PriceType.choices,
        default=PriceType.FLAT,
        verbose_name="Tipe Harga",
    )
    total_stock = models.PositiveIntegerField(
        default=1,
        verbose_name="Total Stok Unit",
        help_text="Jumlah total unit fisik yang dimiliki toko.",
    )
    available_stock = models.PositiveIntegerField(
        default=1,
        verbose_name="Stok Tersedia",
        help_text="Jumlah unit yang siap disewa saat ini.",
    )
    image = models.FileField(
        upload_to="products/",
        blank=True,
        null=True,
        verbose_name="File Gambar Unggahan",
    )
    image_filename = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Nama File Gambar Statis",
        help_text="Nama file di static/assets/img/product/ (contoh: products_xxx.jpg).",
    )
    condition = models.CharField(
        max_length=20,
        choices=Condition.choices,
        default=Condition.EXCELLENT,
        verbose_name="Kondisi Fisik",
    )
    is_featured = models.BooleanField(
        default=False,
        verbose_name="Produk Unggulan (Beranda)",
        help_text="Tampilkan pada bagian Pilihan Terbaik Minggu Ini di halaman utama.",
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name="Status Aktif",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "catalog_product"
        ordering = ["category__order", "name"]
        verbose_name = "Peralatan / Produk"
        verbose_name_plural = "Peralatan / Produk"
        indexes = [
            models.Index(fields=["slug"], name="idx_product_slug"),
            models.Index(fields=["category", "is_active"], name="idx_product_cat_active"),
            models.Index(fields=["is_featured", "is_active"], name="idx_product_featured"),
        ]

    def clean(self):
        super().clean()
        if self.available_stock > self.total_stock:
            raise ValidationError(
                {"available_stock": "Stok tersedia tidak boleh melebihi total stok unit."}
            )
        if self.price_per_day is not None and self.price_per_day <= 0:
            raise ValidationError(
                {"price_per_day": "Harga sewa per hari harus lebih besar dari Rp 0."}
            )

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.name)
        super().save(*args, **kwargs)

    def get_image_url(self) -> str:
        """Kembalikan URL gambar produk (unggah atau static asset)."""
        if self.image:
            try:
                return self.image.url
            except ValueError:
                pass
        if self.image_filename:
            return f"/static/assets/img/product/{self.image_filename}"
        return "/static/assets/img/logo/trailgear_logo.png"

    @property
    def formatted_price(self) -> str:
        """Format harga Rupiah dengan pemisah titik (contoh: Rp 25.000)."""
        formatted = f"{int(self.price_per_day):,}".replace(",", ".")
        return f"Rp {formatted}"

    @property
    def in_stock(self) -> bool:
        """True jika produk aktif dan stok tersedia > 0."""
        return bool(self.is_active and self.available_stock > 0)

    def __str__(self):
        return f"{self.name} ({self.formatted_price})"


class InventoryLog(models.Model):
    """Catatan riwayat perubahan stok alat untuk keperluan audit inventaris."""

    class Action(models.TextChoices):
        INITIAL_SEED = "INITIAL_SEED", "Stok Awal (Seeding)"
        RESTOCK = "RESTOCK", "Penambahan Unit Baru"
        RENTED = "RENTED", "Disewa Pelanggan"
        RETURNED = "RETURNED", "Dikembalikan Pelanggan"
        DAMAGED = "DAMAGED", "Unit Rusak / Servis"
        ADJUSTMENT = "ADJUSTMENT", "Penyesuaian Stok Opname"

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="inventory_logs",
        verbose_name="Peralatan",
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="inventory_logs",
        verbose_name="Diubah Oleh",
    )
    action = models.CharField(
        max_length=30,
        choices=Action.choices,
        default=Action.ADJUSTMENT,
        verbose_name="Jenis Aksi",
    )
    quantity_change = models.IntegerField(
        verbose_name="Perubahan Jumlah (+/-)",
    )
    stock_before = models.PositiveIntegerField(
        verbose_name="Stok Tersedia Sebelumnya",
    )
    stock_after = models.PositiveIntegerField(
        verbose_name="Stok Tersedia Sesudahnya",
    )
    notes = models.CharField(
        max_length=255,
        blank=True,
        default="",
        verbose_name="Catatan",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "catalog_inventory_log"
        ordering = ["-created_at"]
        verbose_name = "Log Inventaris"
        verbose_name_plural = "Log Inventaris"

    def __str__(self):
        sign = "+" if self.quantity_change >= 0 else ""
        return f"{self.product.name}: {sign}{self.quantity_change} ({self.action})"
