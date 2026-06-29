"""Backfill: project each legacy User attribution to that user's Actor.

Pure FK projection across an existing join — no row creation — so it is a
set-based ``update()`` with ``Subquery``, not a per-row loop. Every ``User`` has
a non-null ``Actor`` (the user→actor FK is mandatory), so a non-null
``created_by``/``updated_by`` always resolves to a non-null ``actor_id``; null
attribution (an unattributed extractor-created row, or a row predating
attribution) stays null.

Pure DML with no schema ops, so the default ``atomic=True`` is correct — one
all-or-nothing transaction. (``atomic=False`` is only needed when a migration
mixes DDL ``AlterField`` with DML in a single file.)
"""

from __future__ import annotations

from django.db import migrations
from django.db.models import OuterRef, Subquery

_MODELS = ["CitationSource", "CitationSourceLink", "CitationSourceRootDomain"]


def _forward(apps, schema_editor):
    User = apps.get_model("accounts", "User")
    for model_name in _MODELS:
        model = apps.get_model("citation", model_name)
        model.objects.filter(created_by__isnull=False).update(
            created_by_actor_id=Subquery(
                User.objects.filter(pk=OuterRef("created_by_id")).values("actor_id")[:1]
            )
        )
        model.objects.filter(updated_by__isnull=False).update(
            updated_by_actor_id=Subquery(
                User.objects.filter(pk=OuterRef("updated_by_id")).values("actor_id")[:1]
            )
        )


def _reverse(apps, schema_editor):
    """Project actor attribution back onto the legacy User columns.

    On a full rollback the contract step is reversed first, re-adding the
    *empty* legacy ``created_by``/``updated_by`` User columns and renaming the
    actor columns back to ``*_actor``. So the actor columns hold the only copy
    of the attribution here; map each back to its backing user. A source-backed
    or orphaned actor (no user) leaves the legacy column null — the legacy
    User-FK schema cannot represent non-user attribution.
    """
    User = apps.get_model("accounts", "User")
    for model_name in _MODELS:
        model = apps.get_model("citation", model_name)
        model.objects.filter(created_by_actor__isnull=False).update(
            created_by_id=Subquery(
                User.objects.filter(actor_id=OuterRef("created_by_actor_id")).values(
                    "pk"
                )[:1]
            )
        )
        model.objects.filter(updated_by_actor__isnull=False).update(
            updated_by_id=Subquery(
                User.objects.filter(actor_id=OuterRef("updated_by_actor_id")).values(
                    "pk"
                )[:1]
            )
        )


class Migration(migrations.Migration):
    dependencies = [
        ("citation", "0008_expand_attribution_actor_fks"),
        # The projection reads User.actor_id, added in accounts 0004 — not
        # transitive via 0008, so name it explicitly.
        ("accounts", "0004_user_actor"),
    ]

    operations = [
        migrations.RunPython(_forward, _reverse),
    ]
