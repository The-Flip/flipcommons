"""Tests for the Changes page API endpoints."""

from __future__ import annotations

import pytest
from django.test import Client
from django.utils import timezone

from apps.accounts.test_factories import make_user
from apps.catalog.models import Manufacturer
from apps.catalog.tests.conftest import make_machine_model
from apps.provenance.models import ChangeSet, IngestRun
from apps.provenance.pagination import cursor_paginate
from apps.provenance.test_factories import (
    ingest_changeset,
    make_claim,
    make_ingest_source,
    user_changeset,
)


@pytest.fixture
def client():
    return Client()


@pytest.fixture
def user_b(db):
    return make_user()


@pytest.fixture
def source(db):
    return make_ingest_source(name="IPDB", source_type="database", priority=10)


@pytest.fixture
def pm(db, bootstrap_source):
    pm = make_machine_model(
        name="Medieval Madness", slug="medieval-madness", production_year=1997
    )
    make_claim(pm, "name", "Medieval Madness", ingest_source=bootstrap_source)
    return pm


@pytest.fixture
def mfr(db, bootstrap_source):
    mfr = Manufacturer.objects.create(name="Williams", slug="williams")
    make_claim(mfr, "name", "Williams", ingest_source=bootstrap_source)
    return mfr


# ── Cursor pagination utility ─────────────────────────────────────


@pytest.mark.django_db
class TestCursorPaginate:
    def test_first_page(self, user, pm):
        for i in range(5):
            cs = user_changeset(user)
            make_claim(pm, "production_year", 1990 + i, user=user, changeset=cs)

        items, next_cursor = cursor_paginate(ChangeSet.objects.all(), "", 3)
        assert len(items) == 3
        assert next_cursor is not None

    def test_second_page_via_cursor(self, user, pm):
        for i in range(5):
            cs = user_changeset(user)
            make_claim(pm, "production_year", 1990 + i, user=user, changeset=cs)

        # Scope to this user's changesets; the pm fixture seeds ingest changesets.
        qs = ChangeSet.objects.filter(actor=user.actor)
        items1, cursor = cursor_paginate(qs, "", 3)
        assert cursor is not None
        items2, cursor2 = cursor_paginate(qs, cursor, 3)
        assert len(items2) == 2
        assert cursor2 is None
        # No overlapping IDs
        ids1 = {i.pk for i in items1}
        ids2 = {i.pk for i in items2}
        assert ids1.isdisjoint(ids2)

    def test_same_timestamp_tiebreaker(self, user, pm):
        """Changesets with identical created_at are ordered by -id."""
        now = timezone.now()
        cs_ids = []
        for i in range(3):
            cs = user_changeset(user)
            make_claim(pm, "production_year", 1990 + i, user=user, changeset=cs)
            ChangeSet.objects.filter(pk=cs.pk).update(created_at=now)
            cs_ids.append(cs.pk)

        # Scope to this user's changesets; the pm fixture seeds ingest changesets.
        qs = ChangeSet.objects.filter(actor=user.actor)
        items, cursor = cursor_paginate(qs, "", 2)
        assert len(items) == 2
        assert cursor is not None
        items2, _ = cursor_paginate(qs, cursor, 2)
        assert len(items2) == 1
        all_ids = [i.pk for i in items] + [i.pk for i in items2]
        assert len(set(all_ids)) == 3

    def test_empty_queryset(self):
        items, cursor = cursor_paginate(ChangeSet.objects.all(), "", 10)
        assert items == []
        assert cursor is None


# ── List endpoint ─────────────────────────────────────────────────


def _user_items(resp):
    """Feed entries authored by users; the pm/mfr fixtures seed ingest changesets."""
    return [
        it
        for it in resp.json()["items"]
        if it["attribution"]["author"]["kind"] == "user"
    ]


@pytest.mark.django_db
class TestChangesList:
    def test_returns_user_edits(self, client, user, pm):
        client.force_login(user)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"production_year": 1998}}',
            content_type="application/json",
        )
        resp = client.get("/api/pages/changesets/")
        assert resp.status_code == 200
        items = _user_items(resp)
        assert len(items) == 1
        item = items[0]
        assert item["attribution"]["author"] == {
            "kind": "user",
            "username": user.username,
        }
        assert item["entity"]["name"] == "Medieval Madness"
        assert item["entity"]["type_label"] == "Model"
        assert item["changes_count"] >= 1

    def test_includes_ingest(self, client, source, pm):
        run = IngestRun.objects.create(
            source=source,
            status="success",
            input_fingerprint="test",
            finished_at=timezone.now(),
        )
        cs = ingest_changeset(run)
        make_claim(pm, "production_year", 1999, ingest_source=source, changeset=cs)

        resp = client.get("/api/pages/changesets/")
        assert resp.status_code == 200
        items = resp.json()["items"]
        # The pm fixture seeds its own (Bootstrap) ingest changesets; assert the
        # IPDB ingest changeset created here is present in the feed.
        ipdb = [
            it
            for it in items
            if it["attribution"]["author"] == {"kind": "source", "name": "IPDB"}
        ]
        assert len(ipdb) == 1

    def test_entity_type_filter(self, client, user, pm, mfr):
        client.force_login(user)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"production_year": 1998}}',
            content_type="application/json",
        )
        client.patch(
            f"/api/manufacturers/{mfr.slug}/claims/",
            data='{"fields": {"name": "Williams Inc"}}',
            content_type="application/json",
        )

        resp = client.get("/api/pages/changesets/?entity_type=manufacturer")
        assert resp.status_code == 200
        # mfr fixture seeds an ingest changeset on the manufacturer; assert on the
        # user edit (which must be a manufacturer, confirming the filter works).
        items = _user_items(resp)
        assert len(items) == 1
        assert items[0]["entity"]["type_label"] == "Manufacturer"

    def test_invalid_entity_type_returns_empty(self, client):
        resp = client.get("/api/pages/changesets/?entity_type=nonexistent")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_cursor_pagination(self, client, user, pm):
        client.force_login(user)
        for i in range(5):
            client.patch(
                f"/api/models/{pm.slug}/claims/",
                data=f'{{"fields": {{"production_year": {1990 + i}}}}}',
                content_type="application/json",
            )

        # The feed also carries the pm fixture's seed ingest changesets, which are
        # older than these user edits and so sort after them; assert on the user
        # edits surfaced per page (3 newest, then the remaining 2).
        resp1 = client.get("/api/pages/changesets/?limit=3")
        data1 = resp1.json()
        user1 = _user_items(resp1)
        assert len(user1) == 3
        assert data1["next_cursor"] is not None

        resp2 = client.get(
            f"/api/pages/changesets/?limit=3&cursor={data1['next_cursor']}"
        )
        user2 = _user_items(resp2)
        assert len(user2) == 2

        ids1 = {i["id"] for i in user1}
        ids2 = {i["id"] for i in user2}
        assert ids1.isdisjoint(ids2)

    def test_after_filter(self, client, user, pm):
        client.force_login(user)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"production_year": 1998}}',
            content_type="application/json",
        )
        # Use a future timestamp so the edit falls before it.
        future = "2099-01-01T00:00:00"
        resp = client.get(f"/api/pages/changesets/?after={future}")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 0

        # Use a past timestamp so the edit falls after it. Filter to the user edit;
        # the pm fixture's seed ingest changesets also fall after the past boundary.
        past = "2000-01-01T00:00:00"
        resp = client.get(f"/api/pages/changesets/?after={past}")
        assert resp.status_code == 200
        assert len(_user_items(resp)) == 1

    def test_deleted_entity_excluded(self, client, user, pm):
        client.force_login(user)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"production_year": 1998}}',
            content_type="application/json",
        )
        pm.delete()

        resp = client.get("/api/pages/changesets/")
        assert resp.status_code == 200
        # The deleted model's changesets (including the user edit) are excluded.
        # The auto-Title survives, so its seed ingest changeset may remain; assert
        # no feed entry references the deleted Model.
        items = resp.json()["items"]
        assert all(it["entity"]["type_label"] != "Model" for it in items)
        assert _user_items(resp) == []


# ── Detail endpoint ───────────────────────────────────────────────


@pytest.mark.django_db
class TestChangesDetail:
    def test_returns_field_diffs(self, client, user, pm):
        client.force_login(user)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"production_year": 1998}}',
            content_type="application/json",
        )
        cs_id = ChangeSet.objects.filter(actor=user.actor).latest("created_at").pk

        resp = client.get(f"/api/pages/changesets/{cs_id}/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["entity"]["name"] == "Medieval Madness"
        assert len(data["changes"]) >= 1
        year_change = next(
            c for c in data["changes"] if c["field_name"] == "production_year"
        )
        assert year_change["new_value"]["raw"] == 1998

    def test_cross_author_old_value(self, client, user, user_b, pm):
        """User B editing after User A shows A's value as old_value."""
        client.force_login(user)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"production_year": 1998}}',
            content_type="application/json",
        )
        client.force_login(user_b)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"production_year": 2001}}',
            content_type="application/json",
        )

        cs_id = ChangeSet.objects.filter(actor=user_b.actor).latest("created_at").pk
        resp = client.get(f"/api/pages/changesets/{cs_id}/")
        assert resp.status_code == 200
        year_change = next(
            c for c in resp.json()["changes"] if c["field_name"] == "production_year"
        )
        assert year_change["old_value"]["raw"] == 1998
        assert year_change["new_value"]["raw"] == 2001

    def test_nonexistent_changeset_returns_404(self, client):
        resp = client.get("/api/pages/changesets/99999/")
        assert resp.status_code == 404

    def test_first_edit_has_null_old_value(self, client, user, pm):
        """First user edit for a field has null old_value."""
        client.force_login(user)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"production_year": 1998}}',
            content_type="application/json",
        )
        cs_id = ChangeSet.objects.filter(actor=user.actor).latest("created_at").pk

        resp = client.get(f"/api/pages/changesets/{cs_id}/")
        year_change = next(
            c for c in resp.json()["changes"] if c["field_name"] == "production_year"
        )
        # The bootstrap source claim has no changeset, so no prior user claim exists.
        # old_value should be None for the first user edit.
        assert year_change["old_value"] is None

    def test_retraction_only_changeset(self, client, user, pm):
        """A changeset with only retracted claims shows retractions, no changes."""
        # Create a claim, then retract it via a separate changeset.
        original_cs = user_changeset(user)
        claim = make_claim(
            pm, "production_year", 2000, user=user, changeset=original_cs
        )

        retract_cs = user_changeset(user)
        claim.retracted_by_changeset = retract_cs
        claim.is_active = False
        claim.save()

        resp = client.get(f"/api/pages/changesets/{retract_cs.pk}/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["changes"] == []
        assert len(data["retractions"]) == 1
        assert data["retractions"][0]["field_name"] == "production_year"
        assert data["retractions"][0]["old_value"]["raw"] == 2000


@pytest.mark.django_db
class TestChangesListBeforeFilter:
    def test_before_filter(self, client, user, pm):
        client.force_login(user)
        client.patch(
            f"/api/models/{pm.slug}/claims/",
            data='{"fields": {"production_year": 1998}}',
            content_type="application/json",
        )
        # Use a past timestamp so the edit falls after it.
        past = "2000-01-01T00:00:00"
        resp = client.get(f"/api/pages/changesets/?before={past}")
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 0

        # Use a future timestamp so the edit falls before it. Filter to the user
        # edit; the pm fixture's seed ingest changesets also fall before the future.
        future = "2099-01-01T00:00:00"
        resp = client.get(f"/api/pages/changesets/?before={future}")
        assert resp.status_code == 200
        assert len(_user_items(resp)) == 1
