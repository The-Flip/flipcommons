"""Backfill ChangeSets for user-attributed claims that have none.

The four MEDIA_EDIT endpoints used to mint user claims via ``assert_claim``
with no ``changeset``, leaving them unattributed (see the Actors "Fix Media
Claims" work). Now that every user write goes through a ChangeSet, give each
pre-existing user-attributed orphan its own user ChangeSet (``action=edit``),
timestamped to match the claim it carries. On dev this is the 4 ``user=moses``
media claims; on prod it is the handful of equivalents.

Scope is only user-attributed orphans (``user__isnull=False``). The ~104K
source-attributed changeset-less claims are deliberately untouched: a source
ChangeSet needs an ``ingest_run`` to satisfy the user-XOR-ingest_run check, so
those belong to the later "Backfill ingest runs" + "Backfill changesets" PRs.

Each orphan is a single-claim media mutation (one endpoint call writes exactly
one ``media_attachment`` claim), so per-claim grouping is intentional — there
is no multi-claim "Save" to reconstruct, unlike the source-seed backfill.
"""

from __future__ import annotations

from django.db import migrations


def backfill_user_changesets(apps, schema_editor):
    Claim = apps.get_model("provenance", "Claim")
    ChangeSet = apps.get_model("provenance", "ChangeSet")

    orphaned = Claim.objects.filter(user__isnull=False, changeset__isnull=True)
    for claim in orphaned.iterator():
        # Each orphaned media mutation was its own user action → its own
        # ChangeSet (grouping them would misrepresent separate edits as one).
        cs = ChangeSet.objects.create(user_id=claim.user_id, action="edit")
        # auto_now_add stamps "now" on insert; realign to the claim's time.
        ChangeSet.objects.filter(pk=cs.pk).update(created_at=claim.created_at)
        claim.changeset = cs
        claim.save(update_fields=["changeset"])


class Migration(migrations.Migration):
    dependencies = [
        ("provenance", "0008_citationinstance_prov_citinst_slug_length"),
    ]

    operations = [
        migrations.RunPython(
            backfill_user_changesets,
            migrations.RunPython.noop,
        ),
    ]
