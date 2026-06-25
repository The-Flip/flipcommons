"""Backfill ``ChangeSet.actor`` and ``Claim.actor`` for the historical tail.

``Actor`` is the single attribution target (docs/plans/auth/Actors.md). 0012
added ``ChangeSet.actor`` / ``Claim.actor`` nullable; the write path (PR #560)
already stamps both on every *new* row. What remains is the pre-existing tail —
the ~222K seed/old changesets and claims minted before the write path learned to
stamp ``actor``, which still carry ``actor = NULL``. This migration fills exactly
that tail, so a later "Cut over consumers" PR can read ``actor`` safely.

Pure FK projection across existing joins — no row creation, no grouping — so it
is set-based ``update()`` with ``Subquery``, not the in-memory bulk_create dance
0011 needed. Each update is filtered to ``actor__isnull=True`` so it touches only
the historical tail and leaves the already-correct new rows untouched.

Mapping:
- ChangeSet.actor <- user-attributed: changeset.user.actor;
                     ingest-attributed: changeset.ingest_run.source.actor
- Claim.actor     <- claim.changeset.actor (denormalized copy)

Safe against the live write path: the per-user/per-source dedupe in
``_assert_claim`` keys on the legacy ``user``/``source`` column (it flips to the
``actor`` key only at "Tighten schema") and no ``actor`` unique index exists yet,
so writing ``actor`` onto historical active claims collides with nothing. The
single ``atomic=True`` transaction does hold row locks on the swept claims until
commit — run it in the deploy window, not lock-free against live edits.
"""

from __future__ import annotations

from django.db import migrations
from django.db.models import F, OuterRef, Subquery


def _forward(apps, schema_editor):
    ChangeSet = apps.get_model("provenance", "ChangeSet")
    Claim = apps.get_model("provenance", "Claim")
    User = apps.get_model("accounts", "User")
    IngestRun = apps.get_model("provenance", "IngestRun")

    # 1. User-attributed changesets -> the user's actor.
    ChangeSet.objects.filter(actor__isnull=True, user__isnull=False).update(
        actor_id=Subquery(
            User.objects.filter(pk=OuterRef("user_id")).values("actor_id")[:1]
        )
    )
    # 2. Ingest changesets -> the run's source's actor (two hops).
    ChangeSet.objects.filter(actor__isnull=True, ingest_run__isnull=False).update(
        actor_id=Subquery(
            IngestRun.objects.filter(pk=OuterRef("ingest_run_id")).values(
                "source__actor_id"
            )[:1]
        )
    )
    # 3. Claim.actor <- its (now-populated) changeset's actor. Same transaction,
    #    so it reads the actors steps 1-2 just wrote.
    Claim.objects.filter(actor__isnull=True).update(
        actor_id=Subquery(
            ChangeSet.objects.filter(pk=OuterRef("changeset_id")).values("actor_id")[:1]
        )
    )

    _assert_complete(apps)


def _assert_complete(apps):
    """Fail-fast checks; a leftover routes the failure to the PR that owns it.

    Order matters: the null checks run first. The F-comparisons below promote to
    LEFT JOINs where ``NOT (x = NULL)`` is ``NULL`` — a NULL-``actor_id`` row is
    silently dropped from the mismatch set, so only the null checks can catch an
    unpopulated row. The ``*__isnull=False`` filters are likewise load-bearing:
    they guarantee a non-null target FK (PROTECT + minted), keeping the
    comparison clean.
    """
    ChangeSet = apps.get_model("provenance", "ChangeSet")
    Claim = apps.get_model("provenance", "Claim")

    if ChangeSet.objects.filter(actor__isnull=True).exists():
        raise RuntimeError(
            "ChangeSet rows remain with actor=NULL after the backfill: a "
            "changeset missing both user and ingest_run (impossible under the "
            "user-XOR-ingest_run CHECK) or a User/Source the Actor mint missed."
        )
    if Claim.objects.filter(actor__isnull=True).exists():
        raise RuntimeError(
            "Claim rows remain with actor=NULL after the backfill: a "
            "changeset-less claim slipped past 0009/0011. Fix that upstream."
        )

    # ChangeSet legacy-parity: holds by construction for the swept tail (steps
    # 1-2 derive actor from these very fields); asserted table-wide so it also
    # covers write-path-populated rows and catches any bypass write.
    if (
        ChangeSet.objects.filter(user__isnull=False)
        .exclude(actor_id=F("user__actor_id"))
        .exists()
    ):
        raise RuntimeError(
            "ChangeSet.actor disagrees with user.actor for some user changeset."
        )
    if (
        ChangeSet.objects.filter(ingest_run__isnull=False)
        .exclude(actor_id=F("ingest_run__source__actor_id"))
        .exists()
    ):
        raise RuntimeError(
            "ChangeSet.actor disagrees with ingest_run.source.actor for some "
            "ingest changeset."
        )

    # Denormalization: Claim.actor == claim.changeset.actor.
    if Claim.objects.exclude(actor_id=F("changeset__actor_id")).exists():
        raise RuntimeError(
            "Claim.actor disagrees with its changeset.actor — the denormalized "
            "copy drifted from its source of truth."
        )

    # Legacy-attribution (the one that matters most): the changeset's actor must
    # match the claim's OWN pre-existing author. Historical rows predate
    # _assert_claim's guard and this was never a DB constraint, so a mismatch
    # would silently freeze the wrong actor and change attribution at cutover.
    if (
        Claim.objects.filter(source__isnull=False)
        .exclude(actor_id=F("source__actor_id"))
        .exists()
    ):
        raise RuntimeError(
            "Claim.actor disagrees with source.actor for some source claim: its "
            "changeset's actor differs from the claim's legacy source author."
        )
    if (
        Claim.objects.filter(user__isnull=False)
        .exclude(actor_id=F("user__actor_id"))
        .exists()
    ):
        raise RuntimeError(
            "Claim.actor disagrees with user.actor for some user claim: its "
            "changeset's actor differs from the claim's legacy user author."
        )


def _reverse(apps, schema_editor):
    # Columns are nullable in this PR; null them all. The write path re-stamps
    # new rows on the next write, and a re-forward refills the tail.
    apps.get_model("provenance", "ChangeSet").objects.update(actor=None)
    apps.get_model("provenance", "Claim").objects.update(actor=None)


class Migration(migrations.Migration):
    # Pure RunPython/DML, no schema ops, so one all-or-nothing transaction is
    # correct (and step 3 must see steps 1-2's writes). Unlike 0012/0004, which
    # set atomic=False only because they mix DDL AlterField with DML.
    dependencies = [
        ("provenance", "0012_source_actor_and_changeset_claim_actor"),
        # Not transitive via 0012 (which depends only on actors/0001); step 1
        # reads the historical User.actor_id, so name it explicitly.
        ("accounts", "0004_user_actor"),
    ]

    operations = [
        migrations.RunPython(_forward, _reverse),
    ]
