"""Rename the stored claim field names for the model date rename.

``0031`` renamed the columns ``year``/``month`` to ``production_year``/
``production_month``, but claims address fields by name: every existing claim
row carries ``field_name="year"`` (or ``"month"``), and for a scalar claim
``claim_key`` equals the field name. Left alone, those rows would stop
resolving into the renamed columns and new claims would compete in a
different slot — the exact drift ``0026`` documents.

Both ``field_name`` and ``claim_key`` move together (the provenance ``0027``
CHECK constraint enforces the pairing). Nothing else on the rows changes, so
their ingest/user attribution carries over — no new ChangeSet is needed.

Scoped to MachineModel's content type: field names are per content type, and
only MachineModel's ``year``/``month`` were renamed.
"""

from __future__ import annotations

from django.db import migrations

_RENAMES = {
    "year": "production_year",
    "month": "production_month",
}


def _rename(apps, mapping):
    Claim = apps.get_model("provenance", "Claim")
    ContentType = apps.get_model("contenttypes", "ContentType")
    ct = ContentType.objects.filter(app_label="catalog", model="machinemodel").first()
    if ct is None:
        # Fresh database: no content type row means no claims to rewrite.
        return
    for old, new in mapping.items():
        Claim.objects.filter(content_type=ct, field_name=old).update(
            field_name=new, claim_key=new
        )


def rename_date_claims(apps, schema_editor):
    _rename(apps, _RENAMES)


def unrename_date_claims(apps, schema_editor):
    _rename(apps, {new: old for old, new in _RENAMES.items()})


class Migration(migrations.Migration):
    dependencies = [
        ("catalog", "0032_model_project_date"),
        ("provenance", "0027_repair_drifted_claim_keys"),
        ("contenttypes", "0002_remove_content_type_name"),
    ]

    operations = [
        migrations.RunPython(rename_date_claims, unrename_date_claims),
    ]
