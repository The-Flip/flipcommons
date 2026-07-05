"""Guards for the seed-IngestRun backfill migration (0010).

The migration mints one synthetic "seed" IngestRun per baseline source that
owns changeset-less, source-attributed claims, so the next PR can give those
claims source ChangeSets (which need an ingest_run to satisfy the
user-XOR-ingest_run CHECK). The risks worth pinning:

- one run per source, keyed/timestamped/counted correctly;
- a source whose claims already have changesets gets none;
- the prod shape — a source with both seed claims and real patch runs — gets
  exactly one new synthetic run, leaving the real runs untouched;
- idempotent forward; reverse removes only the synthetic rows.

These build the pre-backfill state (changeset-less claims), which can't exist on
the post-0014 schema, so they run against the historical state via
:func:`historical_apps` (rewound to provenance 0009, the node before 0010). The
backfill never dereferences a claim's subject, so a content type + arbitrary
object_id stands in for a real catalog record.
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest

from apps.provenance.test_migration_state import historical_apps

pytestmark = pytest.mark.migration

_migration = importlib.import_module(
    "apps.provenance.migrations.0010_backfill_seed_ingest_runs"
)

_BEFORE = ("provenance", "0009_backfill_user_claim_changesets")

T_EARLY = datetime(2024, 1, 1, 17, 33, 13, tzinfo=UTC)
T_LATE = datetime(2024, 1, 1, 17, 33, 28, tzinfo=UTC)


def _ct(apps):
    ContentType = apps.get_model("contenttypes", "ContentType")
    ct, _ = ContentType.objects.get_or_create(app_label="catalog", model="manufacturer")
    return ct


def _source(apps, slug: str):
    Source = apps.get_model("provenance", "Source")
    return Source.objects.create(name=slug.title(), slug=slug, source_type="editorial")


def _orphan_claim(apps, ct, object_id, source, claim_key, *, created_at):
    """A source-attributed claim with no changeset, stamped at ``created_at``."""
    Claim = apps.get_model("provenance", "Claim")
    claim = Claim.objects.create(
        content_type=ct,
        object_id=object_id,
        source=source,
        field_name=claim_key,
        claim_key=claim_key,
        value="x",
    )
    # created_at is auto_now_add; realign so min/max are deterministic.
    Claim.objects.filter(pk=claim.pk).update(created_at=created_at)
    return claim


def _real_run(apps, source, patch_id: str):
    IngestRun = apps.get_model("provenance", "IngestRun")
    return IngestRun.objects.create(
        source=source,
        input_fingerprint=f"sha256:{patch_id}",
        status="success",
        finished_at=T_LATE,
        patch_id=patch_id,
    )


@pytest.mark.django_db(transaction=True)
def test_one_run_per_source_with_orphans():
    with historical_apps(_BEFORE) as apps:
        IngestRun = apps.get_model("provenance", "IngestRun")
        ct = _ct(apps)
        src_a = _source(apps, "seed-a")
        src_b = _source(apps, "seed-b")
        _orphan_claim(apps, ct, 1, src_a, "name", created_at=T_EARLY)
        _orphan_claim(apps, ct, 1, src_a, "url", created_at=T_LATE)
        _orphan_claim(apps, ct, 2, src_b, "name", created_at=T_LATE)

        _migration._forward(apps, None)

        run_a = IngestRun.objects.get(input_fingerprint="seed-backfill:seed-a")
        assert run_a.source_id == src_a.pk
        assert run_a.status == "success"
        assert run_a.patch_id is None
        assert run_a.claims_asserted == 2
        assert run_a.started_at == T_EARLY  # min
        assert run_a.finished_at == T_LATE  # max

        run_b = IngestRun.objects.get(input_fingerprint="seed-backfill:seed-b")
        assert run_b.claims_asserted == 1
        assert run_b.started_at == T_LATE
        assert run_b.finished_at == T_LATE


@pytest.mark.django_db(transaction=True)
def test_source_with_only_changesetted_claims_gets_no_run():
    with historical_apps(_BEFORE) as apps:
        ChangeSet = apps.get_model("provenance", "ChangeSet")
        Claim = apps.get_model("provenance", "Claim")
        IngestRun = apps.get_model("provenance", "IngestRun")
        ct = _ct(apps)
        src = _source(apps, "seed-c")
        real = _real_run(apps, src, "0001-foo")
        cs = ChangeSet.objects.create(ingest_run=real)
        claim = Claim.objects.create(
            content_type=ct,
            object_id=1,
            source=src,
            field_name="name",
            claim_key="name",
            value="x",
            changeset=cs,
        )
        assert claim.changeset_id == cs.pk

        _migration._forward(apps, None)

        assert not IngestRun.objects.filter(
            input_fingerprint="seed-backfill:seed-c"
        ).exists()


@pytest.mark.django_db(transaction=True)
def test_mixed_source_prod_shape():
    """A source with both seed claims and real patch runs (the catalog case)."""
    with historical_apps(_BEFORE) as apps:
        IngestRun = apps.get_model("provenance", "IngestRun")
        ct = _ct(apps)
        src = _source(apps, "seed-d")
        real = _real_run(apps, src, "0001-foo")
        _orphan_claim(apps, ct, 1, src, "name", created_at=T_EARLY)

        _migration._forward(apps, None)

        seed_runs = IngestRun.objects.filter(input_fingerprint="seed-backfill:seed-d")
        assert seed_runs.count() == 1
        real.refresh_from_db()
        assert real.input_fingerprint == "sha256:0001-foo"  # untouched

        # Idempotent against the mix: re-running adds no second synthetic run and
        # still leaves the real run alone.
        _migration._forward(apps, None)
        assert seed_runs.count() == 1
        assert IngestRun.objects.filter(source=src).count() == 2  # one real, one seed


@pytest.mark.django_db(transaction=True)
def test_forward_is_idempotent():
    with historical_apps(_BEFORE) as apps:
        IngestRun = apps.get_model("provenance", "IngestRun")
        ct = _ct(apps)
        src = _source(apps, "seed-e")
        _orphan_claim(apps, ct, 1, src, "name", created_at=T_EARLY)

        _migration._forward(apps, None)
        _migration._forward(apps, None)

        assert (
            IngestRun.objects.filter(input_fingerprint="seed-backfill:seed-e").count()
            == 1
        )


@pytest.mark.django_db(transaction=True)
def test_reverse_removes_only_synthetic_runs():
    with historical_apps(_BEFORE) as apps:
        IngestRun = apps.get_model("provenance", "IngestRun")
        ct = _ct(apps)
        src = _source(apps, "seed-f")
        real = _real_run(apps, src, "0001-foo")
        _orphan_claim(apps, ct, 1, src, "name", created_at=T_EARLY)

        _migration._forward(apps, None)
        assert IngestRun.objects.filter(
            input_fingerprint="seed-backfill:seed-f"
        ).exists()

        _migration._reverse(apps, None)

        assert not IngestRun.objects.filter(
            input_fingerprint__startswith="seed-backfill:"
        ).exists()
        assert IngestRun.objects.filter(pk=real.pk).exists()  # real run survives
