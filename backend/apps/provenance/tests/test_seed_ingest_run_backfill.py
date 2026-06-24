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
"""

from __future__ import annotations

import importlib
from datetime import UTC, datetime

import pytest
from django.apps import apps as django_apps
from django.contrib.contenttypes.models import ContentType

from apps.provenance.models import Claim, IngestRun, Source
from apps.provenance.test_factories import ingest_changeset

_migration = importlib.import_module(
    "apps.provenance.migrations.0010_backfill_seed_ingest_runs"
)

T_EARLY = datetime(2024, 1, 1, 17, 33, 13, tzinfo=UTC)
T_LATE = datetime(2024, 1, 1, 17, 33, 28, tzinfo=UTC)


def _source(slug: str) -> Source:
    return Source.objects.create(name=slug.title(), slug=slug, source_type="editorial")


def _orphan_claim(subject, source: Source, claim_key: str, *, created_at) -> Claim:
    """A source-attributed claim with no changeset, stamped at ``created_at``."""
    claim = Claim.objects.create(
        content_type=ContentType.objects.get_for_model(type(subject)),
        object_id=subject.pk,
        source=source,
        field_name=claim_key,
        claim_key=claim_key,
        value="x",
    )
    # created_at is auto_now_add; realign so min/max are deterministic.
    Claim.objects.filter(pk=claim.pk).update(created_at=created_at)
    return claim


def _real_run(source: Source, patch_id: str) -> IngestRun:
    return IngestRun.objects.create(
        source=source,
        input_fingerprint=f"sha256:{patch_id}",
        status="success",
        finished_at=T_LATE,
        patch_id=patch_id,
    )


@pytest.fixture
def mfr():
    from apps.catalog.models import Manufacturer

    return Manufacturer.objects.create(name="Acme", slug="acme")


@pytest.mark.django_db
def test_one_run_per_source_with_orphans(mfr):
    src_a = _source("seed-a")
    src_b = _source("seed-b")
    _orphan_claim(mfr, src_a, "name", created_at=T_EARLY)
    _orphan_claim(mfr, src_a, "url", created_at=T_LATE)
    _orphan_claim(mfr, src_b, "name", created_at=T_LATE)

    _migration._forward(django_apps, None)

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


@pytest.mark.django_db
def test_source_with_only_changesetted_claims_gets_no_run(mfr):
    src = _source("seed-c")
    real = _real_run(src, "0001-foo")
    cs = ingest_changeset(real)
    claim = Claim.objects.create(
        content_type=ContentType.objects.get_for_model(type(mfr)),
        object_id=mfr.pk,
        source=src,
        field_name="name",
        claim_key="name",
        value="x",
        changeset=cs,
    )
    assert claim.changeset_id == cs.pk

    _migration._forward(django_apps, None)

    assert not IngestRun.objects.filter(
        input_fingerprint="seed-backfill:seed-c"
    ).exists()


@pytest.mark.django_db
def test_mixed_source_prod_shape(mfr):
    """A source with both seed claims and real patch runs (the catalog case)."""
    src = _source("seed-d")
    real = _real_run(src, "0001-foo")
    _orphan_claim(mfr, src, "name", created_at=T_EARLY)

    _migration._forward(django_apps, None)

    seed_runs = IngestRun.objects.filter(input_fingerprint="seed-backfill:seed-d")
    assert seed_runs.count() == 1
    real.refresh_from_db()
    assert real.input_fingerprint == "sha256:0001-foo"  # untouched

    # Idempotent against the mix: re-running adds no second synthetic run and
    # still leaves the real run alone.
    _migration._forward(django_apps, None)
    assert seed_runs.count() == 1
    assert IngestRun.objects.filter(source=src).count() == 2  # one real, one seed


@pytest.mark.django_db
def test_forward_is_idempotent(mfr):
    src = _source("seed-e")
    _orphan_claim(mfr, src, "name", created_at=T_EARLY)

    _migration._forward(django_apps, None)
    _migration._forward(django_apps, None)

    assert (
        IngestRun.objects.filter(input_fingerprint="seed-backfill:seed-e").count() == 1
    )


@pytest.mark.django_db
def test_reverse_removes_only_synthetic_runs(mfr):
    src = _source("seed-f")
    real = _real_run(src, "0001-foo")
    _orphan_claim(mfr, src, "name", created_at=T_EARLY)

    _migration._forward(django_apps, None)
    assert IngestRun.objects.filter(input_fingerprint="seed-backfill:seed-f").exists()

    _migration._reverse(django_apps, None)

    assert not IngestRun.objects.filter(
        input_fingerprint__startswith="seed-backfill:"
    ).exists()
    assert IngestRun.objects.filter(pk=real.pk).exists()  # real run survives
