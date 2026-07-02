"""Tests for ``/api/pages/admin/dashboard/`` — the admin glance page.

Pins the auth matrix (anon / non-staff / unverified-staff / verified-staff)
and the metric arithmetic across rolling 24h/7d/total windows.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.test_factories import make_user
from apps.media.models import MediaAsset
from apps.provenance.models import ChangeSet
from apps.provenance.test_factories import (
    ingest_changeset,
    ingest_run,
    make_ingest_source,
    user_changeset,
)

DASHBOARD_URL = "/api/pages/admin/dashboard/"


# ── auth matrix ───────────────────────────────────────────────────────


@pytest.mark.django_db
class TestAuthMatrix:
    def test_anonymous_is_denied(self, client: Client) -> None:
        # `django_auth` is configured on the Router and rejects before
        # `@requires` ever fires, so anonymous deterministically gets 401.
        resp = client.get(DASHBOARD_URL)
        assert resp.status_code == 401

    def test_non_staff_is_denied(self, client: Client, user: User) -> None:
        client.force_login(user)
        resp = client.get(DASHBOARD_URL)
        assert resp.status_code == 403

    def test_unverified_staff_is_denied(self, client: Client) -> None:
        unverified_staff = make_user(is_staff=True, email_verified=False)
        client.force_login(unverified_staff)
        resp = client.get(DASHBOARD_URL)
        assert resp.status_code == 403

    def test_verified_staff_gets_200(self, client: Client, staff: User) -> None:
        # `staff` fixture is email_verified by make_user's default.
        client.force_login(staff)
        resp = client.get(DASHBOARD_URL)
        assert resp.status_code == 200


# ── stats correctness ─────────────────────────────────────────────────


def _backdate_user(u: User, when: datetime) -> None:
    """Override ``date_joined`` after creation.

    The `make_user` factory doesn't expose `date_joined`; setting it
    post-create via `.update()` skips needing a factory parameter.
    """
    User.objects.filter(pk=u.pk).update(date_joined=when)


def _backdate_changeset(cs: ChangeSet, when: datetime) -> None:
    ChangeSet.objects.filter(pk=cs.pk).update(created_at=when)


def _backdate_asset(asset: MediaAsset, when: datetime) -> None:
    MediaAsset.objects.filter(pk=asset.pk).update(created_at=when)


def _make_asset(
    uploader: User,
    status: MediaAsset.Status = MediaAsset.Status.READY,
) -> MediaAsset:
    return MediaAsset.objects.create(
        kind=MediaAsset.Kind.IMAGE,
        status=status,
        original_filename="photo.jpg",
        mime_type="image/jpeg",
        byte_size=1024,
        width=800,
        height=600,
        uploaded_by=uploader,
    )


@pytest.mark.django_db
class TestSignupsMetric:
    def test_counts_split_across_windows(self, client: Client, staff: User) -> None:
        now = timezone.now()
        # Backdate the staff fixture out of both windows so the counts
        # reflect only the explicitly-seeded rows below.
        _backdate_user(staff, now - timedelta(days=400))
        inside_24h = make_user()
        _backdate_user(inside_24h, now - timedelta(hours=2))
        inside_7d = make_user()
        _backdate_user(inside_7d, now - timedelta(days=3))
        ancient = make_user()
        _backdate_user(ancient, now - timedelta(days=400))

        client.force_login(staff)
        m = client.get(DASHBOARD_URL).json()["signups"]
        assert m["last_24h"] == 1  # inside_24h only
        assert m["last_7d"] == 2  # inside_24h + inside_7d
        assert m["total"] == 4  # all four (incl. backdated staff + ancient)


@pytest.mark.django_db
class TestEditsMetric:
    def test_counts_user_changesets_across_windows(
        self, client: Client, staff: User
    ) -> None:
        now = timezone.now()
        editor = make_user()
        user_changeset(editor)  # recent — implicit now()
        weekish = user_changeset(editor)
        _backdate_changeset(weekish, now - timedelta(days=3))
        ancient = user_changeset(editor)
        _backdate_changeset(ancient, now - timedelta(days=400))

        client.force_login(staff)
        m = client.get(DASHBOARD_URL).json()["edits"]
        assert m["last_24h"] == 1
        assert m["last_7d"] == 2
        assert m["total"] == 3

    def test_ingest_changesets_excluded(self, client: Client, staff: User) -> None:
        source = make_ingest_source(name="TestSource", slug="test-source", priority=10)
        run = ingest_run(source)
        ingest_changeset(run)
        ingest_changeset(run)

        client.force_login(staff)
        m = client.get(DASHBOARD_URL).json()["edits"]
        assert m["last_24h"] == 0
        assert m["last_7d"] == 0
        assert m["total"] == 0
        assert m["last_at"] is None


@pytest.mark.django_db
class TestUploadsMetric:
    def test_counts_ready_assets_across_windows(
        self, client: Client, staff: User
    ) -> None:
        now = timezone.now()
        uploader = make_user()

        _make_asset(uploader)  # recent — implicit now()
        weekish = _make_asset(uploader)
        _backdate_asset(weekish, now - timedelta(days=3))
        ancient = _make_asset(uploader)
        _backdate_asset(ancient, now - timedelta(days=400))

        client.force_login(staff)
        m = client.get(DASHBOARD_URL).json()["uploads"]
        assert m["last_24h"] == 1
        assert m["last_7d"] == 2
        assert m["total"] == 3

    def test_non_ready_assets_excluded(self, client: Client, staff: User) -> None:
        uploader = make_user()
        _make_asset(uploader, status=MediaAsset.Status.FAILED)
        # PROCESSING is image-disallowed; use a video to exercise the path.
        MediaAsset.objects.create(
            kind=MediaAsset.Kind.VIDEO,
            status=MediaAsset.Status.PROCESSING,
            original_filename="clip.mp4",
            mime_type="video/mp4",
            byte_size=2048,
            uploaded_by=uploader,
        )
        _make_asset(uploader, status=MediaAsset.Status.READY)

        client.force_login(staff)
        m = client.get(DASHBOARD_URL).json()["uploads"]
        # Pin the filter on every output column — a regression where the
        # READY filter only applies to `total` would slip past a single
        # total-only assertion.
        assert m["last_24h"] == 1
        assert m["last_7d"] == 1
        assert m["total"] == 1
        assert m["last_at"] is not None


# ── last_at semantics ─────────────────────────────────────────────────


@pytest.mark.django_db
class TestLastAt:
    def test_empty_population_yields_none(self, client: Client, staff: User) -> None:
        # No edits exist (staff didn't make any). last_at should be None.
        client.force_login(staff)
        m = client.get(DASHBOARD_URL).json()["edits"]
        assert m["total"] == 0
        assert m["last_at"] is None

    def test_populated_matches_latest_created_at(
        self, client: Client, staff: User
    ) -> None:
        editor = make_user()
        older = user_changeset(editor)
        _backdate_changeset(older, timezone.now() - timedelta(days=2))
        newer = user_changeset(editor)  # implicit now()

        client.force_login(staff)
        m = client.get(DASHBOARD_URL).json()["edits"]
        last_at = datetime.fromisoformat(m["last_at"])
        newer.refresh_from_db()
        # Ninja serializes datetimes at millisecond precision; the DB
        # stores microseconds. Truncate to compare on the wire contract.
        expected_ms = newer.created_at.microsecond // 1000 * 1000
        assert last_at == newer.created_at.replace(microsecond=expected_ms)
