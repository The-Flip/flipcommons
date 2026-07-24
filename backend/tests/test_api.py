import pytest
from django.test import Client, override_settings
from django.utils import timezone

from apps.provenance.models import IngestRun, Source
from apps.provenance.test_factories import make_ingest_source


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_health_endpoint():
    client = Client()
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def _applied_patch(source: Source, patch_id: str) -> IngestRun:
    return IngestRun.objects.create(
        source=source,
        input_fingerprint=f"sha256:{patch_id}",
        patch_id=patch_id,
        status=IngestRun.Status.SUCCESS,
        finished_at=timezone.now(),
    )


@pytest.mark.django_db
@override_settings(DEBUG=True, GIT_COMMIT_SHA="abc123")
def test_version_endpoint_reports_commit_and_highest_applied_patch():
    """The ledger high-water mark, not the most recently applied patch.

    0184 is applied *after* 0183 here, so a max-by-timestamp implementation
    would pass this too — that's what the out-of-order test below separates.
    """
    source = make_ingest_source(name="Data patches")
    _applied_patch(source, "0183-earlier")
    _applied_patch(source, "0184-periodical-citations")

    response = Client().get("/api/version")

    assert response.status_code == 200
    assert response.json() == {
        "commit": "abc123",
        "data_patch": "0184-periodical-citations",
    }


@pytest.mark.django_db
@override_settings(DEBUG=True, GIT_COMMIT_SHA="abc123")
def test_version_endpoint_reports_high_water_mark_when_patches_applied_out_of_order():
    """A backfilled lower-numbered patch doesn't roll the reported version back."""
    source = make_ingest_source(name="Data patches")
    _applied_patch(source, "0184-periodical-citations")
    _applied_patch(source, "0183-backfilled-later")

    body = Client().get("/api/version").json()

    assert body["data_patch"] == "0184-periodical-citations"


@pytest.mark.django_db
@override_settings(DEBUG=True, GIT_COMMIT_SHA="")
def test_version_endpoint_with_no_patches_applied():
    """Empty database — the patch field is null, not a 500."""
    response = Client().get("/api/version")

    assert response.status_code == 200
    assert response.json() == {"commit": "", "data_patch": None}


@pytest.mark.django_db
@override_settings(DEBUG=True, GIT_COMMIT_SHA="abc123")
def test_version_endpoint_ignores_unsuccessful_and_non_patch_runs():
    """Only *applied* patches count — a rolled-back attempt changed nothing."""
    source = make_ingest_source(name="Data patches")
    _applied_patch(source, "0184-applied")
    IngestRun.objects.create(
        source=source,
        input_fingerprint="sha256:failed",
        patch_id="0185-rolled-back",
        status=IngestRun.Status.FAILED,
        finished_at=timezone.now(),
    )
    IngestRun.objects.create(
        source=source,
        input_fingerprint="sha256:normal-ingest",
        status=IngestRun.Status.SUCCESS,
        finished_at=timezone.now(),
    )

    body = Client().get("/api/version").json()

    assert body["data_patch"] == "0184-applied"
