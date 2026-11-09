"""Views Modul Keranjang & Pemesanan Sewa (rentals)."""

import os
from datetime import date, datetime, timedelta
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from accounts.models import SecurityEvent
from accounts.permissions import role_required
from accounts.roles import ROLE_ADMIN, ROLE_CASHIER
from accounts.security import log_event
from catalog.models import Product

from . import services
from .constants import BANK_ACCOUNTS, PAYMENT_INSTRUCTIONS, WHATSAPP_NUMBER
from .forms import CheckoutForm, PaymentProofUploadForm
from .models import RentalOrder
from .services import CartError, OrderTransitionError, StockError


def _wants_json(request) -> bool:
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return True
    if request.GET.get("format") == "json":
        return True
    return "application/json" in (request.headers.get("accept") or "")


def _safe_next(request, fallback: str) -> str:
    candidate = request.POST.get("next") or request.GET.get("next") or ""
    if candidate and url_has_allowed_host_and_scheme(
        candidate,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return candidate
    return fallback


def _cart_count(request) -> int:
    cart = services.get_cart(request, create=False)
    if cart is None:
        return 0
    return sum(item.quantity for item in cart.items.all())


def _parse_date(raw):
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Keranjang
# ---------------------------------------------------------------------------
def add_to_cart(request, slug):
    """Tambah produk ke keranjang.

    Menerima POST (form detail produk) maupun GET (quick add dari katalog).
    Parameter: tgl (YYYY-MM-DD), durasi (hari), qty (unit).
    Mengembalikan JSON bila diminta AJAX, selain itu redirect.
    """
    product = get_object_or_404(
        Product.objects.select_related("category"),
        slug=slug,
        is_active=True,
    )
    source = request.POST if request.method == "POST" else request.GET
    product_url = reverse("catalog:product_detail", kwargs={"slug": product.slug})

    start_date = _parse_date(source.get("tgl"))
    duration = source.get("durasi") or 1
    quantity = source.get("qty") or 1

    try:
        if start_date is None:
            raise CartError("Silakan pilih tanggal pengambilan terlebih dahulu.")
        cart = services.get_cart(request)
        item = services.add_item_to_cart(
            cart,
            product,
            start_date=start_date,
            duration_days=duration,
            quantity=quantity,
        )
    except CartError as exc:
        if _wants_json(request):
            return JsonResponse({"ok": False, "message": str(exc)}, status=400)
        messages.error(request, str(exc))
        return redirect(_safe_next(request, product_url))

    if _wants_json(request):
        return JsonResponse(
            {
                "ok": True,
                "message": f"{product.name} ditambahkan ke keranjang.",
                "cart_items_count": _cart_count(request),
                "item_subtotal": item.subtotal,
            }
        )

    messages.success(
        request,
        f"{product.name} ({item.quantity} unit, {item.duration_days} hari) "
        "ditambahkan ke keranjang.",
    )
    return redirect(_safe_next(request, product_url))


def cart_detail(request):
    """Halaman /cart/ — rincian isi keranjang + kontrol jadwal terpusat."""
    cart = services.get_cart(request, create=False)
    items = (
        cart.items.select_related("product", "product__category").all()
        if cart
        else []
    )
    problems = services.cart_is_valid(cart) if cart else []

    items = list(items)
    schedule_start = min((i.start_date for i in items), default=None)
    schedule_duration = items[0].duration_days if items else 1
    schedule_return = (
        schedule_start + timedelta(days=schedule_duration + 1)
        if schedule_start
        else None
    )

    return render(
        request,
        "rentals/cart.html",
        {
            "cart": cart,
            "items": items,
            "cart_problems": problems,
            "can_checkout": bool(items) and not problems,
            "schedule_start": schedule_start,
            "schedule_duration": schedule_duration,
            "schedule_return": schedule_return,
            "duration_choices": range(services.MIN_DURATION, services.MAX_DURATION + 1),
        },
    )


@require_POST
def update_cart_schedule(request):
    """Sinkronkan tanggal ambil & durasi untuk seluruh item di keranjang."""
    cart = services.get_cart(request, create=False)
    if cart is None:
        messages.warning(request, "Keranjang masih kosong.")
        return redirect("rentals:cart_detail")

    start_date = _parse_date(request.POST.get("tgl"))
    durasi = request.POST.get("durasi")
    try:
        services.update_cart_schedule(cart, start_date, durasi)
        formatted_start = start_date.strftime("%d %b %Y") if start_date else ""
        messages.success(
            request,
            f"Jadwal sewa berhasil disinkronkan: Ambil {formatted_start}, durasi {durasi} hari. Tanggal kembali seluruh barang telah diseragamkan.",
        )
    except CartError as exc:
        messages.error(request, str(exc))
    return redirect("rentals:cart_detail")


@require_POST
def update_cart_item(request, item_id):
    cart = services.get_cart(request, create=False)
    item = get_object_or_404(cart.items, pk=item_id) if cart else None
    if item is None:
        messages.error(request, "Item keranjang tidak ditemukan.")
        return redirect("rentals:cart_detail")

    if request.POST.get("action") == "remove":
        item.delete()
        messages.success(request, "Item dihapus dari keranjang.")
        return redirect("rentals:cart_detail")

    try:
        services.update_item_quantity(item, request.POST.get("quantity"))
        messages.success(request, "Jumlah item diperbarui.")
    except CartError as exc:
        messages.error(request, str(exc))
    return redirect("rentals:cart_detail")


@require_POST
def remove_from_cart(request, item_id):
    cart = services.get_cart(request, create=False)
    item = get_object_or_404(cart.items, pk=item_id) if cart else None
    if item is None:
        messages.error(request, "Item keranjang tidak ditemukan.")
    else:
        name = item.product.name
        item.delete()
        messages.success(request, f"{name} dihapus dari keranjang.")
    return redirect("rentals:cart_detail")


# ---------------------------------------------------------------------------
# Checkout & pesanan
# ---------------------------------------------------------------------------
@login_required
def checkout(request):
    cart = services.get_cart(request, create=False)
    items = list(cart.items.select_related("product")) if cart else []

    if not cart or not items:
        messages.warning(request, "Keranjang masih kosong. Pilih peralatan dulu, ya.")
        return redirect("rentals:cart_detail")

    problems = services.cart_is_valid(cart)

    if request.method == "POST":
        form = CheckoutForm(request.POST, cart=cart)
        if not problems and form.is_valid():
            try:
                order = services.create_order_from_cart(
                    cart, request.user, form.cleaned_data
                )
            except CartError as exc:
                messages.error(request, str(exc))
            else:
                messages.success(
                    request,
                    f"Pesanan {order.order_code} berhasil dibuat. "
                    "Silakan selesaikan pembayaran di kasir.",
                )
                return redirect("rentals:order_detail", order_code=order.order_code)
    else:
        form = CheckoutForm(
            cart=cart,
            initial={
                "full_name": request.user.display_name,
                "phone_number": getattr(request.user, "phone_number", "") or "",
                "pickup_plan_date": min(item.start_date for item in items),
                "return_plan_date": max(item.return_date for item in items),
            },
        )

    return render(
        request,
        "rentals/checkout.html",
        {
            "cart": cart,
            "items": items,
            "form": form,
            "cart_problems": problems,
            "total_rental_fee": sum(item.rental_price_total for item in items),
            "grand_total": sum(item.subtotal for item in items),
        },
    )


def _proof_size(order: RentalOrder) -> int:
    """Ukuran berkas bukti; 0 bila belum ada (hindari ValueError FieldFile)."""
    if not order.payment_proof:
        return 0
    try:
        return order.payment_proof.size
    except (ValueError, OSError):
        return 0


def _is_staff_viewer(user) -> bool:
    return bool(
        user.is_superuser
        or user.groups.filter(name__in=[ROLE_ADMIN, ROLE_CASHIER]).exists()
    )


def _whatsapp_link(order: RentalOrder) -> str:
    """Tautan konfirmasi WhatsApp berisi ringkasan pesanan (URL-encoded)."""
    text = (
        "Halo TrailGear Rent, saya ingin konfirmasi pembayaran sewa.\n"
        f"Kode Booking: {order.order_code}\n"
        f"Nama Penyewa: {order.full_name}\n"
        f"Tanggal Ambil: {order.pickup_plan_date:%d-%m-%Y}\n"
        f"Durasi: {order.duration_days} hari\n"
        f"Rencana Kembali: {order.return_plan_date:%d-%m-%Y}\n"
        f"Metode Bayar: {order.formatted_payment_method}\n"
        f"Total Tagihan: {order.formatted_grand_total}"
    )
    return f"https://wa.me/{WHATSAPP_NUMBER}?text={quote(text)}"


def _order_detail_context(request, order: RentalOrder, proof_form=None) -> dict:
    can_upload = order.can_upload_payment_proof()
    if can_upload and proof_form is None:
        proof_form = PaymentProofUploadForm(
            instance=order,
            initial={"payment_method": order.payment_method},
        )
    return {
        "order": order,
        "is_staff_viewer": _is_staff_viewer(request.user),
        "proof_form": proof_form if can_upload else None,
        "can_upload_proof": can_upload,
        "banks": BANK_ACCOUNTS,
        "payment_instructions": PAYMENT_INSTRUCTIONS,
        "wa_link": _whatsapp_link(order),
    }


@login_required
def order_detail(request, order_code):
    order = get_object_or_404(
        RentalOrder.objects.select_related("user").prefetch_related(
            "items__product__category"
        ),
        order_code=order_code,
    )
    is_staff_viewer = _is_staff_viewer(request.user)
    if order.user_id != request.user.pk and not is_staff_viewer:
        log_event(
            request,
            SecurityEvent.ACCESS_DENIED,
            SecurityEvent.STATUS_BLOCKED,
            user=request.user,
            description=f"order_detail ditolak order={order.order_code}",
        )
        raise PermissionDenied("Anda tidak berhak melihat pesanan ini.")

    return render(
        request,
        "rentals/order_detail.html",
        _order_detail_context(request, order),
    )


@login_required
@require_POST
def upload_payment_proof(request, order_code):
    """Unggah / ganti bukti transfer. Hanya pemilik & status menunggu bayar."""
    order = get_object_or_404(RentalOrder, order_code=order_code)

    # 1) Otorisasi kepemilikan (anti-IDOR).
    if order.user_id != request.user.pk:
        log_event(
            request,
            SecurityEvent.ACCESS_DENIED,
            SecurityEvent.STATUS_BLOCKED,
            user=request.user,
            description=f"upload_proof IDOR order={order.order_code}",
        )
        raise PermissionDenied("Anda tidak berhak mengunggah bukti untuk pesanan ini.")

    # 2) Status harus masih menunggu pembayaran.
    if not order.can_upload_payment_proof():
        messages.error(
            request,
            "Bukti pembayaran tidak dapat diunggah karena pesanan sudah "
            f"{order.get_status_display()}.",
        )
        return redirect("rentals:order_detail", order_code=order.order_code)

    # 3) COD tidak memakai bukti transfer.
    if order.payment_method == RentalOrder.PaymentMethod.CASH:
        messages.info(
            request,
            "Pesanan ini memakai pembayaran tunai (COD) di kasir toko, "
            "jadi tidak perlu unggah bukti transfer.",
        )
        return redirect("rentals:order_detail", order_code=order.order_code)

    old_name = order.payment_proof.name if order.payment_proof else ""
    form = PaymentProofUploadForm(request.POST, request.FILES, instance=order)

    if not form.is_valid():
        file_errors = form.errors.get("payment_proof")
        if file_errors:
            log_event(
                request,
                SecurityEvent.PAYMENT_PROOF_REJECTED,
                SecurityEvent.STATUS_BLOCKED,
                user=request.user,
                description=(
                    f"order={order.order_code} alasan=validasi berkas"
                ),
            )
        return render(
            request,
            "rentals/order_detail.html",
            _order_detail_context(request, order, proof_form=form),
            status=400,
        )

    order = form.save(commit=False)
    order.payment_proof_uploaded_at = timezone.now()
    order.save(
        update_fields=[
            "payment_method",
            "payment_proof",
            "payment_proof_uploaded_at",
            "updated_at",
        ]
    )

    # Hapus berkas lama bila unggah ulang, supaya tidak menumpuk di disk.
    if old_name and old_name != order.payment_proof.name:
        try:
            order.payment_proof.storage.delete(old_name)
        except Exception:  # pragma: no cover - berkas lama sudah hilang
            pass

    log_event(
        request,
        SecurityEvent.PAYMENT_PROOF_UPLOADED,
        SecurityEvent.STATUS_SUCCESS,
        user=request.user,
        description=(
            f"order={order.order_code} method={order.payment_method} "
            f"ext={order.payment_proof_ext} size={_proof_size(order)}"
        ),
    )
    messages.success(
        request,
        "Bukti pembayaran berhasil diunggah. Menunggu verifikasi kasir.",
    )
    return redirect("rentals:order_detail", order_code=order.order_code)


@login_required
def payment_proof_file(request, order_code):
    """Sajikan berkas bukti bayar secara terotorisasi (bukan URL media publik)."""
    order = get_object_or_404(RentalOrder, order_code=order_code)
    if order.user_id != request.user.pk and not _is_staff_viewer(request.user):
        log_event(
            request,
            SecurityEvent.ACCESS_DENIED,
            SecurityEvent.STATUS_BLOCKED,
            user=request.user,
            description=f"proof_file ditolak order={order.order_code}",
        )
        raise PermissionDenied("Anda tidak berhak mengakses berkas ini.")

    if not order.payment_proof:
        raise Http404("Belum ada bukti pembayaran.")

    try:
        path = order.payment_proof.path
    except (ValueError, NotImplementedError):
        raise Http404("Berkas tidak tersedia.")

    if not os.path.isfile(path):
        raise Http404("Berkas tidak ditemukan.")

    content_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".pdf": "application/pdf",
    }
    ext = order.payment_proof_ext
    response = FileResponse(
        open(path, "rb"),
        content_type=content_types.get(ext, "application/octet-stream"),
        as_attachment=(ext == ".pdf"),
        filename=f"bukti-{order.order_code}{ext}",
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response


@login_required
def order_history(request):
    """Riwayat booking pelanggan terhubung ke halaman /transaction/."""
    return redirect("accounts:transaction_list")


# ---------------------------------------------------------------------------
# Dashboard staff: daftar & aksi pesanan
# ---------------------------------------------------------------------------
@role_required(ROLE_CASHIER, ROLE_ADMIN)
def staff_order_list(request):
    selected_status = request.GET.get("status") or ""
    valid = {choice for choice, _ in RentalOrder.Status.choices}
    orders = RentalOrder.objects.select_related("user").prefetch_related(
        "items__product"
    )
    if selected_status in valid:
        orders = orders.filter(status=selected_status)
    else:
        selected_status = ""
        orders = orders.exclude(
            status__in=[RentalOrder.Status.KEMBALI, RentalOrder.Status.DIBATALKAN]
        )

    return render(
        request,
        "rentals/staff_orders.html",
        {
            "orders": orders.order_by("-created_at")[:100],
            "selected_status": selected_status,
            "statuses": RentalOrder.Status.choices,
            "stats": staff_stats(),
        },
    )


@role_required(ROLE_CASHIER, ROLE_ADMIN)
@require_POST
def staff_order_action(request, order_code, action):
    """Aksi cepat: confirm / pickup / return / cancel (POST + CSRF)."""
    order = get_object_or_404(RentalOrder, order_code=order_code)
    new_status = services.ACTION_STATUS_MAP.get(action)
    if new_status is None:
        messages.error(request, "Aksi tidak dikenal.")
        return redirect("rentals:staff_order_list")

    try:
        services.set_order_status(order, new_status, actor=request.user)
    except OrderTransitionError as exc:
        messages.error(request, str(exc))
    except StockError as exc:
        messages.error(request, f"Gagal memproses: {exc}")
    else:
        messages.success(
            request,
            f"Pesanan {order.order_code} kini berstatus "
            f"{order.get_status_display()}.",
        )
    return redirect(_safe_next(request, reverse("rentals:staff_order_list")))


def staff_stats() -> dict:
    """Ringkasan operasional untuk dashboard staf."""
    today = date.today()
    qs = RentalOrder.objects.all()
    return {
        "pending_payment": qs.filter(
            status=RentalOrder.Status.MENUNGGU_PEMBAYARAN
        ).count(),
        "active_rentals": qs.filter(status=RentalOrder.Status.DIAMBIL).count(),
        "pickup_today": qs.filter(
            status=RentalOrder.Status.DIKONFIRMASI, pickup_plan_date=today
        ).count(),
        "return_today": qs.filter(
            status=RentalOrder.Status.DIAMBIL, return_plan_date=today
        ).count(),
    }


def recent_orders(limit=6):
    """Pesanan terbaru (semua status) untuk panel dashboard."""
    return (
        RentalOrder.objects.select_related("user")
        .prefetch_related("items__product")
        .order_by("-created_at")[:limit]
    )


def open_orders_for_dashboard(limit=15):
    """Pesanan yang menunggu tindakan staf (dipakai dashboard admin/kasir)."""
    return (
        RentalOrder.objects.exclude(
            status__in=[RentalOrder.Status.KEMBALI, RentalOrder.Status.DIBATALKAN]
        )
        .select_related("user")
        .prefetch_related("items__product")
        .annotate(item_count=Count("items"))
        .order_by("created_at")[:limit]
    )
