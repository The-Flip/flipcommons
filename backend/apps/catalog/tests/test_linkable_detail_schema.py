"""``LinkableDetailSchema`` parity + behavior tests.

Every top-level catalog entity detail response must expose a uniform
``public_id`` (the entity's URL identity), sourced from
``LinkableModel.public_id`` via the shared ``LinkableDetailSchema`` base.
For most entities ``public_id == slug``; for Location it is ``location_path``.
The assembler that builds JSON-LD ``@id``s reads this field uniformly, so a
detail schema that forgets the base would emit a wrong identity.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest

from apps.catalog._walks import linkable_models
from apps.catalog.models import Location
from config.api import api


def _detail_response_component(
    paths: dict[str, Any], entity_type: str, entity_type_plural: str
) -> str | None:
    """Component name of the 200 body for an entity's ``/api/pages`` detail GET.

    Detail routes live at ``/api/pages/{entity_type}/{public_id}``; Location is
    the exception, keyed on its plural (``/api/pages/locations/{path}``). Meta
    routes (sources, edit-history) sit under their own prefixes and don't match.
    """
    prefixes = (f"/api/pages/{entity_type}/", f"/api/pages/{entity_type_plural}/")
    for path, methods in paths.items():
        get_op = methods.get("get")
        if get_op is None or not path.startswith(prefixes) or "{" not in path:
            continue
        responses = get_op.get("responses", {})
        ok = responses.get(200) or responses.get("200") or {}
        ref: str = (
            ok.get("content", {})
            .get("application/json", {})
            .get("schema", {})
            .get("$ref", "")
        )
        if ref:
            return ref.rsplit("/", 1)[-1]
    return None


class TestLinkableDetailSchemaParity:
    """Model-driven safety net: every linkable catalog entity's detail
    response carries ``public_id``, so a future entity that forgets
    ``LinkableDetailSchema`` fails here rather than silently emitting a wrong
    JSON-LD ``@id``.
    """

    def test_every_detail_response_exposes_public_id(self) -> None:
        schema = api.get_openapi_schema()
        paths = schema["paths"]
        components = schema["components"]["schemas"]

        missing: list[str] = []
        for model in linkable_models():
            name = _detail_response_component(
                paths, model.entity_type, model.entity_type_plural
            )
            assert name is not None, (
                f"No /api/pages detail GET found for {model.__name__} "
                f"(entity_type={model.entity_type!r})"
            )
            if "public_id" not in components[name].get("properties", {}):
                missing.append(f"{model.__name__} → {name}")

        assert not missing, (
            "These catalog detail responses don't expose `public_id`. Inherit "
            f"`LinkableDetailSchema` and source it from the model: {missing}"
        )

    def test_every_detail_response_exposes_last_modified(self) -> None:
        """Every linkable catalog entity's detail response carries
        ``last_modified`` (freshness for JSON-LD ``dateModified``), so a future
        entity that forgets ``LastModifiedDetailSchema`` / ``EntityDetailSchema``
        fails here rather than silently dropping ``dateModified``.
        """
        schema = api.get_openapi_schema()
        paths = schema["paths"]
        components = schema["components"]["schemas"]

        missing: list[str] = []
        for model in linkable_models():
            name = _detail_response_component(
                paths, model.entity_type, model.entity_type_plural
            )
            assert name is not None, (
                f"No /api/pages detail GET found for {model.__name__} "
                f"(entity_type={model.entity_type!r})"
            )
            if "last_modified" not in components[name].get("properties", {}):
                missing.append(f"{model.__name__} → {name}")

        assert not missing, (
            "These catalog detail responses don't expose `last_modified`. "
            "Inherit `EntityDetailSchema` and pass "
            f"`last_modified=obj.last_modified`: {missing}"
        )


@pytest.mark.django_db
class TestLocationPublicIdCorrectness:
    """The load-bearing case: Location's ``public_id`` is ``location_path``,
    not ``slug`` — emitting ``slug`` would produce a non-dereferenceable
    ``@id`` for any non-top-level location.
    """

    def test_nested_location_public_id_is_location_path(self, client) -> None:
        usa = Location.objects.create(
            location_path="usa",
            slug="usa",
            name="USA",
            location_type="country",
            divisions=["state", "city"],
        )
        il = Location.objects.create(
            location_path="usa/il",
            slug="il",
            name="Illinois",
            location_type="state",
            parent=usa,
        )
        Location.objects.create(
            location_path="usa/il/chicago",
            slug="chicago",
            name="Chicago",
            location_type="city",
            parent=il,
        )

        resp = client.get("/api/pages/locations/usa/il/chicago")
        assert resp.status_code == 200
        data = resp.json()

        assert data["public_id"] == "usa/il/chicago"
        assert data["slug"] == "chicago"
        # public_id must NOT collapse to the bare slug for a nested location.
        assert data["public_id"] != data["slug"]


@pytest.mark.django_db
class TestSlugKeyedPublicIdParity:
    """For a slug-keyed entity, ``public_id`` serializes identically to
    ``slug`` — the value is unchanged by the migration.
    """

    def test_manufacturer_public_id_equals_slug(self, client, manufacturer) -> None:
        resp = client.get(f"/api/pages/manufacturer/{manufacturer.slug}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["public_id"] == data["slug"] == manufacturer.slug


@pytest.mark.django_db
class TestLastModifiedSourcing:
    """``last_modified`` is the sitemap's freshness value, not raw
    ``updated_at`` — identical for a non-aggregating entity, widened for Title.
    """

    def test_manufacturer_last_modified_equals_updated_at(
        self, client, manufacturer
    ) -> None:
        resp = client.get(f"/api/pages/manufacturer/{manufacturer.slug}")
        assert resp.status_code == 200
        # Manufacturer doesn't widen lastmod, so detail freshness == updated_at.
        # (Ninja serializes to millisecond precision, so compare with tolerance.)
        got = datetime.fromisoformat(resp.json()["last_modified"])
        assert abs(got - manufacturer.updated_at) < timedelta(milliseconds=1)
