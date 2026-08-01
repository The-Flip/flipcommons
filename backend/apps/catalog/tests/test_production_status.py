"""Commit-3 coverage for the ProductionStatus entity.

The shared taxonomy-router contract (list/patch/create/delete shapes) is pinned
by the Cabinet/Tag/GameFormat suites and the parametrized PATCH-claims cases in
``test_api_claims_additional_entities``. This module covers what's specific to
ProductionStatus: its model constraints, that its router is live end-to-end, the
models-list facet, claim resolution by slug (the pindata data-patch path), and
that the export exposes the real value — including ``produced``, which carries no
suppression at the data layer.
"""

from __future__ import annotations

import json

import pytest
from django.db import IntegrityError

from apps.catalog.models import ProductionStatus, Title
from apps.catalog.tests.conftest import bulk_resolve, make_machine_model
from apps.core.types import JsonBody
from apps.provenance.models import ChangeSet, ChangeSetAction, Claim, Source
from apps.provenance.test_factories import make_claim


def _post(client, path: str, body: JsonBody):
    return client.post(path, data=json.dumps(body), content_type="application/json")


@pytest.mark.django_db
class TestProductionStatusModel:
    def test_name_unique_case_insensitive(self):
        ProductionStatus.objects.create(name="Produced", slug="produced")
        with pytest.raises(IntegrityError):
            ProductionStatus.objects.create(name="PRODUCED", slug="produced-2")

    def test_uppercase_slug_rejected(self):
        with pytest.raises(IntegrityError):
            ProductionStatus.objects.create(name="One-off", slug="One-Off")


@pytest.mark.django_db
class TestProductionStatusRouter:
    def test_list_shape_and_title_count(self, client):
        status = ProductionStatus.objects.create(
            name="Unreleased", slug="unreleased", display_order=2
        )
        make_machine_model(name="Cancelled Project", production_status=status)

        resp = client.get("/api/production-statuses/")
        assert resp.status_code == 200
        body = resp.json()
        assert set(body) == {"items", "count"}
        assert body["count"] == 1
        row = body["items"][0]
        assert row["slug"] == "unreleased"
        assert row["title_count"] == 1

    def test_create_persists_claims(self, client, user):
        client.force_login(user)
        resp = _post(
            client,
            "/api/production-statuses/",
            {"name": "Announced", "slug": "announced"},
        )
        assert resp.status_code == 201, resp.content
        assert ProductionStatus.objects.get(slug="announced").status == "active"
        cs = ChangeSet.objects.get(actor=user.actor, action=ChangeSetAction.CREATE)
        fields = set(
            Claim.objects.filter(changeset=cs).values_list("field_name", flat=True)
        )
        assert fields == {"name", "slug", "status"}

    def test_delete_happy_path(self, client, user):
        status = ProductionStatus.objects.create(name="One-off", slug="one-off")
        client.force_login(user)
        resp = _post(client, f"/api/production-statuses/{status.slug}/delete/", {})
        assert resp.status_code == 200, resp.content
        status.refresh_from_db()
        assert status.status == "deleted"

    def test_delete_blocked_by_referencing_model(self, client, user):
        status = ProductionStatus.objects.create(
            name="Produced", slug="produced", status="active"
        )
        make_machine_model(name="Shipped Game", production_status=status)
        client.force_login(user)
        resp = _post(client, f"/api/production-statuses/{status.slug}/delete/", {})
        assert resp.status_code == 422
        assert len(resp.json()["blocked_by"]) >= 1
        status.refresh_from_db()
        assert status.status == "active"


@pytest.mark.django_db
class TestProductionStatusFacet:
    def test_public_filter_by_production_status(self, client):
        unreleased = ProductionStatus.objects.create(
            name="Unreleased", slug="unreleased"
        )
        produced = ProductionStatus.objects.create(name="Produced", slug="produced")
        cancelled = make_machine_model(
            name="Cancelled", slug="cancelled", production_status=unreleased
        )
        make_machine_model(name="Shipped", slug="shipped", production_status=produced)

        url = "/api/public/filter/models/"
        resp = client.get(f"{url}?production_status=unreleased")
        body = resp.json()
        assert body["count"] == 1
        assert body["public_ids"] == [cancelled.slug]

        assert client.get(f"{url}?production_status=produced").json()["count"] == 1
        assert client.get(f"{url}?production_status=announced").json()["count"] == 0

    def test_variant_status_surfaces_without_a_flag(self, client):
        """A variant carrying its own status (an announced Limited Edition of a
        shipped Premium) surfaces at the filter's flat Model grain — the case
        the old list route needed an ``include_variants`` flag for."""
        announced = ProductionStatus.objects.create(name="Announced", slug="announced")
        parent = make_machine_model(name="Premium", slug="premium")
        le = make_machine_model(
            name="Limited Edition",
            slug="limited-edition",
            title=parent.title,
            variant_of=parent,
            production_status=announced,
        )

        body = client.get(
            "/api/public/filter/models/?production_status=announced"
        ).json()
        assert body["count"] == 1
        assert body["public_ids"] == [le.slug]


@pytest.mark.django_db
class TestProductionStatusClaimResolution:
    def test_fk_claim_resolves_by_pk(self):
        """A ``production_status`` claim (target PK) materializes the FK —
        the path a data patch (``production_status: unreleased``) takes after
        plan-time slug→PK resolution."""
        unreleased = ProductionStatus.objects.create(
            name="Unreleased", slug="unreleased"
        )
        model = make_machine_model(name="Cancelled Project")
        src = Source.objects.get(slug="bootstrap")

        make_claim(model, "production_status", unreleased.pk, ingest_source=src)
        bulk_resolve()

        model.refresh_from_db()
        assert model.production_status is not None
        assert model.production_status.slug == "unreleased"


@pytest.mark.django_db
class TestProductionStatusExport:
    def test_export_emits_real_value_including_produced(self, client):
        """The public export carries the real slug, with no produced-suppression
        at the data layer — the museum's whole need."""
        produced = ProductionStatus.objects.create(name="Produced", slug="produced")
        model = make_machine_model(name="Shipped Game", production_status=produced)

        resp = client.get("/api/public/export/models/")
        assert resp.status_code == 200
        row = next(r for r in resp.json() if r["public_id"] == model.slug)
        assert row["production_status"] == "produced"


@pytest.mark.django_db
class TestProductionStatusModelDetail:
    """The Model detail serializer returns the *real* value — including
    ``produced`` — because the Model editor consumes it as ``initialData``.
    The produced/null hide lives in the frontend (commit 4)."""

    def test_detail_emits_unreleased(self, client):
        status = ProductionStatus.objects.create(name="Unreleased", slug="unreleased")
        model = make_machine_model(name="Cancelled", production_status=status)
        data = client.get(f"/api/pages/model/{model.slug}").json()
        assert data["production_status"]["public_id"] == "unreleased"
        assert data["production_status"]["name"] == "Unreleased"

    def test_detail_emits_produced_unsuppressed(self, client):
        produced = ProductionStatus.objects.create(name="Produced", slug="produced")
        model = make_machine_model(name="Shipped", production_status=produced)
        data = client.get(f"/api/pages/model/{model.slug}").json()
        assert data["production_status"]["public_id"] == "produced"

    def test_detail_null_is_none(self, client):
        model = make_machine_model(name="Unknown")
        data = client.get(f"/api/pages/model/{model.slug}").json()
        assert data["production_status"] is None


@pytest.mark.django_db
class TestProductionStatusTitleRollup:
    """Multi-model Title rollup: production_status agrees like every other spec
    field — all models must share the same non-null status, any null vetoes the
    rollup — then best-effort suppress ``produced``."""

    @pytest.fixture
    def title(self):
        return Title.objects.create(name="Multi", slug="multi")

    def _agreed(self, client, title):
        return client.get(f"/api/pages/title/{title.slug}").json()["agreed_specs"]

    def test_agrees_when_all_same(self, client, title):
        status = ProductionStatus.objects.create(name="Unreleased", slug="unreleased")
        make_machine_model(name="A", slug="a", title=title, production_status=status)
        make_machine_model(name="B", slug="b", title=title, production_status=status)
        assert self._agreed(client, title)["production_status"]["public_id"] == (
            "unreleased"
        )

    def test_disagreement_shows_nothing(self, client, title):
        s1 = ProductionStatus.objects.create(name="Unreleased", slug="unreleased")
        s2 = ProductionStatus.objects.create(name="One-off", slug="one-off")
        make_machine_model(name="A", slug="a", title=title, production_status=s1)
        make_machine_model(name="B", slug="b", title=title, production_status=s2)
        assert self._agreed(client, title).get("production_status") is None

    def test_null_status_vetoes_rollup(self, client, title):
        """A null status is unknown, not a value to agree with: one model with a
        status and one without does not roll up. This is the Cactus Canyon case
        (a produced original with a null status + one aftermarket remake) — the
        title must not inherit the lone model's status."""
        status = ProductionStatus.objects.create(name="Aftermarket", slug="aftermarket")
        make_machine_model(name="A", slug="a", title=title)  # no status
        make_machine_model(name="B", slug="b", title=title, production_status=status)
        assert self._agreed(client, title).get("production_status") is None

    def test_all_null_is_none_no_raise(self, client, title):
        make_machine_model(name="A", slug="a", title=title)
        make_machine_model(name="B", slug="b", title=title)
        assert self._agreed(client, title).get("production_status") is None

    def test_produced_suppressed_when_agreed(self, client, title):
        produced = ProductionStatus.objects.create(name="Produced", slug="produced")
        make_machine_model(name="A", slug="a", title=title, production_status=produced)
        make_machine_model(name="B", slug="b", title=title, production_status=produced)
        assert self._agreed(client, title).get("production_status") is None
