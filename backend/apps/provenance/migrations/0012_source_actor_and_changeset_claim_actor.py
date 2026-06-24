"""Add Source.actor (minted, NOT NULL) and nullable ChangeSet.actor / Claim.actor.

Source.actor is staged like accounts.0004 (AddField nullable -> mint+link ->
AlterField NOT NULL), copying ``priority`` and mapping ``is_enabled`` ->
``resolution_status``. ChangeSet.actor / Claim.actor are added nullable and
stay that way — a later PR ("Backfill actor FKs") populates them. Nothing reads
them yet.

Depends only on ``actors.0001`` and the provenance chain.
"""

from __future__ import annotations

import django.db.models.deletion
from django.apps.registry import Apps
from django.db import migrations, models, transaction
from django.db.backends.base.schema import BaseDatabaseSchemaEditor


def mint_source_actors(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Source = apps.get_model("provenance", "Source")
    Actor = apps.get_model("actors", "Actor")
    with transaction.atomic():
        for source in Source.objects.all().iterator():
            actor = Actor.objects.create(
                backing_model="source",
                priority=source.priority,
                resolution_status="active" if source.is_enabled else "suppressed",
            )
            Source.objects.filter(pk=source.pk).update(actor=actor)


def unlink_source_actors(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    Source = apps.get_model("provenance", "Source")
    Actor = apps.get_model("actors", "Actor")
    with transaction.atomic():
        Source.objects.update(actor=None)
        Actor.objects.filter(backing_model="source").delete()


class Migration(migrations.Migration):
    # Non-atomic so the staged schema ops (AddField / AlterField, DDL) and the
    # RunPython backfill (DML) run in separate transactions. On Postgres a single
    # transaction mixing them fails the reverse with "pending trigger events"
    # when ALTERing a table that the same transaction just modified rows on.
    atomic = False

    dependencies = [
        ("provenance", "0011_backfill_seed_changesets"),
        ("actors", "0001_initial"),
    ]

    operations = [
        # --- Source.actor: minted, then tightened to NOT NULL ---
        migrations.AddField(
            model_name="source",
            name="actor",
            field=models.OneToOneField(
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="%(class)s",
                to="actors.actor",
            ),
        ),
        migrations.RunPython(mint_source_actors, unlink_source_actors),
        migrations.AlterField(
            model_name="source",
            name="actor",
            field=models.OneToOneField(
                editable=False,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="%(class)s",
                to="actors.actor",
            ),
        ),
        # --- ChangeSet.actor / Claim.actor: nullable, populated by a later PR ---
        migrations.AddField(
            model_name="changeset",
            name="actor",
            field=models.ForeignKey(
                blank=True,
                help_text="The actor this changeset is attributed to.",
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="changesets",
                to="actors.actor",
            ),
        ),
        migrations.AddField(
            model_name="claim",
            name="actor",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="claims",
                to="actors.actor",
            ),
        ),
    ]
