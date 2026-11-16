"""
Layanan domain Modul Keranjang & Pemesanan Sewa.

Semua aturan bisnis yang menyentuh stok (mutasi inventaris) berada di sini
supaya view tetap tipis dan konsisten:
- resolusi keranjang (user / session, termasuk adopsi keranjang session)
- penambahan & pembaruan item keranjang dengan validasi stok
- checkout: pembuatan RentalOrder dari Cart
- transisi status pesanan + mutasi catalog.InventoryLog

Tidak ada dependency eksternal: murni Django ORM + transaksi database.
"""

from datetime import date

from django.db import transaction

from catalog.models import InventoryLog, Product

from .constants import LATE_FEE_PER_DAY
from .models import Cart, CartItem, RentalOrder, RentalOrderItem

MIN_DURATION = 1
MAX_DURATION = 30


class CartError(Exception):
    """Kesalahan aturan bisnis keranjang (pesan siap tampil ke pengguna)."""


class StockError(CartError):
    """Stok tidak mencukupi untuk aksi yang diminta."""


class OrderTransitionError(Exception):
    """Perubahan status pesanan tidak diizinkan."""


class MakerCheckerViolationError(OrderTransitionError):
    """Pelanggaran pemisahan tugas (Separation of Duties / Maker-Checker).

    Pembuat transaksi (Maker) tidak diizinkan menjadi pihak yang menyetujui
    atau memverifikasi (Checker) transaksinya sendiri.
    """


class ReturnValidationError(Exception):
    """Data pemeriksaan pengembalian tidak valid (pesan siap tampil)."""


# ---------------------------------------------------------------------------
# Keranjang
# ---------------------------------------------------------------------------
def _ensure_session_key(request) -> str:
    if not request.session.session_key:
        request.session.create()
    return request.session.session_key


def _merge_cart(source: Cart, target: Cart):
    """Pindahkan item source ke target lalu hapus source."""
    for item in source.items.select_related("product"):
        existing = target.items.filter(
            product=item.product,
            start_date=item.start_date,
            duration_days=item.duration_days,
        ).first()
        if existing:
            existing.quantity = min(
                existing.quantity + item.quantity,
                max(existing.product.available_stock, 1),
            )
            existing.save(update_fields=["quantity", "updated_at"])
            item.delete()
        else:
            item.cart = target
            item.save(update_fields=["cart", "updated_at"])
    source.delete()


def _session_cart(request, create: bool = True):
    """Keranjang milik session ini.

    Kunci utama adalah id keranjang di session (`cart_id`) karena session key
    Django berputar (cycle_key) saat login. Session key disimpan sebagai
    cadangan untuk data lama.
    """
    cart_id = request.session.get("cart_id")
    cart = None
    if cart_id:
        cart = Cart.objects.filter(pk=cart_id, user__isnull=True).first()
    if cart is None and request.session.session_key:
        cart = Cart.objects.filter(
            user__isnull=True, session_key=request.session.session_key
        ).first()
    if cart is None:
        if not create:
            return None
        session_key = _ensure_session_key(request)
        cart = Cart.objects.create(session_key=session_key)
    request.session["cart_id"] = cart.pk
    return cart


def get_cart(request, create: bool = True):
    """Keranjang aktif untuk request saat ini (None bila create=False & kosong)."""
    if request.user.is_authenticated:
        cart = Cart.objects.filter(user=request.user).first()
        session_cart = _session_cart(request, create=False)
        if session_cart is not None:
            if cart is None:
                session_cart.user = request.user
                session_cart.session_key = ""
                session_cart.save(
                    update_fields=["user", "session_key", "updated_at"]
                )
                cart = session_cart
                request.session.pop("cart_id", None)
            else:
                _merge_cart(session_cart, cart)
                request.session.pop("cart_id", None)
        if cart is None and create:
            cart = Cart.objects.create(user=request.user)
        return cart

    return _session_cart(request, create=create)


def add_item_to_cart(cart: Cart, product: Product, *, start_date, duration_days, quantity) -> CartItem:
    """Tambah item ke keranjang; gabungkan bila slot (produk+tgl+durasi) sama."""
    if not product.is_active:
        raise CartError("Peralatan ini sedang tidak tersedia untuk disewa.")

    if start_date is None:
        raise CartError("Tanggal pengambilan wajib diisi.")
    if start_date < date.today():
        raise CartError("Tanggal pengambilan tidak boleh di masa lalu.")

    try:
        duration_days = int(duration_days)
        quantity = int(quantity)
    except (TypeError, ValueError):
        raise CartError("Durasi dan jumlah harus berupa angka.")

    if duration_days < MIN_DURATION:
        raise CartError("Durasi sewa minimal 1 hari.")
    if duration_days > MAX_DURATION:
        raise CartError(f"Durasi sewa maksimal {MAX_DURATION} hari.")
    if quantity < 1:
        raise CartError("Jumlah unit minimal 1.")

    if product.available_stock <= 0:
        raise StockError("Stok peralatan ini sedang habis.")
    if quantity > product.available_stock:
        raise StockError(
            f"Jumlah melebihi stok tersedia ({product.available_stock} unit)."
        )

    with transaction.atomic():
        item, created = CartItem.objects.select_for_update().get_or_create(
            cart=cart,
            product=product,
            start_date=start_date,
            duration_days=duration_days,
            defaults={"quantity": quantity},
        )
        if not created:
            new_quantity = item.quantity + quantity
            if new_quantity > product.available_stock:
                raise StockError(
                    "Total di keranjang melebihi stok tersedia "
                    f"({product.available_stock} unit). Hapus item lain dulu."
                )
            item.quantity = new_quantity
            item.save(update_fields=["quantity", "updated_at"])
        cart.save(update_fields=["updated_at"])
    return item


def update_item_quantity(item: CartItem, quantity: int) -> CartItem:
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        raise CartError("Jumlah harus berupa angka.")
    if quantity < 1:
        raise CartError("Jumlah unit minimal 1.")
    if quantity > item.product.available_stock:
        raise StockError(
            f"Jumlah melebihi stok tersedia ({item.product.available_stock} unit)."
        )
    item.quantity = quantity
    item.save(update_fields=["quantity", "updated_at"])
    item.cart.save(update_fields=["updated_at"])
    return item


def update_cart_schedule(cart: Cart, start_date, duration_days) -> Cart:
    """Samakan tanggal ambil & durasi untuk SEMUA item keranjang.

    Dipakai kontrol header keranjang. Duplikat produk digabung lebih dulu
    supaya unique constraint (cart, product, start_date, duration) tidak
    bentrok saat semua baris diubah ke slot yang sama.
    """
    if start_date is None:
        raise CartError("Tanggal ambil wajib diisi.")
    if start_date < date.today():
        raise CartError("Tanggal ambil tidak boleh di masa lalu.")
    try:
        duration_days = int(duration_days)
    except (TypeError, ValueError):
        raise CartError("Durasi harus berupa angka.")
    if duration_days < MIN_DURATION:
        raise CartError("Durasi sewa minimal 1 hari.")
    if duration_days > MAX_DURATION:
        raise CartError(f"Durasi sewa maksimal {MAX_DURATION} hari.")

    with transaction.atomic():
        items = list(cart.items.select_related("product"))
        if not items:
            raise CartError("Keranjang masih kosong.")

        totals = {}
        for item in items:
            totals[item.product_id] = totals.get(item.product_id, 0) + item.quantity
        for item in items:
            if totals[item.product_id] > item.product.available_stock:
                raise StockError(
                    f"Stok {item.product.name} hanya "
                    f"{item.product.available_stock} unit, sedangkan di keranjang "
                    f"{totals[item.product_id]} unit."
                )

        merged = {}
        for item in items:
            if item.product_id in merged:
                keeper = merged[item.product_id]
                keeper.quantity += item.quantity
                keeper.save(update_fields=["quantity", "updated_at"])
                item.delete()
            else:
                merged[item.product_id] = item

        for item in merged.values():
            item.start_date = start_date
            item.duration_days = duration_days
            item.save(update_fields=["start_date", "duration_days", "updated_at"])

        cart.save(update_fields=["updated_at"])
    return cart


def cart_is_valid(cart: Cart):
    """Validasi ulang isi keranjang terhadap stok terkini.

    Mengembalikan list pesan masalah (kosong = keranjang siap checkout).
    """
    problems = []
    items = cart.items.select_related("product")
    if not items:
        problems.append("Keranjang masih kosong.")
        return problems
    totals = {}
    for item in items:
        totals[item.product_id] = totals.get(item.product_id, 0) + item.quantity
    for item in items:
        product = item.product
        if not product.is_active:
            problems.append(f"{product.name} sudah tidak aktif.")
        elif totals[item.product_id] > product.available_stock:
            problems.append(
                f"Stok {product.name} hanya {product.available_stock} unit, "
                f"sedangkan di keranjang {totals[item.product_id]} unit."
            )
    return problems


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------
def create_order_from_cart(cart: Cart, user, data: dict) -> RentalOrder:
    """Ubah Cart menjadi RentalOrder. Cart dikosongkan bila berhasil."""
    problems = cart_is_valid(cart)
    if problems:
        raise StockError(" ".join(problems))

    items = list(cart.items.select_related("product"))
    if not items:
        raise CartError("Keranjang masih kosong.")

    first_start = min(item.start_date for item in items)
    last_return = max(item.return_date for item in items)

    with transaction.atomic():
        order = RentalOrder.objects.create(
            user=user,
            full_name=data["full_name"],
            phone_number=data["phone_number"],
            id_card_number=data["id_card_number"],
            id_card_type=data["id_card_type"],
            pickup_plan_date=data.get("pickup_plan_date") or first_start,
            return_plan_date=data.get("return_plan_date") or last_return,
            payment_method=data.get("payment_method")
            or RentalOrder.PaymentMethod.TRANSFER_BCA,
            notes=data.get("notes", "").strip(),
            status=RentalOrder.Status.MENUNGGU_PEMBAYARAN,
        )
        rental_total = 0
        for item in items:
            order_item = RentalOrderItem.objects.create(
                order=order,
                product=item.product,
                unit_price=item.product.price_per_day,
                quantity=item.quantity,
                duration_days=item.duration_days,
            )
            rental_total += order_item.subtotal

        order.total_rental_fee = rental_total
        order.grand_total = rental_total
        order.save(
            update_fields=[
                "total_rental_fee",
                "grand_total",
                "updated_at",
            ]
        )
        cart.items.all().delete()

    return order


# ---------------------------------------------------------------------------
# Transisi status & mutasi stok
# ---------------------------------------------------------------------------
STATUS_TRANSITIONS = {
    RentalOrder.Status.MENUNGGU_PEMBAYARAN: {
        RentalOrder.Status.DIKONFIRMASI,
        RentalOrder.Status.DIBATALKAN,
    },
    RentalOrder.Status.DIKONFIRMASI: {
        RentalOrder.Status.DIAMBIL,
        RentalOrder.Status.DIBATALKAN,
    },
    RentalOrder.Status.DIAMBIL: {RentalOrder.Status.KEMBALI},
    RentalOrder.Status.KEMBALI: set(),
    RentalOrder.Status.DIBATALKAN: set(),
}

# Aksi cepat dashboard -> status tujuan.
ACTION_STATUS_MAP = {
    "confirm": RentalOrder.Status.DIKONFIRMASI,
    "pickup": RentalOrder.Status.DIAMBIL,
    "return": RentalOrder.Status.KEMBALI,
    "cancel": RentalOrder.Status.DIBATALKAN,
}

STOCK_OUT_STATUSES = {RentalOrder.Status.DIKONFIRMASI, RentalOrder.Status.DIAMBIL}
STOCK_IN_STATUSES = {RentalOrder.Status.KEMBALI, RentalOrder.Status.DIBATALKAN}


def _deduct_stock(order: RentalOrder, actor=None):
    for item in order.items.select_related("product"):
        product = Product.objects.select_for_update().get(pk=item.product_id)
        if product.available_stock < item.quantity:
            raise StockError(
                f"Stok {product.name} tidak cukup "
                f"(tersedia {product.available_stock}, dibutuhkan {item.quantity})."
            )
        before = product.available_stock
        product.available_stock = before - item.quantity
        product.save(update_fields=["available_stock", "updated_at"])
        InventoryLog.objects.create(
            product=product,
            changed_by=actor if getattr(actor, "is_authenticated", False) else None,
            action=InventoryLog.Action.RENTED,
            quantity_change=-item.quantity,
            stock_before=before,
            stock_after=product.available_stock,
            notes=f"Order {order.order_code}",
        )


def _restore_stock(order: RentalOrder, actor=None):
    for item in order.items.select_related("product"):
        product = Product.objects.select_for_update().get(pk=item.product_id)
        before = product.available_stock
        after = min(before + item.quantity, max(product.total_stock, before))
        product.available_stock = after
        product.save(update_fields=["available_stock", "updated_at"])
        InventoryLog.objects.create(
            product=product,
            changed_by=actor if getattr(actor, "is_authenticated", False) else None,
            action=InventoryLog.Action.RETURNED,
            quantity_change=after - before,
            stock_before=before,
            stock_after=after,
            notes=f"Order {order.order_code}",
        )


def set_order_status(order: RentalOrder, new_status: str, actor=None) -> RentalOrder:
    """Ubah status pesanan beserta mutasi stoknya (atomik & idempoten).

    - Masuk DIKONFIRMASI / DIAMBIL -> stok berkurang + InventoryLog RENTED.
    - Masuk KEMBALI / DIBATALKAN  -> stok kembali + InventoryLog RETURNED.
    Penanda order.stock_deducted mencegah pemotongan/pengembalian ganda.
    """
    with transaction.atomic():
        order = RentalOrder.objects.select_for_update().get(pk=order.pk)
        if new_status == order.status:
            return order
        if (
            actor is not None
            and getattr(actor, "is_authenticated", False)
            and order.user_id is not None
            and order.user_id == actor.pk
            and new_status
            in (
                RentalOrder.Status.DIKONFIRMASI,
                RentalOrder.Status.DIAMBIL,
                RentalOrder.Status.KEMBALI,
            )
        ):
            raise MakerCheckerViolationError(
                "Pelanggaran Maker-Checker: Pembuat pesanan (Maker) tidak diizinkan "
                "memverifikasi atau menyetujui pesanannya sendiri (Checker harus staf berbeda)."
            )
        allowed = STATUS_TRANSITIONS.get(order.status, set())
        if new_status not in allowed:
            raise OrderTransitionError(
                f"Status {order.get_status_display()} tidak dapat diubah "
                f"menjadi {dict(RentalOrder.Status.choices).get(new_status, new_status)}."
            )

        if new_status in STOCK_OUT_STATUSES and not order.stock_deducted:
            _deduct_stock(order, actor)
            order.stock_deducted = True

        if new_status in STOCK_IN_STATUSES and order.stock_deducted:
            _restore_stock(order, actor)
            order.stock_deducted = False

        order.status = new_status
        order.save(update_fields=["status", "stock_deducted", "updated_at"])
    return order


def pickup_window(order: RentalOrder):
    """Rentang tanggal sewa efektif untuk tampilan."""
    return {
        "start": order.pickup_plan_date,
        "return": order.return_plan_date,
        "days": (order.return_plan_date - order.pickup_plan_date).days
        if order.return_plan_date and order.pickup_plan_date
        else 0,
    }


# ---------------------------------------------------------------------------
# Pengembalian alat: denda keterlambatan & mutasi stok per kondisi
# ---------------------------------------------------------------------------
def calculate_overdue(order: RentalOrder, actual_return_date):
    """Hitung (hari_terlambat, denda) dari tanggal riil vs rencana kembali.

    Denda = (Hari Terlambat) x Tarif Denda Harian (Rp 10.000 / hari).
    """
    if actual_return_date is None:
        return 0, 0
    if actual_return_date > order.return_plan_date:
        days = (actual_return_date - order.return_plan_date).days
        return days, days * LATE_FEE_PER_DAY
    return 0, 0


def complete_return(
    order: RentalOrder,
    actor,
    *,
    actual_return_date,
    item_conditions: dict,
    return_notes: str = "",
    fine_payment_method: str = "CASH",
) -> RentalOrder:
    """Selesaikan pengembalian: validasi, denda, mutasi stok, status KEMBALI.

    item_conditions: {item_id: {"condition": "...", "damage_fee": int}}
    """
    if actual_return_date is None:
        raise ReturnValidationError("Tanggal pengembalian wajib diisi.")
    if actual_return_date < order.pickup_plan_date:
        raise ReturnValidationError(
            "Tanggal pengembalian tidak boleh sebelum tanggal pengambilan."
        )
    if actual_return_date > date.today():
        raise ReturnValidationError(
            "Tanggal pengembalian tidak boleh melebihi hari ini."
        )

    with transaction.atomic():
        order = RentalOrder.objects.select_for_update().get(pk=order.pk)
        if (
            actor is not None
            and getattr(actor, "is_authenticated", False)
            and order.user_id is not None
            and order.user_id == actor.pk
        ):
            raise MakerCheckerViolationError(
                "Pelanggaran Maker-Checker: Pembuat pesanan (Maker) tidak diizinkan "
                "memproses pengembalian pesanannya sendiri (Checker harus staf berbeda)."
            )
        if order.status != RentalOrder.Status.DIAMBIL:
            raise OrderTransitionError(
                "Pengembalian hanya dapat diproses untuk pesanan berstatus "
                "Berjalan (Diambil)."
            )

        items = list(order.items.select_related("product"))
        overdue_days, overdue_fine = calculate_overdue(order, actual_return_date)

        damage_total = 0
        for item in items:
            data = item_conditions.get(item.pk) or {}
            condition = data.get("condition") or item.Condition.BAIK
            try:
                fee = int(data.get("damage_fee") or 0)
            except (TypeError, ValueError):
                raise ReturnValidationError("Nominal biaya kerusakan harus angka.")
            if fee < 0:
                raise ReturnValidationError("Biaya kerusakan tidak boleh negatif.")
            if condition not in dict(item.Condition.choices):
                raise ReturnValidationError("Kondisi barang tidak dikenal.")

            item.condition_at_return = condition
            item.item_damage_fee = fee
            item.save(update_fields=["condition_at_return", "item_damage_fee"])
            damage_total += fee

            product = Product.objects.select_for_update().get(pk=item.product_id)
            before = product.available_stock

            if condition in (
                item.Condition.BAIK,
                item.Condition.KOTOR,
                item.Condition.RUSAK_RINGAN,
            ):
                after = min(before + item.quantity, max(product.total_stock, before))
                if after != before:
                    product.available_stock = after
                    product.save(update_fields=["available_stock", "updated_at"])
                InventoryLog.objects.create(
                    product=product,
                    changed_by=actor if getattr(actor, "is_authenticated", False) else None,
                    action=InventoryLog.Action.RETURNED,
                    quantity_change=after - before,
                    stock_before=before,
                    stock_after=after,
                    notes=f"Order {order.order_code} ({condition})",
                )
            else:
                # RUSAK_BERAT / HILANG: unit tidak kembali ke stok siap sewa.
                if condition == item.Condition.HILANG:
                    product.total_stock = max(product.total_stock - item.quantity, 0)
                    product.available_stock = min(
                        product.available_stock, product.total_stock
                    )
                    product.save(
                        update_fields=["total_stock", "available_stock", "updated_at"]
                    )
                InventoryLog.objects.create(
                    product=product,
                    changed_by=actor if getattr(actor, "is_authenticated", False) else None,
                    action=InventoryLog.Action.DAMAGED,
                    quantity_change=0,
                    stock_before=before,
                    stock_after=product.available_stock,
                    notes=f"Order {order.order_code} kondisi={condition}",
                )

        total_fine = overdue_fine + damage_total
        if total_fine == 0:
            fine_status = RentalOrder.FinePaymentStatus.TIDAK_ADA_DENDA
        else:
            fine_status = RentalOrder.FinePaymentStatus.MENUNGGU_PEMBAYARAN

        note_parts = []
        if return_notes.strip():
            note_parts.append(return_notes.strip())
        if total_fine > 0:
            note_parts.append(f"Denda dibayar via {fine_payment_method}.")

        order.actual_return_date = actual_return_date
        order.overdue_days = overdue_days
        order.overdue_fine = overdue_fine
        order.damage_fine = damage_total
        order.total_fine = total_fine
        order.fine_payment_status = fine_status
        order.return_notes = " ".join(note_parts)
        order.returned_by_staff = actor if getattr(actor, "is_authenticated", False) else None
        order.status = RentalOrder.Status.KEMBALI
        order.stock_deducted = False
        order.save(
            update_fields=[
                "actual_return_date",
                "overdue_days",
                "overdue_fine",
                "damage_fine",
                "total_fine",
                "fine_payment_status",
                "return_notes",
                "returned_by_staff",
                "status",
                "stock_deducted",
                "updated_at",
            ]
        )
    return order


def settle_fine(order: RentalOrder, actor) -> RentalOrder:
    """Tandai denda pengembalian sudah dibayar lunas."""
    with transaction.atomic():
        order = RentalOrder.objects.select_for_update().get(pk=order.pk)
        if (
            actor is not None
            and getattr(actor, "is_authenticated", False)
            and order.user_id is not None
            and order.user_id == actor.pk
        ):
            raise MakerCheckerViolationError(
                "Pelanggaran Maker-Checker: Pembuat pesanan (Maker) tidak diizinkan "
                "melunasi denda pesanannya sendiri (Checker harus staf berbeda)."
            )
        if order.status != RentalOrder.Status.KEMBALI:
            raise OrderTransitionError("Denda hanya dapat dilunasi setelah pengembalian.")
        if order.total_fine <= 0:
            raise ReturnValidationError("Pesanan ini tidak memiliki denda.")
        if order.fine_payment_status == RentalOrder.FinePaymentStatus.LUNAS:
            raise ReturnValidationError("Denda pesanan ini sudah lunas.")
        order.fine_payment_status = RentalOrder.FinePaymentStatus.LUNAS
        order.save(update_fields=["fine_payment_status", "updated_at"])
    return order


def cancel_order_by_customer(order: RentalOrder, actor) -> RentalOrder:
    """Batalkan pesanan mandiri oleh pelanggan pemilik.

    Keamanan:
    - Hanya pemilik pesanan yang berhak membatalkan (anti-IDOR).
    - Hanya diizinkan ketika status masih MENUNGGU_PEMBAYARAN (dikunci dengan
      select_for_update di dalam transaction.atomic untuk mencegah race condition
      jika kasir baru saja mengonfirmasi pesanan).
    """
    from django.core.exceptions import PermissionDenied

    if actor is None or not getattr(actor, "is_authenticated", False):
        raise PermissionDenied("Autentikasi diperlukan.")

    with transaction.atomic():
        order = RentalOrder.objects.select_for_update().get(pk=order.pk)
        if order.user_id != actor.pk:
            raise PermissionDenied("Anda tidak berhak membatalkan pesanan ini.")
        if order.status != RentalOrder.Status.MENUNGGU_PEMBAYARAN:
            raise OrderTransitionError(
                "Pesanan ini tidak dapat dibatalkan karena statusnya sudah "
                f"{order.get_status_display()}."
            )
        if order.stock_deducted:
            _restore_stock(order, actor)
            order.stock_deducted = False

        order.status = RentalOrder.Status.DIBATALKAN
        order.save(update_fields=["status", "stock_deducted", "updated_at"])
    return order
