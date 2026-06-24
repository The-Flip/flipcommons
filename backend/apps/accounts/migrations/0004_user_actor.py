"""Add User.actor: mint an Actor per existing User, link, then tighten to NOT NULL.

Staged the standard way for a non-null FK with a data backfill: AddField
nullable -> RunPython mint+link -> AlterField NOT NULL. The model declares
``actor`` non-null; this migration's end state matches it.

Depends only on ``actors.0001`` and the accounts chain — never on provenance.
"""

from __future__ import annotations

import django.db.models.deletion
from django.apps.registry import Apps
from django.db import migrations, models, transaction
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def mint_user_actors(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    User = apps.get_model("accounts", "User")
    Actor = apps.get_model("actors", "Actor")
    with transaction.atomic():
        for user in User.objects.all().iterator():
            actor = Actor.objects.create(
                backing_model="user",
                priority=user.priority,
                resolution_status="active",
            )
            User.objects.filter(pk=user.pk).update(actor=actor)


def unlink_user_actors(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    User = apps.get_model("accounts", "User")
    Actor = apps.get_model("actors", "Actor")
    with transaction.atomic():
        User.objects.update(actor=None)
        Actor.objects.filter(backing_model="user").delete()


class Migration(migrations.Migration):
    # Non-atomic so the staged schema ops (AddField / AlterField, DDL) and the
    # RunPython backfill (DML) run in separate transactions. On Postgres a single
    # transaction mixing them fails the reverse with "pending trigger events"
    # when ALTERing a table that the same transaction just modified rows on.
    atomic = False

    dependencies = [
        ("accounts", "0003_alter_user_username"),
        ("actors", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="actor",
            field=models.OneToOneField(
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="%(class)s",
                to="actors.actor",
            ),
        ),
        migrations.RunPython(mint_user_actors, unlink_user_actors),
        migrations.AlterField(
            model_name="user",
            name="actor",
            field=models.OneToOneField(
                editable=False,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="%(class)s",
                to="actors.actor",
            ),
        ),
    ]
