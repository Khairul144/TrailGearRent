"""Views authentication TrailGear (session based, tanpa JWT)."""

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import (
    authenticate,
    get_user_model,
    login as auth_login,
    logout as auth_logout,
    update_session_auth_hash,
)
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_http_methods

from . import ratelimit
from .forms import LoginForm, PasswordChangeForm, ProfileForm, RegistrationForm
from .models import SecurityEvent
from .permissions import role_required
from .roles import (
    ROLE_ADMIN,
    ROLE_CASHIER,
    ROLE_CUSTOMER,
    assign_role,
    primary_role,
)
from .security import log_event

User = get_user_model()

GENERIC_LOGIN_ERROR = "Username/email atau password tidak valid."
LOCKED_LOGIN_ERROR = "Akun sementara tidak dapat digunakan. Silakan coba lagi nanti."
RATE_LIMIT_LOGIN_ERROR = (
    "Terlalu banyak percobaan login. Silakan coba lagi dalam beberapa menit."
)
RATE_LIMIT_REGISTER_ERROR = (
    "Terlalu banyak percobaan registrasi dari jaringan ini. "
    "Silakan coba lagi dalam 10 menit."
)


def _is_safe_next(request, url):
    return bool(url) and url_has_allowed_host_and_scheme(
        url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    )


def _first_error_message(form):
    """Ambil pesan error pertama untuk ditampilkan di #authMsg."""
    for errors in form.errors.values():
        for error in errors:
            return str(error)
    return ""


def post_login_url_name(user):
    """Halaman tujuan setelah login, sesuai role.

    Admin  -> /dashboard/admin/
    Kasir  -> /dashboard/cashier/
    lainnya (Customer / tanpa role) -> beranda
    """
    role = primary_role(user)
    if role == ROLE_ADMIN:
        return "accounts:admin_dashboard"
    if role == ROLE_CASHIER:
        return "accounts:cashier_dashboard"
    return "home"


@never_cache
def register(request):
    if request.user.is_authenticated:
        return redirect(post_login_url_name(request.user))

    ip = ratelimit.client_ip(request)
    error = None
    form = RegistrationForm()

    if request.method == "POST":
        if ratelimit.register_blocked(ip):
            log_event(
                request,
                SecurityEvent.RATE_LIMIT_REGISTER,
                SecurityEvent.STATUS_BLOCKED,
                description="Batas 3 registrasi / 10 menit tercapai.",
            )
            return render(
                request,
                "accounts/register.html",
                {"form": RegistrationForm(), "error": RATE_LIMIT_REGISTER_ERROR},
                status=429,
            )

        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Setiap pendaftar baru otomatis menjadi Customer (Django Group).
            assign_role(user, ROLE_CUSTOMER)
            ratelimit.register_bump(ip)
            log_event(
                request,
                SecurityEvent.REGISTER_SUCCESS,
                SecurityEvent.STATUS_SUCCESS,
                user=user,
                description=f"user_id={user.pk}",
            )
            auth_login(
                request,
                user,
                backend="accounts.backends.EmailOrUsernameBackend",
            )
            messages.success(
                request,
                f"Selamat datang di TrailGear Rent, {user.first_name or user.username}! Akun Anda berhasil dibuat dan Anda telah otomatis masuk.",
            )
            return redirect("home")

        ratelimit.register_bump(ip)
        invalid = ",".join(sorted(form.errors.keys()))
        # Hanya nama field yang dicatat; nilai input (termasuk password) tidak.
        log_event(
            request,
            SecurityEvent.REGISTER_FAILED,
            SecurityEvent.STATUS_FAILURE,
            description=f"invalid_fields={invalid}",
        )
        error = _first_error_message(form) or "Registrasi gagal. Periksa kembali data yang Anda isi."

    return render(
        request,
        "accounts/register.html",
        {"form": form, "error": error},
    )


@sensitive_variables("password")
@never_cache
def login_view(request):
    if request.user.is_authenticated:
        return redirect(post_login_url_name(request.user))

    ip = ratelimit.client_ip(request)
    next_url = request.POST.get("next") or request.GET.get("next") or ""
    error = None

    if request.method == "POST":
        identifier = (request.POST.get("username") or "").strip()
        password = request.POST.get("password") or ""

        if ratelimit.login_blocked(ip, identifier):
            log_event(
                request,
                SecurityEvent.RATE_LIMIT_LOGIN,
                SecurityEvent.STATUS_BLOCKED,
                description="Batas percobaan login tercapai.",
            )
            return render(
                request,
                "accounts/login.html",
                {
                    "form": LoginForm(),
                    "error": RATE_LIMIT_LOGIN_ERROR,
                    "next": next_url,
                },
                status=429,
            )

        # Akun yang cocok dengan identifier (bila ada). Dipakai untuk lockout.
        known = None
        if identifier:
            known = (
                User.objects.filter(username__iexact=identifier).first()
                or User.objects.filter(email__iexact=identifier).first()
            )

        # 1) Account lockout: tolak SEBELUM verifikasi password, sehingga
        #    password yang benar pun tidak bisa dipakai selama akun terkunci.
        if known is not None and known.is_locked:
            ratelimit.login_bump(ip, identifier)
            log_event(
                request,
                SecurityEvent.LOGIN_FAILED,
                SecurityEvent.STATUS_FAILURE,
                user=known,
                description="Akun terkunci sementara; login ditolak.",
            )
            error = LOCKED_LOGIN_ERROR
            return render(
                request,
                "accounts/login.html",
                {"form": LoginForm(), "error": error, "next": next_url},
            )

        user = None
        if identifier and password:
            user = authenticate(request, username=identifier, password=password)

        if user is not None:
            ratelimit.login_reset(ip, identifier)
            # 3) Login berhasil -> counter & lock direset.
            user.reset_login_lock()
            auth_login(request, user)
            log_event(
                request,
                SecurityEvent.LOGIN_SUCCESS,
                SecurityEvent.STATUS_SUCCESS,
                user=user,
                description=f"user_id={user.pk}",
            )
            messages.success(
                request,
                f"Selamat datang kembali, {user.first_name or user.username}!",
            )
            if _is_safe_next(request, next_url):
                return redirect(next_url)
            return redirect(post_login_url_name(user))

        # 2) Credential salah -> naikkan counter akun (atomik) + rate limit IP.
        if known is not None:
            newly_locked = known.register_failed_login()
            if newly_locked:
                log_event(
                    request,
                    SecurityEvent.ACCOUNT_LOCKED,
                    SecurityEvent.STATUS_BLOCKED,
                    user=known,
                    description=(
                        f"threshold={settings.ACCOUNT_LOCKOUT_THRESHOLD} "
                        f"durasi={settings.ACCOUNT_LOCKOUT_DURATION}menit"
                    ),
                )

        ratelimit.login_bump(ip, identifier)

        # Jika akunnya ada tapi nonaktif, catat sebagai ACCOUNT_DISABLED.
        if known is not None and not known.is_active:
            log_event(
                request,
                SecurityEvent.ACCOUNT_DISABLED,
                SecurityEvent.STATUS_FAILURE,
                user=known,
                description="Percobaan login pada akun nonaktif.",
            )

        # Pesan SELALU sama: tidak membedakan user tidak ada vs password salah.
        log_event(
            request,
            SecurityEvent.LOGIN_FAILED,
            SecurityEvent.STATUS_FAILURE,
            user=None,
            description=f"identifier={identifier[:64]!r}",
        )
        error = GENERIC_LOGIN_ERROR

    return render(
        request,
        "accounts/login.html",
        {"form": LoginForm(), "error": error, "next": next_url},
    )


@require_http_methods(["POST"])
def logout_view(request):
    """Logout hanya lewat POST + CSRF (mencegah logout CSRF lewat <img>/link)."""
    if request.user.is_authenticated:
        user = request.user
        log_event(
            request,
            SecurityEvent.LOGOUT,
            SecurityEvent.STATUS_SUCCESS,
            user=user,
            description=f"user_id={user.pk}",
        )
    auth_logout(request)
    messages.info(request, "Anda telah berhasil keluar (logout).")
    return redirect("accounts:login")


@login_required
def dashboard(request):
    events = SecurityEvent.objects.filter(user=request.user).order_by("-timestamp")[:10]
    return render(
        request,
        "accounts/dashboard.html",
        {"events": events, "role": primary_role(request.user)},
    )


# ---------------------------------------------------------------------------
# Area Admin: layout shell + satu halaman per menu sidebar
# ---------------------------------------------------------------------------
ADMIN_PAGE_SIZE = 15


def _admin_counts() -> dict:
    """Angka badge sidebar admin."""
    from catalog.models import Product
    from rentals.models import RentalOrder

    orders = RentalOrder.objects.all()
    total_staff = (
        User.objects.filter(groups__name__in=[ROLE_CASHIER, ROLE_ADMIN])
        .distinct()
        .count()
    )
    return {
        "badge_open_orders": orders.exclude(
            status__in=[RentalOrder.Status.KEMBALI, RentalOrder.Status.DIBATALKAN]
        ).count(),
        "badge_pending_payment": orders.filter(
            status=RentalOrder.Status.MENUNGGU_PEMBAYARAN
        ).count(),
        "badge_security": SecurityEvent.objects.exclude(
            status=SecurityEvent.STATUS_SUCCESS
        ).count(),
        "badge_users": User.objects.count(),
        "badge_staff": total_staff,
        "badge_products": Product.objects.count(),
    }


def _querystring_without_page(request) -> str:
    params = request.GET.copy()
    params.pop("page", None)
    return params.urlencode()


def _admin_render(request, template: str, active_menu: str, context: dict):
    base = {
        "role": primary_role(request.user),
        "active_menu": active_menu,
        "querystring": _querystring_without_page(request),
    }
    base.update(_admin_counts())
    base.update(context)
    return render(request, template, base)


@role_required(ROLE_ADMIN)
def admin_dashboard(request):
    """Ringkasan admin: KPI, pesanan terbaru, dan log keamanan terbaru."""
    from rentals.models import RentalOrder, rupiah
    from rentals.views import recent_orders, staff_stats

    total_users = User.objects.count()
    total_customer = User.objects.filter(groups__name=ROLE_CUSTOMER).distinct().count()
    total_cashier = User.objects.filter(groups__name=ROLE_CASHIER).distinct().count()
    total_admin = User.objects.filter(groups__name=ROLE_ADMIN).distinct().count()
    active_staff = (
        User.objects.filter(groups__name__in=[ROLE_CASHIER, ROLE_ADMIN], is_active=True)
        .distinct()
        .count()
    )

    revenue = (
        RentalOrder.objects.filter(
            status__in=[RentalOrder.Status.DIAMBIL, RentalOrder.Status.KEMBALI]
        ).aggregate(total=Sum("total_rental_fee"))["total"]
        or 0
    )

    events = SecurityEvent.objects.select_related("user").order_by("-timestamp")[:6]

    return _admin_render(
        request,
        "accounts/admin/dashboard.html",
        "dashboard",
        {
            "total_users": total_users,
            "total_customer": total_customer,
            "total_cashier": total_cashier,
            "total_admin": total_admin,
            "total_staff": total_cashier + total_admin,
            "active_staff": active_staff,
            "revenue": revenue,
            "revenue_fmt": rupiah(revenue),
            "rental_stats": staff_stats(),
            "recent_orders": recent_orders(6),
            "events": events,
        },
    )


@role_required(ROLE_ADMIN)
def admin_users(request):
    """Manajemen seluruh user + filter role/status."""
    query = (request.GET.get("q") or "").strip()[:80]
    role_filter = request.GET.get("role") or ""
    status_filter = request.GET.get("status") or ""

    users = User.objects.prefetch_related("groups").order_by("-date_joined")
    if query:
        users = users.filter(
            Q(username__icontains=query)
            | Q(email__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
        )
    if role_filter in (ROLE_ADMIN, ROLE_CASHIER, ROLE_CUSTOMER):
        users = users.filter(groups__name=role_filter).distinct()
    if status_filter == "active":
        users = users.filter(is_active=True)
    elif status_filter == "inactive":
        users = users.filter(is_active=False)

    paginator = Paginator(users, ADMIN_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))
    for item in page_obj.object_list:
        item.role_name = primary_role(item) or "—"

    return _admin_render(
        request,
        "accounts/admin/users.html",
        "users",
        {
            "page_obj": page_obj,
            "users": page_obj.object_list,
            "query": query,
            "role_filter": role_filter,
            "status_filter": status_filter,
            "total_users": User.objects.count(),
            "total_customer": User.objects.filter(groups__name=ROLE_CUSTOMER).distinct().count(),
            "total_cashier": User.objects.filter(groups__name=ROLE_CASHIER).distinct().count(),
            "total_admin": User.objects.filter(groups__name=ROLE_ADMIN).distinct().count(),
            "page_range": paginator.get_elided_page_range(
                page_obj.number, on_each_side=1, on_ends=1
            ),
        },
    )


@role_required(ROLE_ADMIN)
def admin_staff(request):
    """Daftar akun staff (kasir & admin) beserta status aktifnya."""
    from rentals.models import RentalOrder

    staff = (
        User.objects.filter(groups__name__in=[ROLE_CASHIER, ROLE_ADMIN])
        .prefetch_related("groups")
        .distinct()
        .order_by("username")
    )
    rows = list(staff)
    for item in rows:
        item.role_name = primary_role(item) or "—"
        item.order_count = RentalOrder.objects.filter(
            user=item, status=RentalOrder.Status.KEMBALI
        ).count()

    return _admin_render(
        request,
        "accounts/admin/staff.html",
        "staff",
        {
            "staff_rows": rows,
            "total_staff": len(rows),
            "active_staff": len([s for s in rows if s.is_active]),
            "inactive_staff": len([s for s in rows if not s.is_active]),
        },
    )


@role_required(ROLE_ADMIN)
@require_http_methods(["POST"])
def admin_user_toggle(request, user_id):
    """Aktifkan / nonaktifkan akun (tidak boleh untuk diri sendiri)."""
    target = User.objects.filter(pk=user_id).first()
    if target is None:
        messages.error(request, "User tidak ditemukan.")
    elif target.pk == request.user.pk:
        messages.error(request, "Anda tidak dapat menonaktifkan akun sendiri.")
    else:
        target.is_active = not target.is_active
        target.save(update_fields=["is_active"])
        messages.success(
            request,
            f"Akun {target.username} {'diaktifkan' if target.is_active else 'dinonaktifkan'}.",
        )
    return redirect(request.POST.get("next") or "accounts:admin_users")


@role_required(ROLE_ADMIN)
def admin_products(request):
    """Daftar barang + stok, filter kategori & pencarian."""
    from catalog.models import Category, Product

    query = (request.GET.get("q") or "").strip()[:80]
    cat_slug = request.GET.get("cat") or ""
    stock_filter = request.GET.get("stok") or ""

    products = Product.objects.select_related("category")
    if query:
        products = products.filter(
            Q(name__icontains=query)
            | Q(brand_name__icontains=query)
            | Q(category__name__icontains=query)
        )
    if cat_slug:
        products = products.filter(category__slug=cat_slug)
    if stock_filter == "low":
        products = products.filter(available_stock__lte=2, available_stock__gt=0)
    elif stock_filter == "out":
        products = products.filter(available_stock=0)

    paginator = Paginator(products.order_by("category__order", "name"), ADMIN_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    return _admin_render(
        request,
        "accounts/admin/products.html",
        "products",
        {
            "page_obj": page_obj,
            "products": page_obj.object_list,
            "categories": Category.objects.order_by("order", "name"),
            "query": query,
            "cat_slug": cat_slug,
            "stock_filter": stock_filter,
            "total_products": Product.objects.count(),
            "total_out": Product.objects.filter(available_stock=0).count(),
            "total_low": Product.objects.filter(
                available_stock__lte=2, available_stock__gt=0
            ).count(),
            "page_range": paginator.get_elided_page_range(
                page_obj.number, on_each_side=1, on_ends=1
            ),
        },
    )


@role_required(ROLE_ADMIN)
def admin_rentals(request):
    """Semua pesanan sewa + aksi proses status."""
    from rentals.models import RentalOrder

    selected_status = request.GET.get("status") or ""
    query = (request.GET.get("q") or "").strip()[:80]

    orders = RentalOrder.objects.select_related("user").prefetch_related(
        "items__product"
    )
    if selected_status in dict(RentalOrder.Status.choices):
        orders = orders.filter(status=selected_status)
    else:
        selected_status = ""
    if query:
        orders = orders.filter(
            Q(order_code__icontains=query)
            | Q(full_name__icontains=query)
            | Q(phone_number__icontains=query)
        )

    paginator = Paginator(orders.order_by("-created_at"), ADMIN_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    return _admin_render(
        request,
        "accounts/admin/rentals.html",
        "rentals",
        {
            "page_obj": page_obj,
            "open_orders": page_obj.object_list,
            "statuses": RentalOrder.Status.choices,
            "selected_status": selected_status,
            "query": query,
            "stats": {
                "all": RentalOrder.objects.count(),
                "pending": RentalOrder.objects.filter(
                    status=RentalOrder.Status.MENUNGGU_PEMBAYARAN
                ).count(),
                "active": RentalOrder.objects.filter(
                    status=RentalOrder.Status.DIAMBIL
                ).count(),
                "done": RentalOrder.objects.filter(
                    status=RentalOrder.Status.KEMBALI
                ).count(),
                "cancelled": RentalOrder.objects.filter(
                    status=RentalOrder.Status.DIBATALKAN
                ).count(),
            },
            "page_range": paginator.get_elided_page_range(
                page_obj.number, on_each_side=1, on_ends=1
            ),
        },
    )


@role_required(ROLE_ADMIN)
def admin_payments(request):
    """Pembayaran yang menunggu verifikasi kasir."""
    from rentals.models import RentalOrder, rupiah

    pending = (
        RentalOrder.objects.filter(status=RentalOrder.Status.MENUNGGU_PEMBAYARAN)
        .select_related("user")
        .prefetch_related("items__product")
        .order_by("created_at")
    )
    pending_total = pending.aggregate(total=Sum("grand_total"))["total"] or 0

    return _admin_render(
        request,
        "accounts/admin/payments.html",
        "payments",
        {
            "open_orders": pending,
            "pending_count": pending.count(),
            "pending_total": pending_total,
            "pending_total_fmt": rupiah(pending_total),
        },
    )


@role_required(ROLE_ADMIN)
def admin_security(request):
    """Log keamanan lengkap dengan filter."""
    status_filter = request.GET.get("status") or ""
    type_filter = request.GET.get("event") or ""

    events = SecurityEvent.objects.select_related("user").order_by("-timestamp")
    if status_filter in dict(SecurityEvent.STATUS_CHOICES):
        events = events.filter(status=status_filter)
    else:
        status_filter = ""
    valid_events = {value for value, _ in SecurityEvent.EVENT_CHOICES}
    if type_filter in valid_events:
        events = events.filter(event_type=type_filter)
    else:
        type_filter = ""

    paginator = Paginator(events, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    return _admin_render(
        request,
        "accounts/admin/security.html",
        "security",
        {
            "page_obj": page_obj,
            "events": page_obj.object_list,
            "event_choices": SecurityEvent.EVENT_CHOICES,
            "status_choices": SecurityEvent.STATUS_CHOICES,
            "status_filter": status_filter,
            "type_filter": type_filter,
            "page_range": paginator.get_elided_page_range(
                page_obj.number, on_each_side=1, on_ends=1
            ),
        },
    )


@role_required(ROLE_ADMIN)
def admin_reports(request):
    """Laporan ringkas: pendapatan, status pesanan, produk terlaris."""
    from catalog.models import Product
    from rentals.models import RentalOrder, RentalOrderItem, rupiah

    finished = RentalOrder.objects.filter(
        status__in=[RentalOrder.Status.DIAMBIL, RentalOrder.Status.KEMBALI]
    )
    totals = finished.aggregate(
        rental=Sum("total_rental_fee"),
    )

    by_status = (
        RentalOrder.objects.values("status")
        .annotate(jumlah=Count("id"), nilai=Sum("grand_total"))
        .order_by("status")
    )
    status_labels = dict(RentalOrder.Status.choices)
    status_rows = [
        {
            "label": status_labels.get(row["status"], row["status"]),
            "kode": row["status"],
            "jumlah": row["jumlah"],
            "nilai": row["nilai"] or 0,
            "nilai_fmt": rupiah(row["nilai"] or 0),
        }
        for row in by_status
    ]

    top_products = [
        {
            "name": row["product__name"],
            "unit": row["unit"],
            "nilai": row["nilai"] or 0,
            "nilai_fmt": rupiah(row["nilai"] or 0),
        }
        for row in RentalOrderItem.objects.exclude(
            order__status__in=[
                RentalOrder.Status.DIBATALKAN,
                RentalOrder.Status.MENUNGGU_PEMBAYARAN,
            ]
        )
        .values("product__name")
        .annotate(unit=Sum("quantity"), nilai=Sum("subtotal"))
        .order_by("-unit")[:5]
    ]

    revenue = totals["rental"] or 0

    return _admin_render(
        request,
        "accounts/admin/reports.html",
        "reports",
        {
            "revenue": revenue,
            "revenue_fmt": rupiah(revenue),
            "order_count": RentalOrder.objects.count(),
            "status_rows": status_rows,
            "top_products": top_products,
            "total_products": Product.objects.count(),
        },
    )


@role_required(ROLE_CASHIER, ROLE_ADMIN)
def cashier_dashboard(request):
    """Dashboard Kasir: operasional rental (konfirmasi, ambil, kembali)."""
    from rentals.views import open_orders_for_dashboard, recent_orders, staff_stats

    return render(
        request,
        "accounts/cashier_dashboard.html",
        {
            "role": primary_role(request.user),
            "open_orders": open_orders_for_dashboard(),
            "recent_orders": recent_orders(),
            "rental_stats": staff_stats(),
        },
    )


@login_required
@never_cache
def password_change(request):
    error = None
    success = None
    form = PasswordChangeForm(request.user)
    expired = request.GET.get("expired") == "1" or request.user.password_expired

    if request.method == "POST":
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            request.user.set_password(form.cleaned_data["new_password"])
            request.user.save(update_fields=["password", "password_changed_at"])
            # Session saat ini tetap login setelah password berubah.
            update_session_auth_hash(request, request.user)
            log_event(
                request,
                SecurityEvent.PASSWORD_CHANGED,
                SecurityEvent.STATUS_SUCCESS,
                user=request.user,
                description=f"user_id={request.user.pk}",
            )
            success = "Password berhasil diubah."
            expired = False
            form = PasswordChangeForm(request.user)
        else:
            error = _first_error_message(form) or "Password gagal diubah. Periksa kembali input Anda."
            expired = request.user.password_expired

    return render(
        request,
        "accounts/password_change.html",
        {"form": form, "error": error, "success": success, "expired": expired},
    )


@login_required
@never_cache
def settings_view(request):
    """Halaman Pengaturan: profil (form_type=profile) + password (form_type=password)."""
    profile_form = ProfileForm(instance=request.user)
    password_form = PasswordChangeForm(request.user)

    if request.method == "POST":
        form_type = request.POST.get("form_type", "profile")

        if form_type == "password":
            password_form = PasswordChangeForm(request.user, request.POST)
            if password_form.is_valid():
                request.user.set_password(password_form.cleaned_data["new_password"])
                request.user.save(update_fields=["password", "password_changed_at"])
                # Sesi saat ini tetap login setelah password diganti.
                update_session_auth_hash(request, request.user)
                log_event(
                    request,
                    SecurityEvent.PASSWORD_CHANGED,
                    SecurityEvent.STATUS_SUCCESS,
                    user=request.user,
                    description=f"user_id={request.user.pk} (via pengaturan)",
                )
                messages.success(request, "Password berhasil diubah.")
                password_form = PasswordChangeForm(request.user)
            else:
                messages.error(
                    request,
                    _first_error_message(password_form)
                    or "Password gagal diubah. Periksa kembali input Anda.",
                )
        else:
            profile_form = ProfileForm(request.POST, instance=request.user)
            if profile_form.is_valid():
                profile_form.save()
                messages.success(request, "Perubahan profil berhasil disimpan.")
                profile_form = ProfileForm(instance=request.user)
            else:
                messages.error(
                    request,
                    _first_error_message(profile_form)
                    or "Perubahan gagal disimpan. Periksa kembali data Anda.",
                )

    return render(
        request,
        "accounts/settings.html",
        {"profile_form": profile_form, "password_form": password_form},
    )


@login_required
def transaction_list(request):
    """Halaman Transaksi: riwayat booking sewa milik user yang login."""
    from rentals.models import RentalOrder

    orders = (
        RentalOrder.objects.filter(user=request.user)
        .prefetch_related("items__product")
        .order_by("-created_at")
    )
    return render(
        request,
        "accounts/transaction.html",
        {"orders": orders},
    )
