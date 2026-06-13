"""Add the author-stable ``CitationInstance.slug``.

Three-step pattern: add the column nullable, backfill a unique slug onto every
existing row (bypassing the immutable ``save()`` via ``bulk_update``), then
tighten to NOT NULL + unique. See the inline-citations plan for why ``cite``
becomes a public-id wikilink type keyed on this slug.
"""

from __future__ import annotations

from django.db import migrations, models
from django.utils.crypto import get_random_string

# Kept in sync with apps.provenance.models.citation_instance. Inlined (not
# imported) so the migration stays self-contained against future app changes.
_SLUG_ALPHABET = "bcdfghjklmnpqrstvwxyz"
_SLUG_LENGTH = 8


def _backfill_slugs(apps, schema_editor):
    CitationInstance = apps.get_model("provenance", "CitationInstance")
    rows = list(CitationInstance.objects.all().only("pk"))
    seen: set[str] = set()
    for row in rows:
        slug = get_random_string(_SLUG_LENGTH, _SLUG_ALPHABET)
        while slug in seen:
            slug = get_random_string(_SLUG_LENGTH, _SLUG_ALPHABET)
        seen.add(slug)
        row.slug = slug
    if rows:
        CitationInstance.objects.bulk_update(rows, ["slug"])


def _noop_reverse(apps, schema_editor):
    # Reversing the AlterField below drops back to nullable; the column itself
    # is removed by reversing AddField. Nothing to undo for the data step.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("provenance", "0005_ingestrun_citation_source_counts"),
    ]

    operations = [
        migrations.AddField(
            model_name="citationinstance",
            name="slug",
            field=models.CharField(max_length=_SLUG_LENGTH, null=True),
        ),
        migrations.RunPython(_backfill_slugs, _noop_reverse),
        migrations.AlterField(
            model_name="citationinstance",
            name="slug",
            field=models.CharField(max_length=_SLUG_LENGTH, unique=True),
        ),
    ]
