"""Tighten: make editorial attribution non-null.

Every write path now stamps an actor (interactive API/admin -> user.actor,
ingest -> source.actor) and 0011 attributed the legacy seed-ingest rows to the
flipcommons-catalog source, so no null ``created_by``/``updated_by`` remain.
Enforce that at the schema level — a citation row must record its author.

Hand-authored: ``makemigrations`` prompts for a one-off default on the
nullable -> non-null change, which 0011 has already made unnecessary; this is
the plain ``AlterField`` it would otherwise emit.
"""

from __future__ import annotations

import django.db.models.deletion
from django.db import migrations, models


def _non_null_actor_fk():
    return models.ForeignKey(
        on_delete=django.db.models.deletion.PROTECT,
        related_name="+",
        to="actors.actor",
    )


class Migration(migrations.Migration):
    dependencies = [
        ("citation", "0011_attribute_seed_citation_sources"),
    ]

    operations = [
        migrations.AlterField(
            model_name=model,
            name=field,
            field=_non_null_actor_fk(),
        )
        for model in ("citationsource", "citationsourcelink", "citationsourcerootdomain")
        for field in ("created_by", "updated_by")
    ]
