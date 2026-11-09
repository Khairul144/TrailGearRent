"""Sistem role TrailGear berbasis Django Groups.

Tiga role utama: Customer, Cashier, Admin.

Sengaja TIDAK memakai flag boolean (is_customer/is_cashier/is_admin) pada
model User supaya:
- role tetap satu mekanisme dengan permission Django (groups + permissions);
- user bisa punya permission tambahan tanpa mengubah skema;
- penambahan role baru tidak butuh migration.

Satu user normalnya punya satu role utama; `primary_role()` memilih role
dengan prioritas Admin > Cashier > Customer.
"""

from django.contrib.auth.models import Group

ROLE_CUSTOMER = "Customer"
ROLE_CASHIER = "Cashier"
ROLE_ADMIN = "Admin"

ALL_ROLES = (ROLE_CUSTOMER, ROLE_CASHIER, ROLE_ADMIN)

# Prioritas saat user punya lebih dari satu group.
_ROLE_PRIORITY = {ROLE_ADMIN: 0, ROLE_CASHIER: 1, ROLE_CUSTOMER: 2}


def ensure_roles():
    """Buat group role bila belum ada (idempotent). Dipakai migration & command."""
    groups = {}
    for name in ALL_ROLES:
        groups[name], _ = Group.objects.get_or_create(name=name)
    return groups


def user_role_names(user):
    if not user or not user.is_authenticated:
        return set()
    return set(user.groups.values_list("name", flat=True)) & set(ALL_ROLES)


def primary_role(user):
    """Nama role utama user, atau None bila belum punya role."""
    names = user_role_names(user)
    if not names:
        return None
    return sorted(names, key=lambda n: _ROLE_PRIORITY.get(n, 99))[0]


def has_role(user, *roles):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return bool(user_role_names(user) & set(roles))


def assign_role(user, role_name, exclusive=True):
    """Set role utama user.

    exclusive=True  -> role lain dicabut (default: satu user satu role)
    exclusive=False -> role ditambahkan tanpa mencabut role lain
    """
    if role_name not in ALL_ROLES:
        raise ValueError(f"Role tidak dikenal: {role_name!r}")

    group, _ = Group.objects.get_or_create(name=role_name)
    if exclusive:
        user.groups.remove(*Group.objects.filter(name__in=ALL_ROLES).exclude(pk=group.pk))
    user.groups.add(group)
    return group
