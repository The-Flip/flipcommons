"""Seed the patch-attribution Source(s).

Add a new source for patches: ``flip-museum`` — museum-curated
facts (e.g. the prototype list). It sits at the user tier (priority 10000)
so its facts resolve as peer edits (newest-wins, re-breakable).

Corrections to existing data are *not* an override tier: a patch attributes
to the source that erred (``flipcommons-catalog``, ``ipdb``, ``opdb``, …,
already seeded by the ingest) and supersedes or retracts that source's own
claim. So no editorial override source is seeded here.

Sources are infra-ish, so auto-creating on ``migrate`` is fine: it makes the
apply command's "error if attribution missing" check meaningful (the rows
exist after deploy). Idempotent via ``update_or_create``.
"""

from __future__ import annotations

from django.db import migrations

# Default user priority (apps.accounts Profile.priority). Patches resolve as
# peer edits at this tier — a deliberate "peer curation, not authoritative
# override" tradeoff.
USER_TIER_PRIORITY = 10000

PATCH_SOURCES = [
    {
        "slug": "flip-museum",
        "name": "The Flip Museum",
        "description": "Pinball facts curated by The Flip museum.",
    },
]


def seed_patch_sources(apps, schema_editor):
    Source = apps.get_model("provenance", "Source")
    for spec in PATCH_SOURCES:
        Source.objects.update_or_create(
            slug=spec["slug"],
            defaults={
                "name": spec["name"],
                "description": spec["description"],
                "source_type": "editorial",
                "priority": USER_TIER_PRIORITY,
            },
        )


def unseed_patch_sources(apps, schema_editor):
    Source = apps.get_model("provenance", "Source")
    Source.objects.filter(
        slug__in=[spec["slug"] for spec in PATCH_SOURCES]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("provenance", "0003_ingestrun_patch_fields"),
    ]

    operations = [
        migrations.RunPython(seed_patch_sources, unseed_patch_sources),
    ]
