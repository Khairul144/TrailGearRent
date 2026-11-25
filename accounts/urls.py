"""Routing aplikasi accounts TrailGear."""

from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("login/", views.login_view, name="login"),
    path("register/", views.register, name="register"),
    path("logout/", views.logout_view, name="logout"),
    path("dashboard/admin/", views.admin_dashboard, name="admin_dashboard"),
    path("dashboard/admin/users/", views.admin_users, name="admin_users"),
    path("dashboard/admin/users/add/", views.admin_user_add, name="admin_user_add"),
    path(
        "dashboard/admin/users/<int:user_id>/manage/",
        views.admin_user_manage,
        name="admin_user_manage",
    ),
    path("dashboard/admin/staff/", views.admin_staff, name="admin_staff"),
    path(
        "dashboard/admin/users/<int:user_id>/toggle/",
        views.admin_user_toggle,
        name="admin_user_toggle",
    ),
    path("dashboard/admin/products/", views.admin_products, name="admin_products"),
    path("dashboard/admin/products/add/", views.admin_product_form, name="admin_product_add"),
    path(
        "dashboard/admin/products/<int:product_id>/edit/",
        views.admin_product_form,
        name="admin_product_edit",
    ),
    path(
        "dashboard/admin/products/<int:product_id>/stock/",
        views.admin_product_stock,
        name="admin_product_stock",
    ),
    path("dashboard/admin/categories/", views.admin_categories, name="admin_categories"),
    path(
        "dashboard/admin/categories/<int:cat_id>/edit/",
        views.admin_categories,
        name="admin_category_edit",
    ),
    path(
        "dashboard/admin/inventory-logs/",
        views.admin_inventory_logs,
        name="admin_inventory_logs",
    ),
    path("dashboard/admin/rentals/", views.admin_rentals, name="admin_rentals"),
    path("dashboard/admin/payments/", views.admin_payments, name="admin_payments"),
    path("dashboard/admin/security/", views.admin_security, name="admin_security"),
    path(
        "dashboard/admin/security/reset-ratelimit/",
        views.admin_reset_ratelimit,
        name="admin_reset_ratelimit",
    ),
    path("dashboard/admin/reports/", views.admin_reports, name="admin_reports"),
    path(
        "dashboard/admin/settings/",
        views.admin_profile_settings,
        name="admin_profile_settings",
    ),
    path("dashboard/cashier/", views.cashier_dashboard, name="cashier_dashboard"),
    path(
        "dashboard/cashier/customers/",
        views.cashier_customers,
        name="cashier_customers",
    ),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("settings/", views.settings_view, name="settings"),
    path("transaction/", views.transaction_list, name="transaction_list"),
    path("account/password/", views.password_change, name="password_change"),
]
