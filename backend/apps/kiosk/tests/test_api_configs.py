"""Tests for the kiosk resource API at /api/kiosk/configs/."""

from __future__ import annotations

import json

import pytest
from django.test import Client

from apps.accounts.test_factories import make_user
from apps.catalog.models import Title
from apps.kiosk.models import KioskConfig, KioskConfigItem

LIST_URL = "/api/kiosk/configs/"


def detail_url(config_id: int) -> str:
    return f"/api/kiosk/configs/{config_id}/"


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.fixture
def regular_user(db):
    return make_user()


@pytest.fixture
def title_a(db):
    return Title.objects.create(name="Medieval Madness", slug="medieval-madness-title")


@pytest.fixture
def title_b(db):
    return Title.objects.create(name="Attack from Mars", slug="attack-from-mars-title")


# ── Auth ─────────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestAuth:
    def test_anon_list_unauthorized(self, client):
        resp = client.get(LIST_URL)
        assert resp.status_code in (401, 403)

    def test_non_superuser_forbidden(self, client, regular_user):
        client.force_login(regular_user)
        resp = client.get(LIST_URL)
        assert resp.status_code == 403

    def test_superuser_can_list(self, client, superuser):
        client.force_login(superuser)
        resp = client.get(LIST_URL)
        assert resp.status_code == 200
        assert resp.json() == []


# ── Create ───────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestCreate:
    def test_creates_with_defaults(self, client, superuser):
        client.force_login(superuser)
        resp = client.post(LIST_URL)
        assert resp.status_code == 201
        body = resp.json()
        assert isinstance(body["id"], int)
        assert body["page_heading"] == ""
        assert body["idle_seconds"] == 180
        assert body["items"] == []

    def test_audit_fields_set_from_request_user(self, client, superuser):
        client.force_login(superuser)
        resp = client.post(LIST_URL)
        cfg = KioskConfig.objects.get(pk=resp.json()["id"])
        assert cfg.created_by_id == superuser.pk
        assert cfg.updated_by_id == superuser.pk

    def test_repeated_post_creates_distinct_ids(self, client, superuser):
        client.force_login(superuser)
        ids: list[int] = []
        for _ in range(3):
            resp = client.post(LIST_URL)
            assert resp.status_code == 201
            ids.append(resp.json()["id"])
        assert len(set(ids)) == 3


# ── Detail / list ─────────────────────────────────────────────────────


@pytest.mark.django_db
class TestRead:
    def test_list_includes_item_count(self, client, superuser, title_a, title_b):
        cfg = KioskConfig.objects.create()
        KioskConfigItem.objects.create(config=cfg, title=title_a, position=1)
        KioskConfigItem.objects.create(config=cfg, title=title_b, position=2)
        client.force_login(superuser)
        resp = client.get(LIST_URL)
        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["item_count"] == 2

    def test_get_detail(self, client, superuser, title_a):
        cfg = KioskConfig.objects.create(page_heading="Now Playing")
        KioskConfigItem.objects.create(
            config=cfg, title=title_a, position=1, hook="Try this!"
        )
        client.force_login(superuser)
        resp = client.get(detail_url(cfg.pk))
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == cfg.pk
        assert body["page_heading"] == "Now Playing"
        assert len(body["items"]) == 1
        assert body["items"][0]["hook"] == "Try this!"
        assert body["items"][0]["title"]["public_id"] == title_a.public_id

    def test_detail_title_carries_no_manufacturer_year_without_models(
        self, client, superuser, title_a
    ):
        """A title with no models resolves to null manufacturer/year (the editor
        renders the bare name)."""
        cfg = KioskConfig.objects.create()
        KioskConfigItem.objects.create(config=cfg, title=title_a, position=1)
        client.force_login(superuser)
        title = client.get(detail_url(cfg.pk)).json()["items"][0]["title"]
        assert title["manufacturer"] is None
        assert title["year"] is None

    def test_detail_title_derives_manufacturer_year_from_first_model(
        self, client, superuser
    ):
        """The editor config derives the disambiguating manufacturer + year
        live from the title's first model, mirroring the display page."""
        from apps.catalog.models import CorporateEntity, MachineModel, Manufacturer

        mfr = Manufacturer.objects.create(name="Williams", slug="williams")
        ce = CorporateEntity.objects.create(
            name="Williams", slug="williams-ce", manufacturer=mfr
        )
        title = Title.objects.create(name="Medieval Madness", slug="mm-title")
        MachineModel.objects.create(
            title=title,
            name="Medieval Madness",
            slug="mm-model",
            corporate_entity=ce,
            year=1997,
        )
        cfg = KioskConfig.objects.create()
        KioskConfigItem.objects.create(config=cfg, title=title, position=1)
        client.force_login(superuser)
        body_title = client.get(detail_url(cfg.pk)).json()["items"][0]["title"]
        assert body_title["public_id"] == title.public_id
        assert body_title["manufacturer"] == {
            "name": "Williams",
            "public_id": "williams",
        }
        assert body_title["year"] == 1997

    def test_get_404(self, client, superuser):
        client.force_login(superuser)
        assert client.get(detail_url(999_999)).status_code == 404


# ── Patch ────────────────────────────────────────────────────────────


def _patch(client: Client, config_id: int, payload: dict[str, object]):
    return client.patch(
        detail_url(config_id),
        data=json.dumps(payload),
        content_type="application/json",
    )


@pytest.mark.django_db
class TestPatch:
    def test_updates_scalars(self, client, superuser):
        cfg = KioskConfig.objects.create()
        client.force_login(superuser)
        resp = _patch(
            client,
            cfg.pk,
            {"page_heading": "Now Playing", "idle_seconds": 60},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["page_heading"] == "Now Playing"
        assert body["idle_seconds"] == 60

    def test_replaces_items(self, client, superuser, title_a, title_b):
        cfg = KioskConfig.objects.create()
        KioskConfigItem.objects.create(config=cfg, title=title_a, position=1, hook="A")
        client.force_login(superuser)
        resp = _patch(
            client,
            cfg.pk,
            {
                "items": [
                    {"title_slug": title_b.slug, "position": 1, "hook": "B first"},
                    {"title_slug": title_a.slug, "position": 2, "hook": "A second"},
                ]
            },
        )
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert [i["title"]["public_id"] for i in items] == [
            title_b.public_id,
            title_a.public_id,
        ]
        assert [i["position"] for i in items] == [1, 2]

    def test_swap_positions_does_not_violate_unique(
        self, client, superuser, title_a, title_b
    ):
        """A naive in-place swap would hit (config, position) uniqueness mid-update.

        Full replacement (delete + bulk_create inside one transaction)
        sidesteps that. This test asserts the API supports the swap.
        """
        cfg = KioskConfig.objects.create()
        KioskConfigItem.objects.create(config=cfg, title=title_a, position=1)
        KioskConfigItem.objects.create(config=cfg, title=title_b, position=2)
        client.force_login(superuser)
        resp = _patch(
            client,
            cfg.pk,
            {
                "items": [
                    {"title_slug": title_a.slug, "position": 2, "hook": ""},
                    {"title_slug": title_b.slug, "position": 1, "hook": ""},
                ]
            },
        )
        assert resp.status_code == 200

    def test_unknown_title_slug_returns_422(self, client, superuser):
        cfg = KioskConfig.objects.create()
        client.force_login(superuser)
        resp = _patch(
            client,
            cfg.pk,
            {
                "items": [
                    {"title_slug": "no-such-title", "position": 1, "hook": ""},
                ]
            },
        )
        assert resp.status_code == 422

    def test_updated_by_set_from_request_user(self, client, superuser):
        cfg = KioskConfig.objects.create()
        # Stale created_by/updated_by from a previous user — the PATCH must
        # overwrite updated_by from request.user, not from any payload field.
        other = make_user()
        cfg.created_by = other
        cfg.updated_by = other
        cfg.save()
        client.force_login(superuser)
        resp = _patch(client, cfg.pk, {"page_heading": "Edited"})
        assert resp.status_code == 200
        cfg.refresh_from_db()
        assert cfg.updated_by_id == superuser.pk
        # created_by must not change on PATCH.
        assert cfg.created_by_id == other.pk

    def test_payload_audit_fields_ignored(self, client, superuser):
        """Even if the client tries to send created_by/updated_by, they're ignored.

        The schema doesn't declare those fields, so Pydantic should drop them
        from the parsed payload — this is a belt-and-suspenders assertion.
        """
        cfg = KioskConfig.objects.create()
        client.force_login(superuser)
        resp = _patch(
            client,
            cfg.pk,
            {"page_heading": "Edited", "created_by": 999_999, "updated_by": 999_999},
        )
        assert resp.status_code == 200
        cfg.refresh_from_db()
        assert cfg.updated_by_id == superuser.pk


# ── Delete ───────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestDelete:
    def test_deletes(self, client, superuser):
        cfg = KioskConfig.objects.create()
        client.force_login(superuser)
        resp = client.delete(detail_url(cfg.pk))
        assert resp.status_code == 204
        assert not KioskConfig.objects.filter(pk=cfg.pk).exists()

    def test_delete_404(self, client, superuser):
        client.force_login(superuser)
        assert client.delete(detail_url(999_999)).status_code == 404

    def test_delete_non_superuser_forbidden(self, client, regular_user):
        cfg = KioskConfig.objects.create()
        client.force_login(regular_user)
        resp = client.delete(detail_url(cfg.pk))
        assert resp.status_code == 403
        assert KioskConfig.objects.filter(pk=cfg.pk).exists()
