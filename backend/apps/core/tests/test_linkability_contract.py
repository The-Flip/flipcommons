"""Acceptance tests for the model-driven linkability contract.

These tests are the executable form of the model-driven linkability contract:

1. Every concrete ``LinkableModel`` subclass routes its CRUD lifecycle
   through the shared factories — no per-entity duplication of
   ``/{public_id}/delete-preview/``, ``/{public_id}/delete/``, or
   ``/{public_id}/restore/`` handlers.
2. The shared page endpoints (`/api/pages/edit-history/...`,
   `/api/pages/sources/...`) return 404, never 500, when a single-segment
   ``public_id`` is hit with extra trailing path segments.
3. ``apps.core.checks.check_linkable_models`` rejects malformed
   subclasses (missing ``entity_type_plural``, ``public_id_field``
   pointing at a non-unique field, etc.).
"""

from __future__ import annotations

import re

import pytest
from django.core.checks import Error
from django.db import models
from django.test import Client

from apps.core.checks import check_linkable_models
from apps.core.models import LinkableModel

# ---------------------------------------------------------------------------
# 1. Route contract: every public_id-bearing path uses the path converter
# ---------------------------------------------------------------------------


class TestRouteContract:
    """Every Ninja path on the live API that mentions ``public_id`` (in any
    form — ``public_id``, ``parent_public_id``, ``<x>_public_id``) must use
    Ninja's ``{path:name}`` converter, never the bare single-segment form.

    This is the structural backstop for linkable route shape: it iterates the
    *actual* mounted routes (not the factory source code), so a future
    bespoke router that adds ``"/{public_id}/anything/"`` fails this test
    without anyone having to remember to update it. Adds Location-shaped
    multi-segment ids without touching every per-entity router.
    """

    def test_every_public_id_route_uses_path_converter(self):
        from config.api import api

        violations: list[str] = []
        for prefix, router in api._routers:
            for path_template in router.path_operations:
                full = f"{prefix}{path_template}"
                for match in re.finditer(r"\{([^}]+)\}", full):
                    param = match.group(1)
                    # Any param whose name contains ``public_id`` must be
                    # declared with the ``path:`` converter prefix.
                    if "public_id" in param and not param.startswith("path:"):
                        violations.append(full)
                        break

        assert not violations, (
            "Routes using single-segment ``{public_id}`` (rather than "
            "``{path:public_id}``) cannot serve multi-segment public_ids "
            "like Location's ``usa/il/chicago``. Flip each to the "
            "``{path:public_id}`` form:\n  " + "\n  ".join(violations)
        )


# ---------------------------------------------------------------------------
# 2. :path widening — single-segment models must 404 on extra segments
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPathConverterWidening:
    """``/api/pages/edit-history/{entity_type}/{path:public_id}/`` accepts
    multi-segment ids but still 404s when no row matches.

    Concrete cases:
    - Single-segment model + extra segments: misses the lookup → 404.
    - Single-segment model + matching id: 200.
    """

    def setup_method(self):
        self.client = Client()

    def test_extra_segments_404_not_500(self):
        # No Theme exists at this multi-segment path; the lookup misses.
        resp = self.client.get("/api/pages/edit-history/theme/sci-fi/extra/")
        assert resp.status_code == 404, resp.content

    def test_extra_segments_on_sources_404_not_500(self):
        resp = self.client.get("/api/pages/sources/theme/sci-fi/extra/")
        assert resp.status_code == 404, resp.content

    def test_extra_segments_on_detail_page_404_not_500(self):
        # The shared detail-page registrar (``register_entity_detail_page``)
        # mounts ``/{entity_type}/{path:public_id}`` on the pages router.
        # A multi-segment id against a single-segment model should miss the
        # lookup and 404, not 500.
        resp = self.client.get("/api/pages/theme/sci-fi/extra/")
        assert resp.status_code == 404, resp.content

    def test_extra_segments_on_lifecycle_routes_404_not_500(self):
        # The shared lifecycle factory (``register_entity_delete_restore``)
        # mounts ``/{path:public_id}/{action}/`` on each entity's router.
        # Multi-segment ids must widen-and-miss to 404, not match nothing
        # (which would be a 405) or 500. Hits Theme, which is single-segment;
        # the path converter accepts the multi-segment URL and the lookup
        # misses cleanly.
        resp = self.client.get("/api/themes/sci-fi/extra/delete-preview/")
        assert resp.status_code in (401, 404), resp.content
        # 401 because django_auth gates the route — auth runs before the
        # lookup, so an unauthenticated request can't distinguish "no such
        # entity" from "no permission". Either way, not 500.

    def test_unknown_entity_type_404(self):
        resp = self.client.get("/api/pages/edit-history/not-a-real-type/anything/")
        assert resp.status_code == 404, resp.content


# ---------------------------------------------------------------------------
# 3. Startup check: malformed LinkableModel subclasses fail manage.py check
# ---------------------------------------------------------------------------
#
# We can't easily declare deliberately-broken Django models inside a test
# (Django's ``ModelBase`` enforces too much at class-creation time), so we
# exercise the check function directly with hand-crafted stand-in classes
# that quack like a Django ``_meta``.


class _FakeMeta:
    abstract = False

    def __init__(self, fields: dict[str, object]) -> None:
        self._fields = fields

    def get_field(self, name: str) -> object:
        try:
            return self._fields[name]
        except KeyError as err:
            from django.core.exceptions import FieldDoesNotExist

            raise FieldDoesNotExist(name) from err


class TestStartupCheck:
    """``apps.core.checks.check_linkable_models`` enforces the contract."""

    def test_real_subclasses_pass(self):
        """Every concrete LinkableModel currently in the codebase passes."""
        errors = check_linkable_models(app_configs=None)
        assert errors == [], errors

    def test_check_rejects_non_unique_public_id_field(self, monkeypatch):
        """A LinkableModel pointing public_id_field at a non-unique field fails."""
        # Build a stand-in subclass tree manipulating __subclasses__ via a
        # fresh marker class. We attach _FakeMeta so _check_one's
        # ``model._meta.get_field`` path works.
        non_unique = models.SlugField(max_length=20, unique=False)
        non_unique.name = "slug"

        class BadModel:
            __name__ = "BadModel"
            entity_type = "bad-model"
            entity_type_plural = "bad-models"
            public_id_field = "slug"
            _meta = _FakeMeta({"slug": non_unique})

        from apps.core import checks as checks_mod

        seen_t: dict[str, type] = {}
        seen_p: dict[str, type] = {}
        errors = checks_mod._check_one(BadModel, seen_t, seen_p)
        assert any(isinstance(e, Error) and e.id == "core.E105" for e in errors), errors

    def test_check_rejects_unknown_field(self):
        """``public_id_field`` referencing a missing field fails."""

        class UnknownField:
            __name__ = "UnknownField"
            entity_type = "unknown-field"
            entity_type_plural = "unknown-fields"
            public_id_field = "no_such_field"
            _meta = _FakeMeta({})

        from apps.core import checks as checks_mod

        errors = checks_mod._check_one(UnknownField, {}, {})
        assert any(isinstance(e, Error) and e.id == "core.E104" for e in errors), errors

    def test_check_rejects_missing_entity_type(self):
        """A concrete LinkableModel that forgot to declare ``entity_type``
        passes ``__init_subclass__`` (which treats absence as
        abstract-intermediate) but must fail the system check, since Django
        sees it as concrete."""
        slug_field = models.SlugField(max_length=20, unique=True)
        slug_field.name = "slug"

        class MissingEntityType:
            __name__ = "MissingEntityType"
            entity_type = None
            entity_type_plural = "missings"
            public_id_field = "slug"
            _meta = _FakeMeta({"slug": slug_field})

        from apps.core import checks as checks_mod

        errors = checks_mod._check_one(MissingEntityType, {}, {})
        assert any(isinstance(e, Error) and e.id == "core.E106" for e in errors), errors

    def test_check_rejects_missing_entity_type_plural(self):
        """A concrete LinkableModel that forgot to declare
        ``entity_type_plural`` must fail the system check, even when
        ``entity_type`` is set."""
        slug_field = models.SlugField(max_length=20, unique=True)
        slug_field.name = "slug"

        class MissingPlural:
            __name__ = "MissingPlural"
            entity_type = "missing-plural"
            entity_type_plural = ""
            public_id_field = "slug"
            _meta = _FakeMeta({"slug": slug_field})

        from apps.core import checks as checks_mod

        errors = checks_mod._check_one(MissingPlural, {}, {})
        assert any(isinstance(e, Error) and e.id == "core.E107" for e in errors), errors

    def test_check_rejects_blank_public_id_field(self):
        """``public_id_field`` set to an empty string fails."""

        class BlankField:
            __name__ = "BlankField"
            entity_type = "blank-field"
            entity_type_plural = "blank-fields"
            public_id_field = ""
            _meta = _FakeMeta({})

        from apps.core import checks as checks_mod

        errors = checks_mod._check_one(BlankField, {}, {})
        assert any(isinstance(e, Error) and e.id == "core.E103" for e in errors), errors


# ---------------------------------------------------------------------------
# 4. Location plugs in via the contract
# ---------------------------------------------------------------------------


class TestLocationLinkability:
    """Location adopts ``LinkableModel`` with a multi-segment public_id."""

    def test_location_is_linkable(self):
        from apps.catalog.models import Location

        assert issubclass(Location, LinkableModel)
        assert Location.entity_type == "location"
        assert Location.entity_type_plural == "locations"
        assert Location.public_id_field == "location_path"

    def test_location_link_url_pattern(self):
        from apps.catalog.models import Location

        assert Location.link_url_pattern == "/locations/{public_id}"

    def test_location_public_id_returns_location_path(self, db):
        from apps.catalog.models import Location

        loc = Location.objects.create(
            location_path="usa/il/chicago",
            slug="chicago",
            name="Chicago",
            status="active",
        )
        assert loc.public_id == "usa/il/chicago"
        assert loc.get_absolute_url() == "/locations/usa/il/chicago"
