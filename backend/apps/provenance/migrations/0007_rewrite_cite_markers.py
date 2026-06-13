"""Rewrite stored inline cite markers ``[[cite:N]]`` → ``[[cite:id:N]]``.

Coupled to the registry flip that makes ``cite`` a public-id wikilink type: once
``cite`` is public-id, render reads the ``[[cite:id:N]]`` *storage* pattern, so any
un-migrated bare-digit marker would stop resolving. The pk ``N`` is unchanged (it
is the storage id); slugs never appear in storage.

Surface covered, kept self-consistent so a future revert re-materializes valid
storage: every markdown field on every catalog entity (the materialized column
``render_markdown_field`` reads), plus every ``Claim.value`` for a markdown field.

The ``(app_label, model_name, field_name)`` list is **frozen** here, not derived
at runtime: ``MarkdownField.deconstruct()`` serializes as a plain ``TextField``,
so the historical models a data migration sees carry no ``MarkdownField``
instances and ``get_markdown_fields`` would return nothing. A unit test asserts
this frozen list still equals the live markdown-field set so it can't drift.
"""

from __future__ import annotations

import re

from django.db import migrations

# Frozen snapshot of the live markdown fields (see module docstring + the
# drift-guard test in apps/provenance/tests). Currently every markdown field is
# a ``description``; the test fails loudly if a new one is added without updating
# this list.
MARKDOWN_FIELDS: tuple[tuple[str, str, str], ...] = (
    ("catalog", "Cabinet", "description"),
    ("catalog", "CorporateEntity", "description"),
    ("catalog", "CreditRole", "description"),
    ("catalog", "DisplaySubtype", "description"),
    ("catalog", "DisplayType", "description"),
    ("catalog", "Franchise", "description"),
    ("catalog", "GameFormat", "description"),
    ("catalog", "GameplayFeature", "description"),
    ("catalog", "Location", "description"),
    ("catalog", "MachineModel", "description"),
    ("catalog", "Manufacturer", "description"),
    ("catalog", "Person", "description"),
    ("catalog", "ProductionStatus", "description"),
    ("catalog", "RewardType", "description"),
    ("catalog", "Series", "description"),
    ("catalog", "System", "description"),
    ("catalog", "Tag", "description"),
    ("catalog", "TechnologyGeneration", "description"),
    ("catalog", "TechnologySubgeneration", "description"),
    ("catalog", "Theme", "description"),
    ("catalog", "Title", "description"),
)

_FORWARD_RE = re.compile(r"\[\[cite:(\d+)\]\]")
_REVERSE_RE = re.compile(r"\[\[cite:id:(\d+)\]\]")


def _rewrite(apps, pattern: re.Pattern[str], repl: str) -> None:
    # Entity markdown columns.
    for app_label, model_name, field in MARKDOWN_FIELDS:
        model = apps.get_model(app_label, model_name)
        changed = []
        for obj in model.objects.filter(**{f"{field}__contains": "[[cite:"}):
            text = getattr(obj, field)
            new = pattern.sub(repl, text)
            if new != text:
                setattr(obj, field, new)
                changed.append(obj)
        if changed:
            model.objects.bulk_update(changed, [field])

    # Claim values for markdown fields. Claim.value is a JSONField; a markdown
    # claim stores the text as a JSON string. No portable JSON substring filter,
    # so scan all claims for the markdown field names (a bounded set).
    field_names = {field for _, _, field in MARKDOWN_FIELDS}
    Claim = apps.get_model("provenance", "Claim")
    changed_claims = []
    for claim in Claim.objects.filter(field_name__in=field_names):
        value = claim.value
        if not isinstance(value, str):
            continue
        new = pattern.sub(repl, value)
        if new != value:
            claim.value = new
            changed_claims.append(claim)
    if changed_claims:
        Claim.objects.bulk_update(changed_claims, ["value"])


def _forward(apps, schema_editor):
    _rewrite(apps, _FORWARD_RE, r"[[cite:id:\1]]")


def _reverse(apps, schema_editor):
    _rewrite(apps, _REVERSE_RE, r"[[cite:\1]]")


class Migration(migrations.Migration):
    dependencies = [
        ("provenance", "0006_citationinstance_slug"),
        # Catalog entity tables must exist before we rewrite their columns.
        ("catalog", "0012_corporateentity_operating_status_and_more"),
    ]

    operations = [
        migrations.RunPython(_forward, _reverse),
    ]
