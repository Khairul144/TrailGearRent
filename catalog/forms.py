"""Form manajemen Katalog, Kategori, dan Penyesuaian Stok untuk Admin TrailGear.

Keamanan:
- Gambar produk yang diunggah divalidasi dengan whitelist ekstensi (.jpg/.jpeg/.png/.webp),
  batas ukuran 5 MB, pemeriksaan magic bytes header, dan penamaan ulang UUID.
- Nama file statis (`image_filename`) dibatasi regex ketat agar bebas path traversal
  dan injeksi atribut CSS/HTML.
- Penyesuaian stok mewajibkan alasan/catatan (`notes`) untuk akuntabilitas audit trail.
"""

import re
import uuid

from django import forms
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.utils.text import slugify

from rentals.validators import (
    HEADER_SIZE,
    IMAGE_EXTENSIONS,
    MAGIC_LABEL,
    MAX_UPLOAD_BYTES,
    _matches_magic_bytes,
    validate_original_name,
)

from .models import Category, InventoryLog, Product

SAFE_STATIC_IMAGE_RE = re.compile(r"^[A-Za-z0-9_.-]+\.(jpg|jpeg|png|webp)$", re.IGNORECASE)


def validate_product_image(uploaded_file) -> str:
    """Validasi unggahan gambar produk (hanya gambar asli, bukan PDF/SVG/script)."""
    ext = validate_original_name(getattr(uploaded_file, "name", ""))
    if ext not in IMAGE_EXTENSIONS:
        raise ValidationError("Gambar produk harus berformat JPG, JPEG, PNG, atau WEBP.")

    size = int(getattr(uploaded_file, "size", 0) or 0)
    if size <= 0:
        raise ValidationError("Berkas gambar kosong tidak dapat diunggah.")
    if size > MAX_UPLOAD_BYTES:
        raise ValidationError("Ukuran gambar produk maksimal 5 MB.")

    try:
        uploaded_file.seek(0)
        header = uploaded_file.read(HEADER_SIZE)
    finally:
        uploaded_file.seek(0)

    if not isinstance(header, (bytes, bytearray)) or not _matches_magic_bytes(ext, bytes(header)):
        expected = MAGIC_LABEL.get(ext, "gambar")
        raise ValidationError(f"Isi berkas bukan {expected} yang valid.")

    return ext


def _unique_slug(model_cls, base_text: str, instance_pk=None, max_len: int = 170) -> str:
    base = slugify(base_text)[:max_len] or "item"
    candidate = base
    idx = 2
    qs = model_cls.objects.all()
    if instance_pk:
        qs = qs.exclude(pk=instance_pk)
    while qs.filter(slug=candidate).exists():
        suffix = f"-{idx}"
        candidate = f"{base[: max_len - len(suffix)]}{suffix}"
        idx += 1
    return candidate


class ProductForm(forms.ModelForm):
    slug = forms.SlugField(max_length=180, required=False)

    class Meta:
        model = Product
        fields = [
            "category",
            "name",
            "slug",
            "brand_name",
            "price_per_day",
            "price_type",
            "total_stock",
            "available_stock",
            "condition",
            "image",
            "image_filename",
            "description",
            "is_featured",
            "is_active",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["category"].queryset = Category.objects.order_by("order", "name")
        self.fields["brand_name"].required = False
        self.fields["image"].required = False
        self.fields["image_filename"].required = False
        self.fields["description"].required = False
        self.fields["is_featured"].required = False
        self.fields["is_active"].required = False

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if len(name) < 2:
            raise ValidationError("Nama barang minimal 2 karakter.")
        return name

    def clean_price_per_day(self):
        price = self.cleaned_data.get("price_per_day")
        if price is None or price <= 0:
            raise ValidationError("Harga sewa per hari harus lebih besar dari Rp 0.")
        if price > 100_000_000:
            raise ValidationError("Harga sewa per hari melebihi batas wajar (maks Rp 100.000.000).")
        return price

    def clean_total_stock(self):
        val = self.cleaned_data.get("total_stock")
        if val is None or val < 0 or val > 10_000:
            raise ValidationError("Total stok unit harus antara 0 sampai 10.000.")
        return val

    def clean_available_stock(self):
        val = self.cleaned_data.get("available_stock")
        if val is None or val < 0 or val > 10_000:
            raise ValidationError("Stok tersedia harus antara 0 sampai 10.000.")
        return val

    def clean_image_filename(self):
        fname = (self.cleaned_data.get("image_filename") or "").strip()
        if not fname:
            return ""
        if "/" in fname or "\\" in fname or ".." in fname:
            raise ValidationError("Nama file gambar statis tidak boleh mengandung path folder.")
        if not SAFE_STATIC_IMAGE_RE.fullmatch(fname):
            raise ValidationError(
                "Nama file statis hanya boleh huruf/angka/underscore/strip dan berekstensi .jpg/.jpeg/.png/.webp."
            )
        return fname

    def clean_image(self):
        img = self.cleaned_data.get("image")
        if isinstance(img, UploadedFile):
            ext = validate_product_image(img)
            img.name = f"{uuid.uuid4().hex}{ext}"
        return img

    def clean(self):
        cleaned = super().clean()
        total = cleaned.get("total_stock")
        avail = cleaned.get("available_stock")
        if total is not None and avail is not None and avail > total:
            self.add_error("available_stock", "Stok tersedia tidak boleh melebihi total stok unit.")

        name = cleaned.get("name") or ""
        raw_slug = (cleaned.get("slug") or "").strip()
        if raw_slug:
            slug_val = slugify(raw_slug)[:180]
            if not slug_val:
                self.add_error("slug", "Slug URL tidak valid.")
            else:
                qs = Product.objects.filter(slug=slug_val)
                if self.instance.pk:
                    qs = qs.exclude(pk=self.instance.pk)
                if qs.exists():
                    self.add_error("slug", "Slug URL sudah dipakai oleh produk lain.")
                cleaned["slug"] = slug_val
        elif name:
            cleaned["slug"] = _unique_slug(Product, name, instance_pk=self.instance.pk, max_len=170)

        return cleaned


class CategoryForm(forms.ModelForm):
    slug = forms.SlugField(max_length=120, required=False)

    class Meta:
        model = Category
        fields = ["name", "slug", "description", "order", "show_in_menu", "is_active"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["description"].required = False
        self.fields["order"].required = False
        self.fields["show_in_menu"].required = False
        self.fields["is_active"].required = False

    def clean_name(self):
        name = (self.cleaned_data.get("name") or "").strip()
        if len(name) < 2:
            raise ValidationError("Nama kategori minimal 2 karakter.")
        qs = Category.objects.filter(name__iexact=name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("Nama kategori sudah ada.")
        return name

    def clean_order(self):
        val = self.cleaned_data.get("order")
        if val is None:
            return 0
        if val < 0 or val > 9999:
            raise ValidationError("Urutan tampil harus antara 0 sampai 9999.")
        return val

    def clean(self):
        cleaned = super().clean()
        name = cleaned.get("name") or ""
        raw_slug = (cleaned.get("slug") or "").strip()
        if raw_slug:
            slug_val = slugify(raw_slug)[:120]
            if not slug_val:
                self.add_error("slug", "Slug kategori tidak valid.")
            else:
                qs = Category.objects.filter(slug=slug_val)
                if self.instance.pk:
                    qs = qs.exclude(pk=self.instance.pk)
                if qs.exists():
                    self.add_error("slug", "Slug kategori sudah digunakan.")
                cleaned["slug"] = slug_val
        elif name:
            cleaned["slug"] = _unique_slug(Category, name, instance_pk=self.instance.pk, max_len=110)
        return cleaned


class StockAdjustmentForm(forms.Form):
    ACTION_CHOICES = [
        (InventoryLog.Action.RESTOCK, "Restock / Tambah Unit Baru (+Stok Tersedia & Total)"),
        (InventoryLog.Action.DAMAGED, "Tandai Rusak / Servis (-Stok Tersedia)"),
        (InventoryLog.Action.ADJUSTMENT, "Stok Opname (Atur Stok Tersedia Langsung)"),
    ]

    action = forms.ChoiceField(choices=ACTION_CHOICES)
    quantity = forms.IntegerField(min_value=0, max_value=10_000)
    notes = forms.CharField(max_length=255, required=True)

    def clean_notes(self):
        notes = (self.cleaned_data.get("notes") or "").replace("\r", " ").replace("\n", " ").strip()
        if len(notes) < 3:
            raise ValidationError("Catatan / alasan perubahan stok minimal 3 karakter untuk audit.")
        return notes

    def clean(self):
        cleaned = super().clean()
        act = cleaned.get("action")
        qty = cleaned.get("quantity")
        if act in (InventoryLog.Action.RESTOCK, InventoryLog.Action.DAMAGED) and (qty is None or qty < 1):
            self.add_error("quantity", "Jumlah unit untuk Restock / Rusak minimal 1 unit.")
        return cleaned
