"""Buat tiga role utama sebagai Django Group (idempotent).

Role disimpan sebagai Group (bukan boolean pada User) supaya permission
Django bisa dipakai langsung: groups + permissions.
"""

from django.db import migrations

ROLES = ["Customer", "Cashier", "Admin"]


def create_roles(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    for name in ROLES:
        Group.objects.get_or_create(name=name)


def delete_roles(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.filter(name__in=ROLES).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_user_address"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.RunPython(create_roles, delete_roles),
    ]
