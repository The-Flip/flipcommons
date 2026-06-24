"""Give the source-attributed seed claims their ChangeSets.

The initial data seed wrote ~104K source-attributed claims with no ``ChangeSet``
— they predate that machinery. Migration 0009 backfilled the user-attributed
half; 0010 minted one synthetic "seed" ``IngestRun`` per baseline source (the
anchor a source ChangeSet needs to satisfy the user-XOR-ingest_run CHECK). This
migration creates the ChangeSets themselves and links every changeset-less seed
claim to one, completing the "every claim belongs to a ChangeSet" milestone that
the later Actor work depends on.

Grouping rule (from docs/plans/auth/Actors.md): one ChangeSet per (record,
source) — every changeset-less claim on a given record from a given source
collapses into a single ChangeSet pointing at that source's seed run, timestamped
to the earliest claim in the group. Inactive/superseded seed claims ride along in
the same group: collapsing a historical assert+supersede into one synthetic
ChangeSet is a benign fiction (the seed carries no edit-boundary data to split
them), and every claim still gets the ChangeSet it needs.

The seed run for a source is found via ``input_fingerprint__startswith=
"seed-backfill:"`` — the cross-PR handoff contract 0010 defines. Reverse detaches
and deletes exactly the ChangeSets attached to those synthetic runs; it relies on
0011 being the only writer of ChangeSets onto seed runs (true by construction —
the live ingest path mints its own non-seed runs).
"""

from __future__ import annotations

from datetime import datetime
from typing import NamedTuple

from django.db import migrations

SEED_FINGERPRINT_PREFIX = "seed-backfill:"

SEED_NOTE = "Seed import (backfilled)."


class _Group(NamedTuple):
    """The (record, source) identity that defines one synthetic ChangeSet."""

    content_type_id: int
    object_id: int
    source_id: int


def _forward(apps, schema_editor):
    Claim = apps.get_model("provenance", "Claim")
    ChangeSet = apps.get_model("provenance", "ChangeSet")
    IngestRun = apps.get_model("provenance", "IngestRun")

    # The seed runs 0010 minted: the contract is exactly one synthetic anchor
    # per source. A duplicate (0010 drift, a slug change minting a second run, a
    # hand-created row) makes the anchor ambiguous — refuse rather than pick one.
    seed_run_by_source: dict[int, int] = {}
    for source_id, run_id in IngestRun.objects.filter(
        input_fingerprint__startswith=SEED_FINGERPRINT_PREFIX
    ).values_list("source_id", "pk"):
        if source_id in seed_run_by_source:
            raise RuntimeError(
                f"Source {source_id} has multiple {SEED_FINGERPRINT_PREFIX!r} "
                "IngestRuns; the synthetic anchor must be exactly one per source."
            )
        seed_run_by_source[source_id] = run_id

    # Group changeset-less source claims by (record, source). Hold pk tuples,
    # not model instances — there are ~104K rows.
    groups: dict[_Group, list[int]] = {}
    group_ts: dict[_Group, datetime] = {}
    orphans = Claim.objects.filter(
        user__isnull=True, changeset__isnull=True
    ).values_list("pk", "content_type_id", "object_id", "source_id", "created_at")
    for pk, content_type_id, object_id, source_id, created_at in orphans.iterator():
        key = _Group(content_type_id, object_id, source_id)
        groups.setdefault(key, []).append(pk)
        # min(created_at) per group — deterministic; the seed claims are all
        # within seconds anyway, so which one wins doesn't matter.
        if key not in group_ts or created_at < group_ts[key]:
            group_ts[key] = created_at

    if groups:
        # Every grouped source must have a seed run (0010 covers them all). A
        # gap means 0010 didn't run or didn't cover it — never mint an
        # unanchored ChangeSet (it would fail the user-XOR-ingest_run CHECK).
        missing = sorted({key.source_id for key in groups} - seed_run_by_source.keys())
        if missing:
            raise RuntimeError(
                f"Source(s) {missing} have changeset-less seed claims but no "
                f"{SEED_FINGERPRINT_PREFIX!r} IngestRun; apply "
                "0010_backfill_seed_ingest_runs first."
            )

        # Build the ChangeSets and aligned metadata in one loop so the pairing
        # is structural (zip), not a bet on bulk_create's return order.
        cs_objs = []
        meta: list[tuple[_Group, datetime]] = []
        for key in groups:
            cs_objs.append(
                ChangeSet(
                    ingest_run_id=seed_run_by_source[key.source_id], note=SEED_NOTE
                )
            )
            meta.append((key, group_ts[key]))
        ChangeSet.objects.bulk_create(cs_objs, batch_size=1000)

        # auto_now_add stamped "now" on insert; realign each ChangeSet to its
        # group's earliest claim, exactly as 0009/0010 do.
        for cs, (_key, ts) in zip(cs_objs, meta, strict=True):
            cs.created_at = ts
        ChangeSet.objects.bulk_update(cs_objs, ["created_at"], batch_size=1000)

        # Link each orphan claim to its group's ChangeSet. Construct lightweight
        # instances (pk + changeset_id only) to avoid reloading 104K rows.
        claim_updates = [
            Claim(pk=pk, changeset_id=cs.pk)
            for cs, (key, _ts) in zip(cs_objs, meta, strict=True)
            for pk in groups[key]
        ]
        Claim.objects.bulk_update(claim_updates, ["changeset"], batch_size=2000)

    # Milestone checkpoint: combined with 0009, every claim now has a ChangeSet.
    # This migration only processes source-attributed orphans, so a leftover is
    # an unexpected orphan (e.g. a user one 0009 missed) — fix it upstream, not
    # here. The raise routes the failure to the right PR.
    remaining = Claim.objects.filter(changeset__isnull=True).count()
    if remaining:
        raise RuntimeError(
            f"{remaining} changeset-less claim(s) remain after the seed backfill. "
            "0011 only fills source-attributed orphans; a leftover means an "
            "unexpected changeset-less claim (likely user-attributed) that 0009 "
            "or the media fix should have handled. Resolve it there, not here."
        )


def _reverse(apps, schema_editor):
    Claim = apps.get_model("provenance", "Claim")
    ChangeSet = apps.get_model("provenance", "ChangeSet")

    seed_changesets = ChangeSet.objects.filter(
        ingest_run__input_fingerprint__startswith=SEED_FINGERPRINT_PREFIX
    )
    # Claim.changeset is PROTECT — detach the claims before deleting.
    Claim.objects.filter(changeset__in=seed_changesets).update(changeset=None)
    seed_changesets.delete()


class Migration(migrations.Migration):
    dependencies = [
        ("provenance", "0010_backfill_seed_ingest_runs"),
    ]

    operations = [
        migrations.RunPython(_forward, _reverse),
    ]
