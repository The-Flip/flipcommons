"""Focused tests for the ``register_entity_create`` registrar.

The behavioral tests for ``scope_filter_builder`` live alongside real
callers (CorporateEntity create — parented sibling-scope; Location create
— unparented root-tier scope, once Location lands). This file covers
contract guards and tight tests for the extension hooks (``body_schema``,
``extra_create_fields_builder``) that don't require live entity wiring.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.core.cache import cache
from django.db.models import Q
from django.test import RequestFactory
from ninja import Router, Schema

from apps.catalog.api.schemas import EntityCreateInputSchema
from apps.catalog.engine.entity_api.create import CreateExtras, register_entity_create
from apps.catalog.models import Theme
from apps.claim_edit.claim_write import ClaimSpec
from apps.provenance.models import Claim

User = get_user_model()


class DummySchema(Schema):
    pass


def _registered_handler(router: Router):
    """Return the (single) view function the factory registered."""
    (path_view,) = router.path_operations.values()
    (op,) = path_view.operations
    return op.view_func


def test_parented_without_parent_model_still_raises():
    """Existing guard: parent_field without parent_model / route_suffix."""
    router = Router()
    with pytest.raises(TypeError, match="parent_model and route_suffix are required"):
        register_entity_create(
            router,
            Theme,
            detail_qs=lambda: Theme.objects.all(),
            serialize_detail=lambda _t: DummySchema(),
            response_schema=DummySchema,
            parent_field="parent",
        )


def test_body_schema_must_subclass_entity_create_input():
    """``body_schema`` runtime guard: passing a non-conforming Schema
    (e.g. raw ``ninja.Schema``) must raise at registration so a dynamic
    caller bypassing mypy can't ship a 500-on-first-request route."""
    router = Router()
    with pytest.raises(TypeError, match="body_schema must subclass"):
        register_entity_create(
            router,
            Theme,
            detail_qs=lambda: Theme.objects.all(),
            serialize_detail=lambda _t: DummySchema(),
            response_schema=DummySchema,
            body_schema=DummySchema,  # type: ignore[arg-type]  # intentional
        )


def test_body_schema_overrides_data_annotation():
    """``body_schema`` replaces ``EntityCreateInputSchema`` on the
    registered handler. Ninja reads this annotation to pick the body
    parser, so overriding ``__annotations__["data"]`` is the contract."""

    class CustomBody(EntityCreateInputSchema):
        extra: str = ""

    router = Router()
    register_entity_create(
        router,
        Theme,
        detail_qs=lambda: Theme.objects.all(),
        serialize_detail=lambda _t: DummySchema(),
        response_schema=DummySchema,
        body_schema=CustomBody,
    )
    handler = _registered_handler(router)
    assert handler.__annotations__["data"] is CustomBody


def test_body_schema_default_is_entity_create_input_schema():
    """Without ``body_schema``, the data annotation stays
    ``EntityCreateInputSchema`` so existing callers are byte-identical."""
    router = Router()
    register_entity_create(
        router,
        Theme,
        detail_qs=lambda: Theme.objects.all(),
        serialize_detail=lambda _t: DummySchema(),
        response_schema=DummySchema,
    )
    handler = _registered_handler(router)
    assert handler.__annotations__["data"] is EntityCreateInputSchema


# ── extra_create_fields_builder: behavioural ────────────────────────


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def _invoke(handler, user, **body_overrides):
    """Call a registered unparented create handler directly.

    Bypasses Ninja routing/auth — the factory mounts ``auth=django_auth``
    at the route layer, but the inner ``_do_create`` only needs an
    authenticated ``request.user`` for the rate limiter.
    """
    body = {"name": "T", "slug": "t", "note": "", "citation": None}
    body.update(body_overrides)
    request = RequestFactory().post("/")
    request.user = user
    data = handler.__annotations__["data"](**body)
    return handler(request, data)


@pytest.mark.django_db
def test_scope_filter_builder_unparented_invoked(user):
    """Unparented ``scope_filter_builder`` is invoked with ``parent=None``
    and its returned ``Q`` is consumed without error. Catches the realistic
    failure modes (lambda silently dropped, wrong arg threading, API
    mismatch); doesn't try to prove the ``Q`` literally reaches
    ``assert_name_available`` because that would require white-box
    monkey-patching for diminishing return on a 5-line code path."""
    seen: dict[str, object] = {}

    def _scope(_data, parent):
        seen["called"] = True
        seen["parent"] = parent
        return Q()

    router = Router()
    register_entity_create(
        router,
        Theme,
        detail_qs=lambda: Theme.objects.all(),
        serialize_detail=lambda _t: DummySchema(),
        response_schema=DummySchema,
        scope_filter_builder=_scope,
    )
    handler = _registered_handler(router)
    _invoke(handler, user, name="UnparentedScopeTest", slug="unparented-scope-test")

    assert seen["called"] is True
    assert seen["parent"] is None


@pytest.mark.django_db
def test_extra_create_fields_builder_row_kwargs_and_claims_reach_row(user):
    """The ``CreateExtras`` returned by the builder is merged into row
    kwargs and appended to the claim list. Mirrors the realistic Location
    pattern where ``location_type`` lands as both a row column and a claim
    — without a matching claim, the post-create claim resolver would reset
    the column to default. This test exercises both halves at once: the
    row column survives resolution iff both halves are wired correctly."""

    def _build_extras(data, parent):
        assert parent is None  # unparented Theme registration
        description = f"auto: {data.name}"
        return CreateExtras(
            row_kwargs={"description": description},
            claim_specs=[ClaimSpec(field_name="description", value=description)],
        )

    router = Router()
    register_entity_create(
        router,
        Theme,
        detail_qs=lambda: Theme.objects.all(),
        serialize_detail=lambda _t: DummySchema(),
        response_schema=DummySchema,
        extra_create_fields_builder=_build_extras,
    )
    handler = _registered_handler(router)
    _invoke(handler, user, name="AutoThemed", slug="autothemed")

    theme = Theme.objects.get(slug="autothemed")
    assert theme.description == "auto: AutoThemed"
    ct = ContentType.objects.get_for_model(Theme)
    fields = {
        c.field_name for c in Claim.objects.filter(content_type=ct, object_id=theme.pk)
    }
    assert "description" in fields
