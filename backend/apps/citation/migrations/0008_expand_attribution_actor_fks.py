"""Expand: add the actor-backed editorial-attribution columns.

Editorial attribution (``created_by`` / ``updated_by`` on the citation-source
family) moves from a FK to ``User`` to a FK to ``Actor`` — the same durable
attribution anchor the claims/provenance system points at, so a data patch's
``Source`` can attribute the citation rows it creates (its `sources:` block).

Staged expand → backfill → contract, because a FK can't be retargeted to a
different table in place without reinterpreting the stored ids. This first step
adds the new ``*_actor`` columns nullable alongside the legacy User columns; the
backfill copies each user's actor across, and the contract step drops the old
columns and renames the new ones into place. Hand-authored — letting
``makemigrations`` diff the final model state would emit a single unsafe
``AlterField`` that recasts User ids as Actor ids.
"""

from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("citation", "0007_citationsourcerootdomain_created_by_and_more"),
        # The new columns FK to actors.Actor, so its table must exist.
        ("actors", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="citationsource",
            name="created_by_actor",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="actors.actor",
            ),
        ),
        migrations.AddField(
            model_name="citationsource",
            name="updated_by_actor",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="actors.actor",
            ),
        ),
        migrations.AddField(
            model_name="citationsourcelink",
            name="created_by_actor",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="actors.actor",
            ),
        ),
        migrations.AddField(
            model_name="citationsourcelink",
            name="updated_by_actor",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="actors.actor",
            ),
        ),
        migrations.AddField(
            model_name="citationsourcerootdomain",
            name="created_by_actor",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="actors.actor",
            ),
        ),
        migrations.AddField(
            model_name="citationsourcerootdomain",
            name="updated_by_actor",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="+",
                to="actors.actor",
            ),
        ),
    ]
