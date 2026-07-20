"""Promote ``extra_data['ipdb.model_number']`` to the new
``MachineModel.manufacturer_model_identifier`` column.

The value is the *manufacturer's* own model identifier, which IPDB happens to
record; it was ingested under the field name ``ipdb.model_number``, which
matched no column, so the resolver parked it in ``extra_data``. Now that a
dedicated column exists, two rewrites make the promotion complete:

1. Claims: rename ``field_name`` from ``ipdb.model_number`` to
   ``manufacturer_model_identifier``. The claim rows themselves are untouched
   otherwise, so their IPDB ingest attribution (actor → source → IngestRun)
   carries over — no new ChangeSet is needed or wanted.
2. Materialized rows: copy the parked value into the column and drop the
   ``extra_data`` key, mirroring exactly what the next resolve would produce
   (a claim whose field name matches a column resolves into the column, not
   ``extra_data``). Doing it here means the value displays immediately after
   deploy instead of after each entity happens to re-resolve.
"""

from __future__ import annotations

from django.db import migrations

_OLD_FIELD_NAME = "ipdb.model_number"
_NEW_FIELD_NAME = "manufacturer_model_identifier"
_BATCH_SIZE = 1000


def promote_model_number(apps, schema_editor):
    Claim = apps.get_model("provenance", "Claim")
    MachineModel = apps.get_model("catalog", "MachineModel")

    Claim.objects.filter(field_name=_OLD_FIELD_NAME).update(field_name=_NEW_FIELD_NAME)

    changed = []
    for pm in MachineModel.objects.filter(extra_data__has_key=_OLD_FIELD_NAME):
        value = pm.extra_data.pop(_OLD_FIELD_NAME)
        # Parked values are plain strings; anything else (or blank) is not a
        # usable identifier, so drop the key but leave the column NULL.
        if isinstance(value, str) and value.strip():
            pm.manufacturer_model_identifier = value
        changed.append(pm)

    MachineModel.objects.bulk_update(
        changed,
        ["manufacturer_model_identifier", "extra_data"],
        batch_size=_BATCH_SIZE,
    )


def demote_model_number(apps, schema_editor):
    """Reverse: park the value back under the old field name so the state
    matches what the pre-migration resolver produced."""
    Claim = apps.get_model("provenance", "Claim")
    MachineModel = apps.get_model("catalog", "MachineModel")

    Claim.objects.filter(field_name=_NEW_FIELD_NAME).update(field_name=_OLD_FIELD_NAME)

    changed = []
    for pm in MachineModel.objects.filter(manufacturer_model_identifier__isnull=False):
        pm.extra_data[_OLD_FIELD_NAME] = pm.manufacturer_model_identifier
        pm.manufacturer_model_identifier = None
        changed.append(pm)

    MachineModel.objects.bulk_update(
        changed,
        ["manufacturer_model_identifier", "extra_data"],
        batch_size=_BATCH_SIZE,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0025_machinemodel_manufacturer_model_identifier_and_more"),
        ("provenance", "0026_fk_claim_values_to_pk"),
    ]

    operations = [
        migrations.RunPython(promote_model_number, demote_model_number),
    ]
