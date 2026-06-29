"""Backfill: attribute legacy unattributed citation rows to the catalog source.

The pre-fix ingest path created citation sources/links/recognition domains
without recording attribution (the bug this series fixes), leaving
``created_by``/``updated_by`` null. The interactive path always set a user
(carried to an Actor by 0009), so a remaining null ``created_by`` means the row
was created by the baseline seed ingest — which is the ``flipcommons-catalog``
source. Attribute those rows to its Actor, matching how the fixed ingest path
now stamps freshly-created rows.

The forward fails fast if any null attribution remains afterward (it is the
precursor to enforcing the column ``NOT NULL``), so a drifted DB surfaces the
gap here with context rather than at the later schema-tightening step.

The reverse clears *source*-backed citation attribution (nulls it). It must: a
rollback below ``provenance.0012`` runs that migration's reverse, which deletes
every source-backed ``Actor`` — and ``created_by``/``updated_by`` are
``PROTECT``, so any citation row still pointing at a source actor would block
the delete. Only ``0011`` depends on ``provenance.0012`` (the expand/contract
steps don't), so this reverse is the one place guaranteed to run first and drop
those references. User-backed attribution is left alone — it's torn down by the
``0009``/``0008`` reverses, which the ``accounts.0004`` dependency orders ahead
of the user-actor delete.
"""

from __future__ import annotations

from django.db import migrations
from django.db.models import Q

_MODELS = ["CitationSource", "CitationSourceLink", "CitationSourceRootDomain"]
_CATALOG_SOURCE_SLUG = "flipcommons-catalog"


def _forward(apps, schema_editor):
    Source = apps.get_model("provenance", "Source")
    catalog = Source.objects.filter(slug=_CATALOG_SOURCE_SLUG).first()
    if catalog is not None:
        actor_id = catalog.actor_id
        for model_name in _MODELS:
            model = apps.get_model("citation", model_name)
            model.objects.filter(created_by__isnull=True).update(created_by_id=actor_id)
            model.objects.filter(updated_by__isnull=True).update(updated_by_id=actor_id)

    # Fail fast: this is the precursor to a NOT NULL constraint, so a remaining
    # null (a null row with no flipcommons-catalog source to claim it — a drifted
    # DB) must surface here, not at the later tightening with less context.
    for model_name in _MODELS:
        model = apps.get_model("citation", model_name)
        if model.objects.filter(
            Q(created_by__isnull=True) | Q(updated_by__isnull=True)
        ).exists():
            raise RuntimeError(
                f"{model_name}: null editorial attribution remains after the "
                f"backfill — no {_CATALOG_SOURCE_SLUG!r} source to attribute it to, "
                "or unexpected null rows. Resolve before tightening to NOT NULL."
            )


def _reverse(apps, schema_editor):
    # Drop references to source-backed actors so a rollback below provenance.0012
    # (which deletes those actors) isn't blocked by the PROTECT FKs. See the
    # module docstring.
    for model_name in _MODELS:
        model = apps.get_model("citation", model_name)
        model.objects.filter(created_by__backing_model="source").update(created_by=None)
        model.objects.filter(updated_by__backing_model="source").update(updated_by=None)


class Migration(migrations.Migration):
    dependencies = [
        ("citation", "0010_contract_attribution_actor_fks"),
        # Reads Source.actor_id, added + minted in provenance 0012.
        ("provenance", "0012_source_actor_and_changeset_claim_actor"),
    ]

    operations = [
        migrations.RunPython(_forward, _reverse),
    ]
