"""Mint a synthetic "seed" IngestRun per baseline source.

The initial data seed (``flipcommons-catalog``, the ``ai-desc-*`` sources,
``web-scrape``, …) wrote ~104K source-attributed claims with no ``ChangeSet``
and no ``IngestRun`` — they predate that machinery. Those claims were all
written within seconds of each other, so each source's seed claims are
conceptually one ingest run.

The next PR ("Backfill changesets") will give those claims ChangeSets, but a
source-attributed ChangeSet needs an ``ingest_run`` to satisfy the
``provenance_changeset_user_xor_ingest_run`` CHECK. This migration mints the
anchor runs those ChangeSets will point at — one per baseline source that has
changeset-less claims. Scope here is ONLY creating ``IngestRun`` rows; no
claims or changesets are touched. Migration 0009 did the user-attributed half
and deferred this source half here.

The source set is derived dynamically from the claims that actually lack a
changeset — the ``ai-desc-*`` / ``web-scrape`` slugs live only in the baseline
data export, never in code, so enumerating them would be fragile.

``input_fingerprint = "seed-backfill:<slug>"`` is a migration-owned, reserved
sentinel. No other code path writes it. It is (a) the get_or_create idempotency
key, (b) what the reverse deletes, and (c) the cross-PR handoff contract: the
next PR finds the synthetic anchor among a source's runs via
``input_fingerprint__startswith="seed-backfill:"`` (catalog will have ~49 runs;
exactly one is this synthetic anchor).
"""

from __future__ import annotations

from django.db import migrations
from django.db.models import Count, Max, Min

SEED_FINGERPRINT_PREFIX = "seed-backfill:"

NOTE = (
    "Synthetic seed IngestRun backfilled to anchor source-attributed claims "
    "that predate the ChangeSet/IngestRun machinery."
)


def _forward(apps, schema_editor):
    Claim = apps.get_model("provenance", "Claim")
    Source = apps.get_model("provenance", "Source")
    IngestRun = apps.get_model("provenance", "IngestRun")

    orphans = Claim.objects.filter(user__isnull=True, changeset__isnull=True)
    # source XOR user means source is set whenever user is null; drop any None
    # defensively rather than minting an orphan run.
    source_ids = [
        s for s in orphans.values_list("source_id", flat=True).distinct() if s
    ]
    # Fetch only slugs (the one field we need) in one query — avoids an N+1 and
    # any unrelated columns a drifted dev DB might be missing.
    slugs = dict(Source.objects.filter(pk__in=source_ids).values_list("pk", "slug"))
    for source_id in source_ids:
        stats = orphans.filter(source_id=source_id).aggregate(
            n=Count("pk"), ts_min=Min("created_at"), ts_max=Max("created_at")
        )
        run, created = IngestRun.objects.get_or_create(
            source_id=source_id,
            input_fingerprint=f"{SEED_FINGERPRINT_PREFIX}{slugs[source_id]}",
            defaults={
                # String literal, not IngestRun.Status.SUCCESS: historical
                # models carry fields but not nested TextChoices classes.
                "status": "success",
                "finished_at": stats["ts_max"],
                "claims_asserted": stats["n"],
                "note": NOTE,
            },
        )
        if created:
            # started_at is auto_now_add (stamped "now" on insert); realign to
            # the earliest seed claim so the run spans first-to-last claim.
            IngestRun.objects.filter(pk=run.pk).update(started_at=stats["ts_min"])


def _reverse(apps, schema_editor):
    IngestRun = apps.get_model("provenance", "IngestRun")
    IngestRun.objects.filter(
        input_fingerprint__startswith=SEED_FINGERPRINT_PREFIX
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("provenance", "0009_backfill_user_claim_changesets"),
    ]

    operations = [
        migrations.RunPython(_forward, _reverse),
    ]
