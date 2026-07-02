"""Backfill scalar citation support into the ClaimCitationInstance join.

The scalar/edit half of the citation model moves from ``CitationInstance.claim``
(a single-owner FK) to the ``ClaimCitationInstance`` join. EXP2 already dual-writes
join rows on both write paths; this migration fills the historical tail — every
pre-existing scalar instance carries the FK but no join row — and then collapses
the per-ChangeSet clones the old write path minted, so the shared-evidence model
holds retroactively, not just for new writes.

Two steps, backfill then collapse, in one transaction:

1. **Backfill** — one ``ClaimCitationInstance(claim=inst.claim, instance=inst)`` per
   scalar instance (``claim`` set). A direct 1:1 FK projection; ``ignore_conflicts``
   makes a re-run (or reverse-then-reapply) a clean no-op against the unique pair.
2. **Collapse** — the write path clones one instance per edited field, so a
   multi-field save with one citation leaves N identical rows. Group scalar
   instances by ``(changeset, source, locator)`` (full instance identity today),
   keep one survivor, repoint the group's join rows at it, delete the losers.

Inline ``[[cite:slug]]`` footnotes (``claim=NULL``) are untouched: the backfill
filters to ``claim__isnull=False`` and the collapse never sees them.

**Ships with the read switch.** The collapse deletes clones while reads still
traverse the old ``CitationInstance.claim`` reverse accessor; a deploy that
collapses without the follow-on read switch would show every non-survivor claim
as uncited. The two are order-independent at the DB level (the through-M2M is a
read-only view over this same join table), so they live in separate migrations —
they just must not deploy apart.

Reverse is a no-op: the collapse deletes clone rows irreversibly, and forward is
idempotent (backfill absorbed by the unique constraint, collapse sees only
singleton groups), so a re-forward after any reverse is safe.
"""

from __future__ import annotations

from collections import defaultdict

from django.db import migrations
from django.db.models import F


def _forward(apps, schema_editor):
    CitationInstance = apps.get_model("provenance", "CitationInstance")
    ClaimCitationInstance = apps.get_model("provenance", "ClaimCitationInstance")

    scalar = CitationInstance.objects.filter(claim__isnull=False)
    links = [
        ClaimCitationInstance(claim_id=claim_id, citation_instance_id=inst_id)
        for inst_id, claim_id in scalar.values_list("id", "claim_id")
    ]
    ClaimCitationInstance.objects.bulk_create(
        links, batch_size=2000, ignore_conflicts=True
    )

    _collapse_clones(apps)
    _assert_complete(apps)


def _referenced_instance_ids(apps) -> set[int]:
    """Instance ids that a ``[[cite:...]]`` marker resolves to (RecordReference).

    Scalar slugs are minted-but-unused by convention, but the ``cite`` link type
    resolves *any* ``CitationInstance`` by slug (no ``claim IS NULL`` filter), so
    a scalar clone *could* be a marker target. The collapse must never delete one.
    """
    RecordReference = apps.get_model("core", "RecordReference")
    return set(
        RecordReference.objects.filter(
            target_type__app_label="provenance",
            target_type__model="citationinstance",
        ).values_list("target_id", flat=True)
    )


def _collapse_clones(apps):
    CitationInstance = apps.get_model("provenance", "CitationInstance")
    ClaimCitationInstance = apps.get_model("provenance", "ClaimCitationInstance")
    referenced = _referenced_instance_ids(apps)

    groups: dict[tuple[int, int, str], list[tuple[int, int]]] = defaultdict(list)
    rows = CitationInstance.objects.filter(claim__isnull=False).values_list(
        "id", "claim_id", "claim__changeset_id", "citation_source_id", "locator"
    )
    for inst_id, claim_id, changeset_id, source_id, locator in rows:
        groups[(changeset_id, source_id, locator)].append((inst_id, claim_id))

    for key, members in groups.items():
        if len(members) < 2:
            continue
        member_ids = [i for i, _ in members]
        claim_ids = [c for _, c in members]
        # The repoint rests on distinct claims per group (write-path convention:
        # one clone per claim). Nothing structural enforces it and this sweeps
        # legacy data, so a claim repeated *within a group* would make the repoint
        # collide on prov_claimcite_unique with a raw IntegrityError. Fail
        # diagnosably instead. Per-group, not global: a claim owning instances in
        # two different (source, locator) groups is legitimate multi-evidence.
        if len(claim_ids) != len(set(claim_ids)):
            raise RuntimeError(
                f"Group {key} has a claim with >1 scalar instance "
                f"(instances {member_ids}, claims {claim_ids}): collapse repoint "
                "would collide on prov_claimcite_unique. Investigate by hand."
            )
        hit = [i for i in member_ids if i in referenced]
        if len(hit) > 1:
            raise RuntimeError(
                f"Collapse group {member_ids} has >1 marker-referenced instance; "
                "merging would break a [[cite:...]] marker. Investigate by hand."
            )
        # Prefer a marker-referenced member as survivor (preserve its slug);
        # else min id -- stable, arbitrary.
        survivor = hit[0] if hit else min(member_ids)
        losers = [i for i in member_ids if i != survivor]
        updated = ClaimCitationInstance.objects.filter(
            citation_instance_id__in=losers
        ).update(citation_instance_id=survivor)
        # Backfill gave every scalar instance exactly one self-link, so the
        # repoint must move exactly one row per loser. A shortfall means a loser
        # lost its citation silently -- invisible to the self-linked assertion
        # below, since the loser is about to be deleted.
        if updated != len(losers):
            raise RuntimeError(
                f"Collapse repointed {updated} join rows for {len(losers)} losers "
                f"in group {key}: a claim would silently lose its citation."
            )
        CitationInstance.objects.filter(id__in=losers).delete()


def _assert_complete(apps):
    """Fail-fast post-conditions; a leftover routes the failure to this migration."""
    CitationInstance = apps.get_model("provenance", "CitationInstance")
    ClaimCitationInstance = apps.get_model("provenance", "ClaimCitationInstance")
    # Every surviving scalar instance carries a join row for its own claim.
    if (
        CitationInstance.objects.filter(claim__isnull=False)
        .exclude(claim_links__claim_id=F("claim_id"))
        .exists()
    ):
        raise RuntimeError(
            "A scalar CitationInstance is missing its self-link after backfill."
        )

    # No clones remain: no (changeset, source, locator) group has >1 scalar row.
    counts: dict[tuple[int, int, str], int] = defaultdict(int)
    for changeset_id, source_id, locator in CitationInstance.objects.filter(
        claim__isnull=False
    ).values_list("claim__changeset_id", "citation_source_id", "locator"):
        counts[(changeset_id, source_id, locator)] += 1
    dupes = [k for k, n in counts.items() if n > 1]
    if dupes:
        raise RuntimeError(f"Scalar clone groups survived the collapse: {dupes}.")

    # No join row points at an inline (claim=NULL) instance.
    if ClaimCitationInstance.objects.filter(
        citation_instance__claim__isnull=True
    ).exists():
        raise RuntimeError("A ClaimCitationInstance points at an inline instance.")

    # No [[cite:...]] marker dangles: every referenced instance still exists.
    referenced = _referenced_instance_ids(apps)
    if referenced:
        existing = set(
            CitationInstance.objects.filter(id__in=referenced).values_list(
                "id", flat=True
            )
        )
        missing = referenced - existing
        if missing:
            raise RuntimeError(
                f"Collapse deleted marker-referenced instances {missing}: a "
                "[[cite:...]] marker now dangles."
            )


class Migration(migrations.Migration):
    # Pure RunPython/DML, no schema ops, so one all-or-nothing transaction is
    # correct (the collapse must see the backfill's rows). Reverse is a no-op:
    # the collapse's deletes can't be reconstructed, and forward is idempotent.
    atomic = True

    dependencies = [
        ("provenance", "0017_claimcitationinstance"),
        # The collapse's marker audit reads core.RecordReference (created in
        # core/0001); not reachable transitively, so name it.
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(_forward, migrations.RunPython.noop),
    ]
