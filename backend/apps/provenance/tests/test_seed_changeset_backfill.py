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
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest
from django.apps import apps as django_apps
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from apps.provenance.models import ChangeSet, Claim, IngestRun, Source

_migration = importlib.import_module(
    "apps.provenance.migrations.0011_backfill_seed_changesets"
)

T_EARLY = datetime(2024, 1, 1, 17, 33, 13, tzinfo=UTC)
T_LATE = datetime(2024, 1, 1, 17, 33, 28, tzinfo=UTC)


def _source(slug: str) -> Source:
    return Source.objects.create(name=slug.title(), slug=slug, source_type="editorial")


def _seed_run(source: Source) -> IngestRun:
    """Mimic the synthetic seed run 0010 mints for a source."""
    return IngestRun.objects.create(
        source=source,
        input_fingerprint=f"{_migration.SEED_FINGERPRINT_PREFIX}{source.slug}",
        status="success",
        finished_at=T_LATE,
    )


def _orphan_claim(
    subject, source: Source, claim_key: str, *, created_at, is_active: bool = True
) -> Claim:
    """A source-attributed claim with no changeset, stamped at ``created_at``."""
    claim = Claim.objects.create(
        content_type=ContentType.objects.get_for_model(type(subject)),
        object_id=subject.pk,
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


@pytest.fixture
def mfr():
    from apps.catalog.models import Manufacturer

    return Manufacturer.objects.create(name="Acme", slug="acme")


@pytest.fixture
def mfr2():
    from apps.catalog.models import Manufacturer

    return Manufacturer.objects.create(name="Beta", slug="beta")


@pytest.mark.django_db
def test_grouping_one_changeset_per_record_source(mfr, mfr2):
    src = _source("seed-a")
    _seed_run(src)
    # Two claims on one record from one source → one ChangeSet holding both.
    _orphan_claim(mfr, src, "name", created_at=T_EARLY)
    _orphan_claim(mfr, src, "url", created_at=T_LATE)
    # A second record from the same source → its own ChangeSet.
    _orphan_claim(mfr2, src, "name", created_at=T_LATE)

    _migration._forward(django_apps, None)

    assert ChangeSet.objects.count() == 2
    mfr_cs_ids = set(
        Claim.objects.filter(object_id=mfr.pk, source=src).values_list(
            "changeset_id", flat=True
        )
    )
    mfr2_cs_ids = set(
        Claim.objects.filter(object_id=mfr2.pk, source=src).values_list(
            "changeset_id", flat=True
        )
    )
    assert len(mfr_cs_ids) == 1  # both of mfr's claims share one ChangeSet
    assert len(mfr2_cs_ids) == 1
    assert mfr_cs_ids != mfr2_cs_ids  # the two records get distinct ChangeSets


@pytest.mark.django_db
def test_superseded_claim_rides_along(mfr):
    src = _source("seed-b")
    _seed_run(src)
    # A historical assert + supersede on the same field: both changeset-less,
    # both must land in the one (record, source) ChangeSet.
    superseded = _orphan_claim(mfr, src, "name", created_at=T_EARLY, is_active=False)
    active = _orphan_claim(mfr, src, "name", created_at=T_LATE, is_active=True)

    _migration._forward(django_apps, None)

    superseded.refresh_from_db()
    active.refresh_from_db()
    assert superseded.changeset_id is not None
    assert superseded.changeset_id == active.changeset_id


@pytest.mark.django_db
def test_attribution_is_ingest_changeset(mfr):
    src = _source("seed-c")
    run = _seed_run(src)
    claim = _orphan_claim(mfr, src, "name", created_at=T_EARLY)

    _migration._forward(django_apps, None)

    claim.refresh_from_db()
    cs = claim.changeset
    assert cs is not None
    assert cs.ingest_run_id == run.pk
    assert cs.user_id is None
    assert cs.action is None
    assert cs.note == _migration.SEED_NOTE


@pytest.mark.django_db
def test_changeset_timestamp_is_group_min(mfr):
    src = _source("seed-d")
    _seed_run(src)
    _orphan_claim(mfr, src, "name", created_at=T_LATE)
    _orphan_claim(mfr, src, "url", created_at=T_EARLY)

    _migration._forward(django_apps, None)

    # One record + one source → exactly one ChangeSet.
    cs = ChangeSet.objects.get()
    assert cs.created_at == T_EARLY  # min across the group


@pytest.mark.django_db
def test_consistency_changeset_run_source_matches_claim_source(mfr, mfr2):
    src_a = _source("seed-e")
    src_b = _source("seed-f")
    _seed_run(src_a)
    _seed_run(src_b)
    _orphan_claim(mfr, src_a, "name", created_at=T_EARLY)
    _orphan_claim(mfr2, src_b, "name", created_at=T_EARLY)

    _migration._forward(django_apps, None)

    for claim in Claim.objects.select_related("changeset__ingest_run"):
        assert claim.changeset is not None
        assert claim.changeset.ingest_run is not None
        assert claim.changeset.ingest_run.source_id == claim.source_id


@pytest.mark.django_db
def test_post_condition_no_changeset_less_claims(mfr):
    src = _source("seed-g")
    _seed_run(src)
    _orphan_claim(mfr, src, "name", created_at=T_EARLY)

    _migration._forward(django_apps, None)

    assert not Claim.objects.filter(changeset__isnull=True).exists()


@pytest.mark.django_db
def test_forward_is_idempotent(mfr):
    src = _source("seed-h")
    _seed_run(src)
    _orphan_claim(mfr, src, "name", created_at=T_EARLY)
    _orphan_claim(mfr, src, "url", created_at=T_LATE)

    _migration._forward(django_apps, None)
    first = set(ChangeSet.objects.values_list("pk", flat=True))
    _migration._forward(django_apps, None)

    assert set(ChangeSet.objects.values_list("pk", flat=True)) == first


@pytest.mark.django_db
def test_reverse_detaches_and_deletes_only_seed_changesets(mfr):
    src = _source("seed-i")
    run = _seed_run(src)
    claim = _orphan_claim(mfr, src, "name", created_at=T_EARLY)

    _migration._forward(django_apps, None)
    assert ChangeSet.objects.filter(ingest_run=run).exists()

    _migration._reverse(django_apps, None)

    claim.refresh_from_db()
    assert claim.changeset_id is None
    assert not ChangeSet.objects.filter(ingest_run=run).exists()
    assert IngestRun.objects.filter(pk=run.pk).exists()  # seed run survives


@pytest.mark.django_db
def test_fail_fast_when_source_has_no_seed_run(mfr):
    src = _source("seed-j")  # deliberately no seed run
    _orphan_claim(mfr, src, "name", created_at=T_EARLY)

    with pytest.raises(RuntimeError, match="no .*IngestRun"):
        _migration._forward(django_apps, None)

    assert not ChangeSet.objects.exists()


@pytest.mark.django_db
def test_fail_fast_on_duplicate_seed_run(mfr):
    src = _source("seed-k")
    _seed_run(src)
    # A second synthetic run for the same source (e.g. a slug change) — ambiguous.
    IngestRun.objects.create(
        source=src,
        input_fingerprint=f"{_migration.SEED_FINGERPRINT_PREFIX}seed-k-old",
        status="success",
        finished_at=T_LATE,
    )
    _orphan_claim(mfr, src, "name", created_at=T_EARLY)

    with pytest.raises(RuntimeError, match="multiple"):
        _migration._forward(django_apps, None)

    assert not ChangeSet.objects.exists()


@pytest.mark.django_db
def test_fail_fast_on_unexpected_orphan(mfr):
    # A user-attributed changeset-less claim — outside 0011's scope (it only
    # processes source orphans), so it must trip the milestone checkpoint.
    user = get_user_model().objects.create(username="moses", email="moses@example.com")
    Claim.objects.create(
        content_type=ContentType.objects.get_for_model(type(mfr)),
        object_id=mfr.pk,
        user=user,
        field_name="name",
        claim_key="name",
        value="x",
    )

    with pytest.raises(RuntimeError, match="changeset-less claim"):
        _migration._forward(django_apps, None)
