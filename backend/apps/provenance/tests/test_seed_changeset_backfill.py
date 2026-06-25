"""Guards for the seed-ChangeSet backfill migration (0011).

The migration gives every changeset-less, source-attributed seed claim a
ChangeSet — one per (record, source), pointing at that source's synthetic seed
IngestRun (minted by 0010), timestamped to the group's earliest claim. The risks
worth pinning:

- grouping: one ChangeSet per (record, source), holding every claim on that
  record from that source — including inactive/superseded ones;
- attribution: the ChangeSet is an ingest ChangeSet (ingest_run set, user/action
  NULL) anchored to the right seed run, consistent with the claim's source;
- the milestone: zero changeset-less claims remain afterwards;
- idempotent forward; reverse detaches and removes only the synthetic
  ChangeSets, leaving the seed runs and the claims behind;
- fail-fast on the broken shapes: no seed run, duplicate seed run, or an
  unexpected orphan this migration doesn't own.

These build the pre-backfill state (changeset-less claims), which can't exist on
the post-0014 schema, so they run against the historical state via
:func:`historical_apps` (rewound to provenance 0010, the node before 0011). The
backfill never dereferences a claim's subject, so a content type + arbitrary
object_id stands in for a real catalog record.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest

from apps.provenance.test_migration_state import historical_apps

_migration = importlib.import_module(
    "apps.provenance.migrations.0011_backfill_seed_changesets"
)

_BEFORE = ("provenance", "0010_backfill_seed_ingest_runs")

T_EARLY = datetime(2024, 1, 1, 17, 33, 13, tzinfo=UTC)
T_LATE = datetime(2024, 1, 1, 17, 33, 28, tzinfo=UTC)


def _ct(apps):
    ContentType = apps.get_model("contenttypes", "ContentType")
    ct, _ = ContentType.objects.get_or_create(app_label="catalog", model="manufacturer")
    return ct


def _source(apps, slug: str):
    Source = apps.get_model("provenance", "Source")
    return Source.objects.create(name=slug.title(), slug=slug, source_type="editorial")


def _seed_run(apps, source):
    """Mimic the synthetic seed run 0010 mints for a source."""
    IngestRun = apps.get_model("provenance", "IngestRun")
    return IngestRun.objects.create(
        source=source,
        input_fingerprint=f"{_migration.SEED_FINGERPRINT_PREFIX}{source.slug}",
        status="success",
        finished_at=T_LATE,
    )


def _orphan_claim(
    apps, ct, object_id, source, claim_key, *, created_at, is_active=True
):
    """A source-attributed claim with no changeset, stamped at ``created_at``."""
    Claim = apps.get_model("provenance", "Claim")
    claim = Claim.objects.create(
        content_type=ct,
        object_id=object_id,
        source=source,
        field_name=claim_key,
        claim_key=claim_key,
        value="x",
        is_active=is_active,
    )
    # created_at is auto_now_add; realign so min/max are deterministic.
    Claim.objects.filter(pk=claim.pk).update(created_at=created_at)
    claim.refresh_from_db()
    return claim


@pytest.mark.django_db(transaction=True)
def test_grouping_one_changeset_per_record_source():
    with historical_apps(_BEFORE) as apps:
        ChangeSet = apps.get_model("provenance", "ChangeSet")
        Claim = apps.get_model("provenance", "Claim")
        ct = _ct(apps)
        src = _source(apps, "seed-a")
        _seed_run(apps, src)
        # Two claims on one record from one source → one ChangeSet holding both.
        _orphan_claim(apps, ct, 1, src, "name", created_at=T_EARLY)
        _orphan_claim(apps, ct, 1, src, "url", created_at=T_LATE)
        # A second record from the same source → its own ChangeSet.
        _orphan_claim(apps, ct, 2, src, "name", created_at=T_LATE)

        _migration._forward(apps, None)

        assert ChangeSet.objects.count() == 2
        rec1_cs_ids = set(
            Claim.objects.filter(object_id=1, source=src).values_list(
                "changeset_id", flat=True
            )
        )
        rec2_cs_ids = set(
            Claim.objects.filter(object_id=2, source=src).values_list(
                "changeset_id", flat=True
            )
        )
        assert len(rec1_cs_ids) == 1  # both of record 1's claims share one ChangeSet
        assert len(rec2_cs_ids) == 1
        assert rec1_cs_ids != rec2_cs_ids  # distinct records get distinct ChangeSets


@pytest.mark.django_db(transaction=True)
def test_superseded_claim_rides_along():
    with historical_apps(_BEFORE) as apps:
        ct = _ct(apps)
        src = _source(apps, "seed-b")
        _seed_run(apps, src)
        # A historical assert + supersede on the same field: both changeset-less,
        # both must land in the one (record, source) ChangeSet.
        superseded = _orphan_claim(
            apps, ct, 1, src, "name", created_at=T_EARLY, is_active=False
        )
        active = _orphan_claim(apps, ct, 1, src, "name", created_at=T_LATE)

        _migration._forward(apps, None)

        superseded.refresh_from_db()
        active.refresh_from_db()
        assert superseded.changeset_id is not None
        assert superseded.changeset_id == active.changeset_id


@pytest.mark.django_db(transaction=True)
def test_attribution_is_ingest_changeset():
    with historical_apps(_BEFORE) as apps:
        ct = _ct(apps)
        src = _source(apps, "seed-c")
        run = _seed_run(apps, src)
        claim = _orphan_claim(apps, ct, 1, src, "name", created_at=T_EARLY)

        _migration._forward(apps, None)

        claim.refresh_from_db()
        cs = claim.changeset
        assert cs is not None
        assert cs.ingest_run_id == run.pk
        assert cs.user_id is None
        assert cs.action is None
        assert cs.note == _migration.SEED_NOTE


@pytest.mark.django_db(transaction=True)
def test_changeset_timestamp_is_group_min():
    with historical_apps(_BEFORE) as apps:
        ChangeSet = apps.get_model("provenance", "ChangeSet")
        ct = _ct(apps)
        src = _source(apps, "seed-d")
        _seed_run(apps, src)
        _orphan_claim(apps, ct, 1, src, "name", created_at=T_LATE)
        _orphan_claim(apps, ct, 1, src, "url", created_at=T_EARLY)

        _migration._forward(apps, None)

        # One record + one source → exactly one ChangeSet.
        cs = ChangeSet.objects.get()
        assert cs.created_at == T_EARLY  # min across the group


@pytest.mark.django_db(transaction=True)
def test_consistency_changeset_run_source_matches_claim_source():
    with historical_apps(_BEFORE) as apps:
        Claim = apps.get_model("provenance", "Claim")
        ct = _ct(apps)
        src_a = _source(apps, "seed-e")
        src_b = _source(apps, "seed-f")
        _seed_run(apps, src_a)
        _seed_run(apps, src_b)
        _orphan_claim(apps, ct, 1, src_a, "name", created_at=T_EARLY)
        _orphan_claim(apps, ct, 2, src_b, "name", created_at=T_EARLY)

        _migration._forward(apps, None)

        for claim in Claim.objects.select_related("changeset__ingest_run"):
            assert claim.changeset is not None
            assert claim.changeset.ingest_run is not None
            assert claim.changeset.ingest_run.source_id == claim.source_id


@pytest.mark.django_db(transaction=True)
def test_post_condition_no_changeset_less_claims():
    with historical_apps(_BEFORE) as apps:
        Claim = apps.get_model("provenance", "Claim")
        ct = _ct(apps)
        src = _source(apps, "seed-g")
        _seed_run(apps, src)
        _orphan_claim(apps, ct, 1, src, "name", created_at=T_EARLY)

        _migration._forward(apps, None)

        assert not Claim.objects.filter(changeset__isnull=True).exists()


@pytest.mark.django_db(transaction=True)
def test_forward_is_idempotent():
    with historical_apps(_BEFORE) as apps:
        ChangeSet = apps.get_model("provenance", "ChangeSet")
        ct = _ct(apps)
        src = _source(apps, "seed-h")
        _seed_run(apps, src)
        _orphan_claim(apps, ct, 1, src, "name", created_at=T_EARLY)
        _orphan_claim(apps, ct, 1, src, "url", created_at=T_LATE)

        _migration._forward(apps, None)
        first = set(ChangeSet.objects.values_list("pk", flat=True))
        _migration._forward(apps, None)

        assert set(ChangeSet.objects.values_list("pk", flat=True)) == first


@pytest.mark.django_db(transaction=True)
def test_reverse_detaches_and_deletes_only_seed_changesets():
    with historical_apps(_BEFORE) as apps:
        ChangeSet = apps.get_model("provenance", "ChangeSet")
        IngestRun = apps.get_model("provenance", "IngestRun")
        ct = _ct(apps)
        src = _source(apps, "seed-i")
        run = _seed_run(apps, src)
        claim = _orphan_claim(apps, ct, 1, src, "name", created_at=T_EARLY)

        _migration._forward(apps, None)
        assert ChangeSet.objects.filter(ingest_run=run).exists()

        _migration._reverse(apps, None)

        claim.refresh_from_db()
        assert claim.changeset_id is None
        assert not ChangeSet.objects.filter(ingest_run=run).exists()
        assert IngestRun.objects.filter(pk=run.pk).exists()  # seed run survives


@pytest.mark.django_db(transaction=True)
def test_fail_fast_when_source_has_no_seed_run():
    with historical_apps(_BEFORE) as apps:
        ChangeSet = apps.get_model("provenance", "ChangeSet")
        ct = _ct(apps)
        src = _source(apps, "seed-j")  # deliberately no seed run
        _orphan_claim(apps, ct, 1, src, "name", created_at=T_EARLY)

        with pytest.raises(RuntimeError, match="no .*IngestRun"):
            _migration._forward(apps, None)

        assert not ChangeSet.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_fail_fast_on_duplicate_seed_run():
    with historical_apps(_BEFORE) as apps:
        ChangeSet = apps.get_model("provenance", "ChangeSet")
        IngestRun = apps.get_model("provenance", "IngestRun")
        ct = _ct(apps)
        src = _source(apps, "seed-k")
        _seed_run(apps, src)
        # A second synthetic run for the same source (e.g. a slug change) — ambiguous.
        IngestRun.objects.create(
            source=src,
            input_fingerprint=f"{_migration.SEED_FINGERPRINT_PREFIX}seed-k-old",
            status="success",
            finished_at=T_LATE,
        )
        _orphan_claim(apps, ct, 1, src, "name", created_at=T_EARLY)

        with pytest.raises(RuntimeError, match="multiple"):
            _migration._forward(apps, None)

        assert not ChangeSet.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_fail_fast_on_unexpected_orphan():
    # The live User model matches the leaf accounts schema (only provenance is
    # rewound here); 0011 reads the claim's ``user_id``, never the User model.
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.create(
        username="moses", email="moses@example.com", password="!"
    )
    with historical_apps(_BEFORE) as apps:
        Claim = apps.get_model("provenance", "Claim")
        ct = _ct(apps)
        # A user-attributed changeset-less claim — outside 0011's scope (it only
        # processes source orphans), so it must trip the milestone checkpoint.
        Claim.objects.create(
            content_type=ct,
            object_id=1,
            user_id=user.pk,
            field_name="name",
            claim_key="name",
            value="x",
        )

        with pytest.raises(RuntimeError, match="changeset-less claim"):
            _migration._forward(apps, None)
