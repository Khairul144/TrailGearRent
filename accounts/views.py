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


def _csv_safe(value) -> str:
    """Cegah CSV / Formula Injection saat ekspor dibuka di Excel/LibreOffice."""
    text = str(value if value is not None else "").replace("\r", " ").replace("\n", " ")
    if text and text[0] in ("=", "+", "-", "@", "\t"):
        return "'" + text
    return text


def _safe_redirect_target(request, default_route: str):
    """Validasi parameter `next` agar bebas kerentanan Open Redirect."""
    nxt = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if _is_safe_next(request, nxt):
        return nxt
    return default_route


def _admin_counts() -> dict:
    """Angka badge sidebar admin."""
    from datetime import timedelta
    from django.utils import timezone
    from catalog.models import Category, Product
    from rentals.models import RentalOrder

    orders = RentalOrder.objects.all()
    total_staff = (
        User.objects.filter(groups__name__in=[ROLE_CASHIER, ROLE_ADMIN])
        .distinct()
        .count()
    )
    seven_days_ago = timezone.now() - timedelta(days=7)
    return {
        "badge_open_orders": orders.exclude(
            status__in=[RentalOrder.Status.KEMBALI, RentalOrder.Status.DIBATALKAN]
        ).count(),
        "badge_pending_payment": orders.filter(
            status=RentalOrder.Status.MENUNGGU_PEMBAYARAN
        ).count(),
        "badge_security": SecurityEvent.objects.exclude(
            status=SecurityEvent.STATUS_SUCCESS
        )
        .filter(timestamp__gte=seven_days_ago)
        .count(),
        "badge_users": User.objects.count(),
        "badge_staff": total_staff,
        "badge_products": Product.objects.count(),
        "badge_categories": Category.objects.count(),
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

    paid_rental_revenue = (
        RentalOrder.objects.filter(
            status__in=[
                RentalOrder.Status.DIKONFIRMASI,
                RentalOrder.Status.DIAMBIL,
                RentalOrder.Status.KEMBALI,
            ]
        ).aggregate(total=Sum("total_rental_fee"))["total"]
        or 0
    )
    paid_fine_revenue = (
        RentalOrder.objects.filter(
            fine_payment_status=RentalOrder.FinePaymentStatus.LUNAS
        ).aggregate(total=Sum("total_fine"))["total"]
        or 0
    )
    revenue = paid_rental_revenue + paid_fine_revenue

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
    """Daftar akun staff (kasir & admin) beserta metrik operasional riil tanpa N+1."""
    staff = (
        User.objects.filter(groups__name__in=[ROLE_CASHIER, ROLE_ADMIN])
        .prefetch_related("groups")
        .annotate(returned_count=Count("processed_returns", distinct=True))
        .distinct()
        .order_by("username")
    )
    rows = list(staff)
    approved_map = dict(
        SecurityEvent.objects.filter(
            event_type=SecurityEvent.ORDER_APPROVED,
            user__in=rows,
        )
        .values_list("user_id")
        .annotate(cnt=Count("id"))
    )
    for item in rows:
        item.role_name = primary_role(item) or "—"
        item.approved_count = approved_map.get(item.pk, 0)
        item.order_count = item.returned_count + item.approved_count

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
def admin_user_add(request):
    """Tambah akun baru (Customer / Cashier / Admin) langsung dari Dashboard Admin."""
    from .roles import ALL_ROLES, ensure_roles

    ensure_roles()
    default_role = request.GET.get("role")
    if default_role not in ALL_ROLES:
        default_role = ROLE_CUSTOMER

    selected_role = request.POST.get("role") if request.method == "POST" else default_role
    if selected_role not in ALL_ROLES:
        selected_role = ROLE_CUSTOMER

    form = RegistrationForm(request.POST or None)
    error = None

    if request.method == "POST":
        if form.is_valid():
            new_user = form.save(commit=True)
            assign_role(new_user, selected_role, exclusive=True)
            new_user.is_staff = selected_role == ROLE_ADMIN
            new_user.save(update_fields=["is_staff"])
            log_event(
                request,
                SecurityEvent.REGISTER_SUCCESS,
                SecurityEvent.STATUS_SUCCESS,
                user=new_user,
                description=(
                    f"created_by_admin={request.user.pk} "
                    f"new_user={new_user.pk} role={selected_role}"
                ),
            )
            messages.success(
                request,
                f"Akun @{new_user.username} dengan role {selected_role} berhasil dibuat.",
            )
            if selected_role in (ROLE_ADMIN, ROLE_CASHIER):
                return redirect("accounts:admin_staff")
            return redirect("accounts:admin_users")
        error = _first_error_message(form) or "Data belum valid. Periksa kembali input Anda."

    return _admin_render(
        request,
        "accounts/admin/user_add.html",
        "staff" if selected_role in (ROLE_ADMIN, ROLE_CASHIER) else "users",
        {
            "form": form,
            "error": error,
            "selected_role": selected_role,
            "role_choices": [
                (ROLE_CUSTOMER, "Customer (Pelanggan)"),
                (ROLE_CASHIER, "Cashier (Kasir Operasional)"),
                (ROLE_ADMIN, "Admin (Administrator)"),
            ],
        },
    )


@role_required(ROLE_ADMIN)
def admin_user_manage(request, user_id):
    """Kelola akun user/staff (profil, ganti role, buka lockout, reset password)."""
    from django.contrib.auth import password_validation
    from django.core.exceptions import ValidationError
    from django.shortcuts import get_object_or_404
    from .roles import ALL_ROLES, ensure_roles

    ensure_roles()
    target = get_object_or_404(User, pk=user_id)
    current_role = primary_role(target) or ROLE_CUSTOMER
    profile_form = ProfileForm(instance=target)

    if request.method == "POST":
        action = request.POST.get("action") or "profile_role"

        if action == "unlock":
            target.failed_login_attempts = 0
            target.locked_until = None
            target.save(update_fields=["failed_login_attempts", "locked_until"])
            ip_candidates = list(
                SecurityEvent.objects.filter(user=target)
                .exclude(ip_address__isnull=True)
                .values_list("ip_address", flat=True)
                .distinct()[:10]
            )
            for ip in set(ip_candidates + ["127.0.0.1"]):
                ratelimit.reset_ip(ip, [target.username, target.email])
            log_event(
                request,
                SecurityEvent.ADMIN_SECURITY_OVERRIDE,
                SecurityEvent.STATUS_SUCCESS,
                user=request.user,
                description=(
                    f"action=unlock_user target_user={target.pk} "
                    f"target_username={target.username}"
                ),
            )
            messages.success(
                request,
                f"Kunci akun @{target.username} telah dibuka dan counter gagal login direset.",
            )
            return redirect("accounts:admin_user_manage", user_id=target.pk)

        if action == "reset_password":
            new_pw = request.POST.get("new_password") or ""
            confirm_pw = request.POST.get("new_password_confirmation") or ""
            if not new_pw:
                messages.error(request, "Password baru wajib diisi.")
            elif new_pw != confirm_pw:
                messages.error(request, "Konfirmasi password baru tidak cocok.")
            else:
                try:
                    password_validation.validate_password(new_pw, target)
                except ValidationError as exc:
                    messages.error(request, exc.messages[0])
                else:
                    target.set_password(new_pw)
                    target.failed_login_attempts = 0
                    target.locked_until = None
                    target.save(
                        update_fields=[
                            "password",
                            "password_changed_at",
                            "failed_login_attempts",
                            "locked_until",
                        ]
                    )
                    log_event(
                        request,
                        SecurityEvent.PASSWORD_CHANGED,
                        SecurityEvent.STATUS_SUCCESS,
                        user=target,
                        description=f"reset_by_admin={request.user.pk} target={target.pk}",
                    )
                    messages.success(
                        request, f"Password untuk @{target.username} berhasil diperbarui."
                    )
                    return redirect("accounts:admin_user_manage", user_id=target.pk)

        elif action == "profile_role":
            profile_form = ProfileForm(request.POST, instance=target)
            new_role = request.POST.get("role") or current_role
            want_active = request.POST.get("is_active") == "1"

            if new_role not in ALL_ROLES:
                messages.error(request, "Role tidak valid.")
            elif target.pk == request.user.pk and not want_active:
                messages.error(request, "Anda tidak dapat menonaktifkan akun sendiri.")
            elif target.pk == request.user.pk and new_role != ROLE_ADMIN:
                messages.error(request, "Anda tidak dapat menurunkan role Admin akun sendiri.")
            elif profile_form.is_valid():
                old_role = current_role
                old_active = target.is_active
                user_obj = profile_form.save(commit=False)
                user_obj.is_active = want_active
                if not user_obj.is_superuser:
                    user_obj.is_staff = new_role == ROLE_ADMIN
                user_obj.save()
                assign_role(user_obj, new_role, exclusive=True)
                log_event(
                    request,
                    SecurityEvent.ADMIN_USER_UPDATED,
                    SecurityEvent.STATUS_SUCCESS,
                    user=request.user,
                    description=(
                        f"action=profile_role target_user={user_obj.pk} "
                        f"role={old_role}->{new_role} "
                        f"active={old_active}->{want_active}"
                    ),
                )
                messages.success(
                    request,
                    f"Data & role akun @{user_obj.username} ({new_role}) berhasil disimpan.",
                )
                return redirect("accounts:admin_user_manage", user_id=target.pk)
            else:
                messages.error(
                    request,
                    _first_error_message(profile_form)
                    or "Gagal menyimpan perubahan. Periksa input Anda.",
                )

    current_role = primary_role(target) or ROLE_CUSTOMER
    return _admin_render(
        request,
        "accounts/admin/user_manage.html",
        "staff" if current_role in (ROLE_ADMIN, ROLE_CASHIER) else "users",
        {
            "target": target,
            "current_role": current_role,
            "profile_form": profile_form,
            "role_choices": [
                (ROLE_CUSTOMER, "Customer (Pelanggan)"),
                (ROLE_CASHIER, "Cashier (Kasir Operasional)"),
                (ROLE_ADMIN, "Admin (Administrator)"),
            ],
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
        log_event(
            request,
            SecurityEvent.ADMIN_USER_UPDATED,
            SecurityEvent.STATUS_SUCCESS,
            user=request.user,
            description=(
                f"action=toggle_active target_user={target.pk} "
                f"target_username={target.username} is_active={target.is_active}"
            ),
        )
        messages.success(
            request,
            f"Akun {target.username} {'diaktifkan' if target.is_active else 'dinonaktifkan'}.",
        )
    return redirect(_safe_redirect_target(request, "accounts:admin_users"))


@role_required(ROLE_ADMIN)
def admin_products(request):
    """Daftar barang + stok, filter kategori, status & pencarian."""
    from catalog.models import Category, Product

    query = (request.GET.get("q") or "").strip()[:80]
    cat_slug = request.GET.get("cat") or ""
    stock_filter = request.GET.get("stok") or ""
    status_filter = request.GET.get("status") or ""

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
    if status_filter == "active":
        products = products.filter(is_active=True)
    elif status_filter == "inactive":
        products = products.filter(is_active=False)

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
            "status_filter": status_filter,
            "total_products": Product.objects.count(),
            "total_inactive": Product.objects.filter(is_active=False).count(),
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
def admin_product_form(request, product_id=None):
    """Tambah atau Edit Barang langsung dari Dashboard Admin (mencatat InventoryLog & SecurityEvent)."""
    from django.db import transaction
    from django.shortcuts import get_object_or_404
    from catalog.forms import ProductForm
    from catalog.models import InventoryLog, Product

    instance = get_object_or_404(Product, pk=product_id) if product_id else None
    old_available = instance.available_stock if instance else 0

    if request.method == "POST":
        form = ProductForm(request.POST, request.FILES, instance=instance)
        if form.is_valid():
            with transaction.atomic():
                obj = form.save()
                if instance is None:
                    if obj.available_stock > 0:
                        InventoryLog.objects.create(
                            product=obj,
                            changed_by=request.user,
                            action=InventoryLog.Action.RESTOCK,
                            quantity_change=obj.available_stock,
                            stock_before=0,
                            stock_after=obj.available_stock,
                            notes="Barang baru ditambahkan melalui Dashboard Admin",
                        )
                    log_event(
                        request,
                        SecurityEvent.ADMIN_CATALOG_UPDATED,
                        SecurityEvent.STATUS_SUCCESS,
                        user=request.user,
                        description=(
                            f"action=add_product product_id={obj.pk} "
                            f"slug={obj.slug} stock={obj.available_stock}/{obj.total_stock}"
                        ),
                    )
                    messages.success(request, f"Barang '{obj.name}' berhasil ditambahkan.")
                else:
                    if obj.available_stock != old_available:
                        delta = obj.available_stock - old_available
                        InventoryLog.objects.create(
                            product=obj,
                            changed_by=request.user,
                            action=(
                                InventoryLog.Action.RESTOCK
                                if delta > 0
                                else InventoryLog.Action.ADJUSTMENT
                            ),
                            quantity_change=delta,
                            stock_before=old_available,
                            stock_after=obj.available_stock,
                            notes="Pembaruan data barang melalui Dashboard Admin",
                        )
                    log_event(
                        request,
                        SecurityEvent.ADMIN_CATALOG_UPDATED,
                        SecurityEvent.STATUS_SUCCESS,
                        user=request.user,
                        description=(
                            f"action=edit_product product_id={obj.pk} "
                            f"stock={old_available}->{obj.available_stock}/{obj.total_stock} "
                            f"active={obj.is_active}"
                        ),
                    )
                    messages.success(request, f"Perubahan barang '{obj.name}' berhasil disimpan.")
            return redirect("accounts:admin_products")
        messages.error(
            request,
            _first_error_message(form) or "Data barang belum valid. Periksa input Anda.",
        )
    else:
        form = ProductForm(
            instance=instance,
            initial={"is_active": True, "total_stock": 1, "available_stock": 1}
            if instance is None
            else None,
        )

    recent_logs = (
        instance.inventory_logs.select_related("changed_by").order_by("-created_at")[:10]
        if instance
        else []
    )
    return _admin_render(
        request,
        "accounts/admin/product_form.html",
        "products",
        {
            "form": form,
            "product": instance,
            "is_edit": instance is not None,
            "recent_logs": recent_logs,
        },
    )


@role_required(ROLE_ADMIN)
def admin_product_stock(request, product_id):
    """Penyesuaian stok cepat (Restock / Rusak / Opname) secara atomik + wajib catatan audit."""
    from django.db import transaction
    from django.shortcuts import get_object_or_404
    from catalog.forms import StockAdjustmentForm
    from catalog.models import InventoryLog, Product

    product = get_object_or_404(Product.objects.select_related("category"), pk=product_id)
    form = StockAdjustmentForm(request.POST or None)

    if request.method == "POST":
        if form.is_valid():
            act = form.cleaned_data["action"]
            qty = form.cleaned_data["quantity"]
            notes = form.cleaned_data["notes"]

            with transaction.atomic():
                locked = Product.objects.select_for_update().get(pk=product.pk)
                before_avail = locked.available_stock
                before_total = locked.total_stock

                if act == InventoryLog.Action.RESTOCK:
                    after_avail = before_avail + qty
                    after_total = before_total + qty
                    delta = qty
                elif act == InventoryLog.Action.DAMAGED:
                    if qty > before_avail:
                        messages.error(
                            request,
                            f"Jumlah unit rusak ({qty}) melebihi stok tersedia saat ini ({before_avail}).",
                        )
                        return redirect("accounts:admin_product_stock", product_id=product.pk)
                    after_avail = before_avail - qty
                    after_total = before_total
                    delta = -qty
                else:
                    # ADJUSTMENT (stok opname: set available_stock langsung)
                    if qty > before_total:
                        after_total = qty
                    else:
                        after_total = before_total
                    after_avail = qty
                    delta = after_avail - before_avail

                locked.available_stock = after_avail
                locked.total_stock = after_total
                locked.save(update_fields=["available_stock", "total_stock", "updated_at"])

                InventoryLog.objects.create(
                    product=locked,
                    changed_by=request.user,
                    action=act,
                    quantity_change=delta,
                    stock_before=before_avail,
                    stock_after=after_avail,
                    notes=notes,
                )
                log_event(
                    request,
                    SecurityEvent.ADMIN_CATALOG_UPDATED,
                    SecurityEvent.STATUS_SUCCESS,
                    user=request.user,
                    description=(
                        f"action=stock_adjust mode={act} product_id={locked.pk} "
                        f"avail={before_avail}->{after_avail} total={before_total}->{after_total} "
                        f"note={notes[:80]!r}"
                    ),
                )
                messages.success(
                    request,
                    f"Stok '{locked.name}' diperbarui ({before_avail} → {after_avail} tersedia).",
                )
                return redirect(_safe_redirect_target(request, "accounts:admin_products"))
        else:
            messages.error(
                request,
                _first_error_message(form) or "Input penyesuaian stok tidak valid.",
            )

    logs = product.inventory_logs.select_related("changed_by").order_by("-created_at")[:15]
    return _admin_render(
        request,
        "accounts/admin/product_stock.html",
        "products",
        {
            "product": product,
            "form": form,
            "logs": logs,
        },
    )


@role_required(ROLE_ADMIN)
def admin_categories(request, cat_id=None):
    """Kelola daftar kategori & tambah/edit kategori langsung dari Dashboard Admin."""
    from django.shortcuts import get_object_or_404
    from catalog.forms import CategoryForm
    from catalog.models import Category

    editing = get_object_or_404(Category, pk=cat_id) if cat_id else None

    if request.method == "POST":
        form = CategoryForm(request.POST, instance=editing)
        if form.is_valid():
            cat = form.save()
            log_event(
                request,
                SecurityEvent.ADMIN_CATALOG_UPDATED,
                SecurityEvent.STATUS_SUCCESS,
                user=request.user,
                description=(
                    f"action={'edit_category' if editing else 'add_category'} "
                    f"category_id={cat.pk} slug={cat.slug} active={cat.is_active}"
                ),
            )
            messages.success(
                request,
                f"Kategori '{cat.name}' berhasil {'diperbarui' if editing else 'ditambahkan'}.",
            )
            return redirect("accounts:admin_categories")
        messages.error(
            request,
            _first_error_message(form) or "Data kategori belum valid.",
        )
    else:
        form = CategoryForm(
            instance=editing,
            initial={"is_active": True, "show_in_menu": True, "order": 0}
            if editing is None
            else None,
        )

    categories = Category.objects.annotate(product_count=Count("products")).order_by(
        "order", "name"
    )
    return _admin_render(
        request,
        "accounts/admin/categories.html",
        "categories",
        {
            "categories": categories,
            "form": form,
            "editing": editing,
            "total_categories": categories.count(),
        },
    )


@role_required(ROLE_ADMIN)
def admin_inventory_logs(request):
    """Riwayat audit mutasi stok (`InventoryLog`) lengkap dengan filter & pencarian."""
    from catalog.models import InventoryLog

    query = (request.GET.get("q") or "").strip()[:80]
    action_filter = request.GET.get("action") or ""
    valid_actions = dict(InventoryLog.Action.choices)

    logs = InventoryLog.objects.select_related("product", "changed_by").order_by(
        "-created_at"
    )
    if action_filter in valid_actions:
        logs = logs.filter(action=action_filter)
    else:
        action_filter = ""
    if query:
        logs = logs.filter(
            Q(product__name__icontains=query)
            | Q(notes__icontains=query)
            | Q(changed_by__username__icontains=query)
        )

    paginator = Paginator(logs, 25)
    page_obj = paginator.get_page(request.GET.get("page"))

    return _admin_render(
        request,
        "accounts/admin/inventory_logs.html",
        "inventory_logs",
        {
            "page_obj": page_obj,
            "logs": page_obj.object_list,
            "query": query,
            "action_filter": action_filter,
            "action_choices": InventoryLog.Action.choices,
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
                "confirmed": RentalOrder.objects.filter(
                    status=RentalOrder.Status.DIKONFIRMASI
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
    """Pembayaran yang menunggu verifikasi kasir/admin + filter struk, metode, pencarian & paginasi."""
    from rentals.models import RentalOrder, rupiah

    query = (request.GET.get("q") or "").strip()[:80]
    proof_filter = request.GET.get("proof") or ""
    method_filter = request.GET.get("method") or ""
    valid_methods = dict(RentalOrder.PaymentMethod.choices)

    base_pending = RentalOrder.objects.filter(
        status=RentalOrder.Status.MENUNGGU_PEMBAYARAN
    )
    pending_count = base_pending.count()
    pending_with_proof = base_pending.exclude(payment_proof="").exclude(
        payment_proof__isnull=True
    ).count()
    pending_total = base_pending.aggregate(total=Sum("grand_total"))["total"] or 0

    qs = base_pending.select_related("user").prefetch_related("items__product")
    if query:
        qs = qs.filter(
            Q(order_code__icontains=query)
            | Q(full_name__icontains=query)
            | Q(phone_number__icontains=query)
        )
    if proof_filter == "yes":
        qs = qs.exclude(payment_proof="").exclude(payment_proof__isnull=True)
    elif proof_filter == "no":
        qs = qs.filter(Q(payment_proof="") | Q(payment_proof__isnull=True))
    else:
        proof_filter = ""

    if method_filter in valid_methods:
        qs = qs.filter(payment_method=method_filter)
    else:
        method_filter = ""

    paginator = Paginator(qs.order_by("created_at"), ADMIN_PAGE_SIZE)
    page_obj = paginator.get_page(request.GET.get("page"))

    return _admin_render(
        request,
        "accounts/admin/payments.html",
        "payments",
        {
            "page_obj": page_obj,
            "open_orders": page_obj.object_list,
            "pending_count": pending_count,
            "pending_with_proof": pending_with_proof,
            "pending_total": pending_total,
            "pending_total_fmt": rupiah(pending_total),
            "query": query,
            "proof_filter": proof_filter,
            "method_filter": method_filter,
            "payment_methods": RentalOrder.PaymentMethod.choices,
            "page_range": paginator.get_elided_page_range(
                page_obj.number, on_each_side=1, on_ends=1
            ),
        },
    )


def _build_user_access_review():
    """Susun data User Access Review (UAR) untuk akun aplikasi & role DBMS."""
    from django.db import connection
    from django.utils import timezone

    app_rows = []
    for u in User.objects.prefetch_related("groups").order_by("username"):
        rname = primary_role(u) or "Tanpa Role"
        if rname == ROLE_ADMIN:
            priv_desc = "Full Admin Dashboard, Manajemen User/Katalog/Laporan"
        elif rname == ROLE_CASHIER:
            priv_desc = "Operasional Kasir (Verifikasi, Serah Terima, Inspeksi Kembali)"
        elif rname == ROLE_CUSTOMER:
            priv_desc = "Pelanggan (Katalog, Keranjang, Checkout & Pesanan Milik Sendiri)"
        else:
            priv_desc = "Tidak ada privilege role"

        if not u.is_active:
            finding = "Akun Nonaktif"
            rec = "REVOKE / PERTAHANKAN NONAKTIF"
            badge = "cancelled"
        elif u.is_locked:
            finding = "Akun Terkunci (Lockout)"
            rec = "INVESTIGASI PERCOBAAN LOGIN"
            badge = "rejected"
        elif u.password_expired:
            finding = "Password Kedaluwarsa"
            rec = "WAJIB ROTASI PASSWORD"
            badge = "pending"
        elif rname == "Tanpa Role":
            finding = "Belum Memiliki Group Role"
            rec = "TETAPKAN ROLE / REVOKE"
            badge = "pending"
        elif rname in (ROLE_CUSTOMER, ROLE_CASHIER) and (u.is_staff or u.is_superuser):
            finding = "Privilege Berlebih (is_staff/superuser pada non-Admin)"
            rec = "DOWNGRADE PRIVILEGE (Cabut is_staff)"
            badge = "rejected"
        else:
            finding = "Sesuai Least Privilege"
            rec = "MAINTAIN (Pertahankan Akses)"
            badge = "active"

        app_rows.append(
            {
                "user": u,
                "role_name": rname,
                "privilege_summary": priv_desc,
                "finding": finding,
                "recommendation": rec,
                "badge": badge,
            }
        )

    db_rows = []
    db_audit_config = {}
    try:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT rolname, rolsuper, rolcreaterole, rolcreatedb, "
                "rolcanlogin, rolvaliduntil "
                "FROM pg_roles WHERE rolname NOT LIKE 'pg_%' ORDER BY rolname"
            )
            now_ts = timezone.now()
            for (
                rolname,
                rolsuper,
                rolcreaterole,
                rolcreatedb,
                rolcanlogin,
                rolvaliduntil,
            ) in cur.fetchall():
                expired = bool(rolvaliduntil and rolvaliduntil <= now_ts)
                if rolsuper:
                    finding = "Superuser DBMS (Hanya untuk DBA)"
                    rec = "BATASI HANYA ADMINISTRATOR"
                    badge = "pending"
                elif expired and rolcanlogin:
                    finding = "Masa Berlaku Habis namun LOGIN Masih Aktif"
                    rec = "REVOKE LOGIN (ALTER ROLE ... NOLOGIN)"
                    badge = "rejected"
                elif expired and not rolcanlogin:
                    finding = "Akun Uji Kedaluwarsa (Login Dicabut)"
                    rec = "REVOKE / NONAKTIF TERKENDALI"
                    badge = "cancelled"
                else:
                    finding = "Sesuai Skema Least Privilege"
                    rec = "MAINTAIN (Pertahankan)"
                    badge = "active"
                db_rows.append(
                    {
                        "rolname": rolname,
                        "rolsuper": rolsuper,
                        "rolcreaterole": rolcreaterole,
                        "rolcreatedb": rolcreatedb,
                        "rolcanlogin": rolcanlogin,
                        "rolvaliduntil": rolvaliduntil,
                        "finding": finding,
                        "recommendation": rec,
                        "badge": badge,
                    }
                )
            for param in (
                "log_statement",
                "log_connections",
                "log_disconnections",
                "logging_collector",
            ):
                cur.execute(f"SHOW {param}")
                row = cur.fetchone()
                db_audit_config[param] = row[0] if row else "—"
    except Exception:
        pass

    return app_rows, db_rows, db_audit_config


@role_required(ROLE_ADMIN)
def admin_security(request):
    """Log keamanan lengkap dengan filter + pencarian + ekspor CSV + Kontrol Buka Blokir + UAR."""
    import csv
    from datetime import timedelta
    from django.http import HttpResponse
    from django.utils import timezone

    status_filter = request.GET.get("status") or ""
    type_filter = request.GET.get("event") or ""
    period_filter = request.GET.get("period") or ""
    query = (request.GET.get("q") or "").strip()[:80]

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

    now = timezone.now()
    if period_filter == "24h":
        events = events.filter(timestamp__gte=now - timedelta(hours=24))
    elif period_filter == "7d":
        events = events.filter(timestamp__gte=now - timedelta(days=7))
    elif period_filter == "30d":
        events = events.filter(timestamp__gte=now - timedelta(days=30))
    else:
        period_filter = ""

    if query:
        events = events.filter(
            Q(ip_address__icontains=query)
            | Q(user__username__icontains=query)
            | Q(description__icontains=query)
        )

    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="trailgear_security_events_{timezone.localdate():%Y%m%d}.csv"'
        )
        response["X-Content-Type-Options"] = "nosniff"
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow(["Waktu (WIB)", "Event", "Status", "Username", "IP", "Keterangan"])
        for e in events[:2000]:
            local_ts = timezone.localtime(e.timestamp).strftime("%Y-%m-%d %H:%M:%S")
            writer.writerow(
                [
                    _csv_safe(local_ts),
                    _csv_safe(e.event_type),
                    _csv_safe(e.status),
                    _csv_safe(e.user.username if e.user else ""),
                    _csv_safe(e.ip_address or ""),
                    _csv_safe(e.description or ""),
                ]
            )
        return response

    paginator = Paginator(events, 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    uar_app_rows, uar_db_rows, db_audit_config = _build_user_access_review()

    # Kumpulkan daftar IP dari event terbaru + IP lokal untuk memantau status rate-limit
    recent_ips = list(
        SecurityEvent.objects.exclude(ip_address__isnull=True)
        .values_list("ip_address", flat=True)
        .order_by("-timestamp")[:50]
    )
    candidate_ips = []
    for ip in ["127.0.0.1", ratelimit.client_ip(request)] + recent_ips:
        if ip and ip not in candidate_ips:
            candidate_ips.append(ip)

    rate_limit_rows = [ratelimit.ip_status(ip) for ip in candidate_ips[:12]]
    locked_users = list(
        User.objects.filter(
            Q(failed_login_attempts__gt=0) | Q(locked_until__gt=timezone.now())
        ).order_by("-failed_login_attempts", "username")
    )

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
            "period_filter": period_filter,
            "query": query,
            "rate_limit_rows": rate_limit_rows,
            "locked_users": locked_users,
            "uar_app_rows": uar_app_rows,
            "uar_db_rows": uar_db_rows,
            "db_audit_config": db_audit_config,
            "page_range": paginator.get_elided_page_range(
                page_obj.number, on_each_side=1, on_ends=1
            ),
        },
    )


@role_required(ROLE_ADMIN)
@require_http_methods(["POST"])
def admin_reset_ratelimit(request):
    """Buka blokir / reset rate limit IP atau buka kunci akun langsung dari web."""
    import ipaddress

    mode = (request.POST.get("mode") or "").strip()
    ip = (request.POST.get("ip") or "").strip()
    unlock_user_id = (request.POST.get("unlock_user_id") or "").strip()

    if mode == "all":
        ratelimit.reset_all()
        log_event(
            request,
            SecurityEvent.ADMIN_SECURITY_OVERRIDE,
            SecurityEvent.STATUS_SUCCESS,
            user=request.user,
            description="action=reset_ratelimit_all",
        )
        messages.success(
            request,
            "Seluruh cache rate limit (registrasi & login semua IP) berhasil direset.",
        )
    elif unlock_user_id.isdigit():
        target = User.objects.filter(pk=int(unlock_user_id)).first()
        if target:
            target.failed_login_attempts = 0
            target.locked_until = None
            target.save(update_fields=["failed_login_attempts", "locked_until"])
            ip_candidates = list(
                SecurityEvent.objects.filter(user=target)
                .exclude(ip_address__isnull=True)
                .values_list("ip_address", flat=True)
                .distinct()[:10]
            )
            for cand_ip in set(ip_candidates + ["127.0.0.1", ratelimit.client_ip(request)]):
                if cand_ip:
                    ratelimit.reset_ip(cand_ip, [target.username, target.email])
            log_event(
                request,
                SecurityEvent.ADMIN_SECURITY_OVERRIDE,
                SecurityEvent.STATUS_SUCCESS,
                user=request.user,
                description=(
                    f"action=unlock_user target_user={target.pk} "
                    f"target_username={target.username}"
                ),
            )
            messages.success(
                request,
                f"Kunci akun @{target.username} telah dibuka & rate limit seluruh IP terkait direset.",
            )
        else:
            messages.error(request, "Akun tidak ditemukan.")
    elif ip:
        try:
            clean_ip = str(ipaddress.ip_address(ip))
        except ValueError:
            messages.error(request, "Format alamat IP tidak valid.")
            return redirect("accounts:admin_security")
        identifiers = list(User.objects.values_list("username", flat=True)) + list(
            User.objects.values_list("email", flat=True)
        )
        ratelimit.reset_ip(clean_ip, identifiers)
        log_event(
            request,
            SecurityEvent.ADMIN_SECURITY_OVERRIDE,
            SecurityEvent.STATUS_SUCCESS,
            user=request.user,
            description=f"action=reset_ratelimit_ip target_ip={clean_ip}",
        )
        messages.success(
            request,
            f"Rate limit (registrasi & login) untuk IP {clean_ip} berhasil dihapus.",
        )
    else:
        messages.error(request, "Masukkan alamat IP atau pilih aksi reset.")

    return redirect("accounts:admin_security")


@role_required(ROLE_ADMIN)
def admin_reports(request):
    """Laporan pendapatan sewa & denda, filter periode, produk terlaris & ekspor CSV."""
    import csv
    from datetime import datetime, timedelta
    from django.http import HttpResponse
    from django.utils import timezone
    from catalog.models import Product
    from rentals.models import RentalOrder, RentalOrderItem, rupiah

    period = (request.GET.get("period") or "all").strip()
    raw_start = (request.GET.get("start") or "").strip()
    raw_end = (request.GET.get("end") or "").strip()
    today = timezone.localdate()

    start_date = None
    end_date = None
    if period == "today":
        start_date = today
        end_date = today
    elif period == "7d":
        start_date = today - timedelta(days=6)
        end_date = today
    elif period == "30d":
        start_date = today - timedelta(days=29)
        end_date = today
    elif period == "month":
        start_date = today.replace(day=1)
        end_date = today
    elif period == "custom":
        try:
            if raw_start:
                start_date = datetime.strptime(raw_start, "%Y-%m-%d").date()
            if raw_end:
                end_date = datetime.strptime(raw_end, "%Y-%m-%d").date()
            if start_date and end_date and start_date > end_date:
                start_date, end_date = end_date, start_date
        except ValueError:
            start_date = None
            end_date = None
    else:
        period = "all"

    orders_qs = RentalOrder.objects.all()
    if start_date:
        orders_qs = orders_qs.filter(created_at__date__gte=start_date)
    if end_date:
        orders_qs = orders_qs.filter(created_at__date__lte=end_date)

    if request.GET.get("export") == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            f'attachment; filename="trailgear_laporan_sewa_{today:%Y%m%d}.csv"'
        )
        response["X-Content-Type-Options"] = "nosniff"
        response.write("\ufeff")
        writer = csv.writer(response)
        writer.writerow(
            [
                "Kode Booking",
                "Waktu Dibuat",
                "Penyewa",
                "Username",
                "Telepon",
                "Tanggal Ambil",
                "Rencana Kembali",
                "Status",
                "Metode Bayar",
                "Biaya Sewa (Rp)",
                "Total Denda (Rp)",
                "Status Denda",
            ]
        )
        for o in orders_qs.select_related("user").order_by("-created_at")[:5000]:
            writer.writerow(
                [
                    _csv_safe(o.order_code),
                    _csv_safe(timezone.localtime(o.created_at).strftime("%Y-%m-%d %H:%M")),
                    _csv_safe(o.full_name),
                    _csv_safe(o.user.username if o.user_id else ""),
                    _csv_safe(o.phone_number),
                    _csv_safe(o.pickup_plan_date.isoformat()),
                    _csv_safe(o.return_plan_date.isoformat()),
                    _csv_safe(o.get_status_display()),
                    _csv_safe(o.get_payment_method_display()),
                    o.total_rental_fee,
                    o.total_fine,
                    _csv_safe(o.get_fine_payment_status_display()),
                ]
            )
        return response

    paid_statuses = [
        RentalOrder.Status.DIKONFIRMASI,
        RentalOrder.Status.DIAMBIL,
        RentalOrder.Status.KEMBALI,
    ]
    rental_revenue = (
        orders_qs.filter(status__in=paid_statuses).aggregate(
            rental=Sum("total_rental_fee")
        )["rental"]
        or 0
    )
    fine_paid = (
        orders_qs.filter(
            fine_payment_status=RentalOrder.FinePaymentStatus.LUNAS
        ).aggregate(total=Sum("total_fine"))["total"]
        or 0
    )
    fine_unpaid = (
        orders_qs.filter(
            fine_payment_status=RentalOrder.FinePaymentStatus.MENUNGGU_PEMBAYARAN
        ).aggregate(total=Sum("total_fine"))["total"]
        or 0
    )
    revenue = rental_revenue + fine_paid

    by_status = (
        orders_qs.values("status")
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

    item_qs = RentalOrderItem.objects.filter(order__in=orders_qs, order__status__in=paid_statuses)
    top_products = [
        {
            "name": row["product__name"],
            "unit": row["unit"],
            "nilai": row["nilai"] or 0,
            "nilai_fmt": rupiah(row["nilai"] or 0),
        }
        for row in item_qs.values("product__name")
        .annotate(unit=Sum("quantity"), nilai=Sum("subtotal"))
        .order_by("-unit")[:8]
    ]

    return _admin_render(
        request,
        "accounts/admin/reports.html",
        "reports",
        {
            "revenue": revenue,
            "revenue_fmt": rupiah(revenue),
            "rental_revenue_fmt": rupiah(rental_revenue),
            "fine_paid": fine_paid,
            "fine_paid_fmt": rupiah(fine_paid),
            "fine_unpaid": fine_unpaid,
            "fine_unpaid_fmt": rupiah(fine_unpaid),
            "order_count": orders_qs.count(),
            "status_rows": status_rows,
            "top_products": top_products,
            "total_products": Product.objects.filter(is_active=True).count(),
            "period": period,
            "start_val": start_date.isoformat() if start_date else "",
            "end_val": end_date.isoformat() if end_date else "",
        },
    )


@role_required(ROLE_ADMIN)
@never_cache
def admin_profile_settings(request):
    """Pengaturan profil & ubah password khusus Admin tetap di dalam layout Dashboard Admin."""
    profile_form = ProfileForm(instance=request.user)
    password_form = PasswordChangeForm(request.user)

    if request.method == "POST":
        form_type = request.POST.get("form_type", "profile")
        if form_type == "password":
            password_form = PasswordChangeForm(request.user, request.POST)
            if password_form.is_valid():
                request.user.set_password(password_form.cleaned_data["new_password"])
                request.user.save(update_fields=["password", "password_changed_at"])
                update_session_auth_hash(request, request.user)
                log_event(
                    request,
                    SecurityEvent.PASSWORD_CHANGED,
                    SecurityEvent.STATUS_SUCCESS,
                    user=request.user,
                    description=f"user_id={request.user.pk} (via pengaturan admin)",
                )
                messages.success(request, "Password akun Admin berhasil diubah.")
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
                log_event(
                    request,
                    SecurityEvent.ADMIN_USER_UPDATED,
                    SecurityEvent.STATUS_SUCCESS,
                    user=request.user,
                    description=f"action=self_profile_update user_id={request.user.pk}",
                )
                messages.success(request, "Profil Admin berhasil diperbarui.")
                profile_form = ProfileForm(instance=request.user)
            else:
                messages.error(
                    request,
                    _first_error_message(profile_form)
                    or "Perubahan profil gagal disimpan.",
                )

    return _admin_render(
        request,
        "accounts/admin/profile_settings.html",
        "settings",
        {"profile_form": profile_form, "password_form": password_form},
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


@role_required(ROLE_CASHIER, ROLE_ADMIN)
def cashier_customers(request):
    """Daftar pelanggan penyewa + riwayat kepatuhan (khusus kasir/admin)."""
    from django.db.models import Prefetch
    from django.db.models import Count as DjCount

    from rentals.models import RentalOrder

    query = (request.GET.get("q") or "").strip()[:80]
    tab = request.GET.get("tab") or "all"

    order_qs = RentalOrder.objects.select_related("user").order_by("-created_at")
    customers = User.objects.filter(rental_orders__isnull=False)

    if query:
        customers = customers.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
            | Q(phone_number__icontains=query)
            | Q(rental_orders__full_name__icontains=query)
            | Q(rental_orders__id_card_number__icontains=query)
            | Q(rental_orders__phone_number__icontains=query)
            | Q(rental_orders__order_code__icontains=query)
        ).distinct()

    if tab == "active":
        customers = customers.filter(
            rental_orders__status=RentalOrder.Status.DIAMBIL
        ).distinct()
    elif tab == "overdue":
        customers = customers.filter(rental_orders__overdue_days__gt=0).distinct()

    customers = customers.annotate(
        fine_total=DjCount("rental_orders", filter=Q(rental_orders__total_fine__gt=0))
    ).prefetch_related(
        Prefetch("rental_orders", queryset=order_qs, to_attr="order_history")
    ).order_by("username")

    rows = []
    for customer in customers:
        history = customer.order_history
        latest = history[0] if history else None
        rows.append(
            {
                "user": customer,
                "latest": latest,
                "nik": latest.id_card_number if latest else "—",
                "phone": (latest.phone_number if latest else "")
                or getattr(customer, "phone_number", "")
                or "—",
                "total_done": len(
                    [o for o in history if o.status == RentalOrder.Status.KEMBALI]
                ),
                "active_count": len(
                    [o for o in history if o.status == RentalOrder.Status.DIAMBIL]
                ),
                "overdue_count": len([o for o in history if o.overdue_days > 0]),
                "history": history,
            }
        )

    return render(
        request,
        "accounts/cashier_customers.html",
        {
            "role": primary_role(request.user),
            "rows": rows,
            "query": query,
            "tab": tab,
            "total_customers": len(rows),
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
