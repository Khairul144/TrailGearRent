"""Form Modul Keranjang & Pemesanan Sewa."""

import re
from datetime import date

from django import forms

from .models import RentalOrder
from .validators import validate_payment_proof

NIK_RE = re.compile(r"^\d{16}$")


class CheckoutForm(forms.ModelForm):
    """Form identitas penyewa saat checkout."""

    class Meta:
        model = RentalOrder
        fields = [
            "full_name",
            "phone_number",
            "id_card_type",
            "id_card_number",
            "pickup_plan_date",
            "return_plan_date",
            "payment_method",
            "notes",
        ]
        widgets = {
            "full_name": forms.TextInput(
                attrs={"placeholder": "Nama sesuai identitas", "autocomplete": "name"}
            ),
            "phone_number": forms.TextInput(
                attrs={"placeholder": "08xxxxxxxxxx", "inputmode": "tel"}
            ),
            "id_card_number": forms.TextInput(
                attrs={
                    "placeholder": "16 digit NIK KTP",
                    "inputmode": "numeric",
                    "maxlength": "16",
                    "pattern": r"\d{16}",
                    "autocomplete": "off",
                }
            ),
            "pickup_plan_date": forms.DateInput(attrs={"type": "date"}),
            "return_plan_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(
                attrs={"rows": 3, "placeholder": "Catatan tambahan (opsional)"}
            ),
        }

    def __init__(self, *args, cart=None, **kwargs):
        self.cart = cart
        super().__init__(*args, **kwargs)
        # Jaminan hanya KTP asli fisik; pilihan lain (SIM/KTM) dihapus.
        self.fields["id_card_type"].choices = [
            (RentalOrder.IdCardType.KTP.value, "KTP (Kartu Tanda Penduduk)")
        ]
        self.fields["id_card_type"].initial = RentalOrder.IdCardType.KTP
        self.fields["payment_method"].required = False
        if not self.is_bound:
            self.fields["payment_method"].initial = (
                RentalOrder.PaymentMethod.TRANSFER_BCA
            )

    def clean_payment_method(self):
        return (
            self.cleaned_data.get("payment_method")
            or RentalOrder.PaymentMethod.TRANSFER_BCA
        )

    def clean_full_name(self):
        name = (self.cleaned_data.get("full_name") or "").strip()
        if len(name) < 3:
            raise forms.ValidationError("Nama lengkap minimal 3 karakter.")
        return name

    def clean_phone_number(self):
        phone = (self.cleaned_data.get("phone_number") or "").strip()
        digits = "".join(ch for ch in phone if ch.isdigit())
        if not digits:
            raise forms.ValidationError("Nomor telepon wajib berisi angka.")
        if not 9 <= len(digits) <= 15:
            raise forms.ValidationError("Nomor telepon harus 9-15 digit.")
        allowed = set("0123456789+- ()")
        if any(ch not in allowed for ch in phone):
            raise forms.ValidationError("Nomor telepon mengandung karakter tidak valid.")
        return phone

    def clean_id_card_number(self):
        number = (self.cleaned_data.get("id_card_number") or "").strip()
        if not NIK_RE.match(number):
            raise forms.ValidationError(
                "Nomor identitas harus tepat 16 digit angka (NIK KTP), tanpa huruf atau spasi."
            )
        return number

    def clean_pickup_plan_date(self):
        pickup = self.cleaned_data.get("pickup_plan_date")
        if pickup and pickup < date.today():
            raise forms.ValidationError("Tanggal ambil tidak boleh di masa lalu.")
        return pickup

    def clean(self):
        cleaned = super().clean()
        pickup = cleaned.get("pickup_plan_date")
        ret = cleaned.get("return_plan_date")

        if pickup and ret:
            if ret <= pickup:
                self.add_error(
                    "return_plan_date",
                    "Tanggal kembali harus setelah tanggal ambil.",
                )

        if self.cart is not None and pickup and ret:
            items = list(self.cart.items.select_related("product"))
            if items:
                earliest_start = min(item.start_date for item in items)
                latest_return = max(item.return_date for item in items)
                if pickup > earliest_start:
                    self.add_error(
                        "pickup_plan_date",
                        "Tanggal ambil tidak boleh melewati jadwal item di "
                        f"keranjang ({earliest_start:%d-%m-%Y}).",
                    )
                if ret < latest_return:
                    self.add_error(
                        "return_plan_date",
                        "Tanggal kembali minimal "
                        f"{latest_return:%d-%m-%Y} sesuai durasi sewa.",
                    )
        return cleaned


class PaymentProofUploadForm(forms.ModelForm):
    """Form unggah bukti transfer dengan validasi berkas berlapis."""

    class Meta:
        model = RentalOrder
        fields = ["payment_method", "payment_proof"]
        widgets = {
            "payment_method": forms.Select(),
            "payment_proof": forms.FileInput(
                attrs={
                    "accept": ".jpg,.jpeg,.png,.webp,.pdf",
                    "class": "proof-input",
                }
            ),
        }
        labels = {
            "payment_method": "Metode Pembayaran",
            "payment_proof": "Berkas Bukti Transfer",
        }

    def clean_payment_proof(self):
        uploaded = self.cleaned_data.get("payment_proof")
        # Saat unggah ulang, field boleh kosong jika user hanya ganti metode.
        if uploaded is None or uploaded is False:
            return uploaded
        validate_payment_proof(uploaded)
        return uploaded

    def clean(self):
        cleaned = super().clean()
        method = cleaned.get("payment_method")
        proof = cleaned.get("payment_proof")
        if method != RentalOrder.PaymentMethod.CASH and proof is None and not self.instance.has_payment_proof():
            self.add_error(
                "payment_proof",
                "Bukti transfer wajib diunggah untuk pembayaran non-tunai.",
            )
        return cleaned


class ReturnInspectionForm(forms.Form):
    """Form pemeriksaan fisik & serah terima pengembalian alat.

    Field per item dibuat dinamis di __init__ (condition_<id>, damage_<id>)
    karena jumlah item berbeda tiap pesanan.
    """

    actual_return_date = forms.DateField(
        label="Tanggal Riil Pengembalian",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    return_notes = forms.CharField(
        label="Catatan Kondisi & Serah Terima",
        required=False,
        widget=forms.Textarea(
            attrs={"rows": 3, "placeholder": "Contoh: tenda kotor, KTP asli sudah diserahkan"}
        ),
    )
    fine_payment_method = forms.ChoiceField(
        label="Metode Bayar Denda",
        choices=[("CASH", "Tunai di Kasir"), ("QRIS", "QRIS Kasir")],
        initial="CASH",
        required=False,
    )
    confirmed = forms.BooleanField(
        label=(
            "Saya telah memeriksa kondisi fisik barang dan menyerahkan kembali "
            "KTP asli fisik kepada pelanggan."
        ),
        required=True,
    )

    def __init__(self, *args, order, **kwargs):
        self.order = order
        super().__init__(*args, **kwargs)
        for item in order.items.select_related("product"):
            self.fields[f"condition_{item.pk}"] = forms.ChoiceField(
                label=item.product.name,
                choices=item.Condition.choices,
                initial=item.Condition.BAIK,
                required=True,
            )
            self.fields[f"damage_{item.pk}"] = forms.IntegerField(
                label=f"Biaya kerusakan {item.product.name}",
                min_value=0,
                initial=0,
                required=False,
            )

    def clean_actual_return_date(self):
        value = self.cleaned_data.get("actual_return_date")
        if value and value < self.order.pickup_plan_date:
            raise forms.ValidationError(
                "Tanggal pengembalian tidak boleh sebelum tanggal pengambilan."
            )
        if value and value > date.today():
            raise forms.ValidationError(
                "Tanggal pengembalian tidak boleh melebihi hari ini."
            )
        return value

    def clean_confirmed(self):
        value = self.cleaned_data.get("confirmed")
        if not value:
            raise forms.ValidationError(
                "Centang pernyataan pemeriksaan fisik sebelum menyelesaikan."
            )
        return value

    def item_conditions(self) -> dict:
        """Kumpulkan kondisi & biaya per item untuk services.complete_return."""
        data = {}
        for item in self.order.items.select_related("product"):
            data[item.pk] = {
                "condition": self.cleaned_data.get(f"condition_{item.pk}")
                or item.Condition.BAIK,
                "damage_fee": self.cleaned_data.get(f"damage_{item.pk}") or 0,
            }
        return data
