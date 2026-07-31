"""Tests for the engine's own-media consolidation (Phase D).

Covers the generic ``own_media`` decorator's discovered-capability dispatch and
the registration-time guard ``register_entity_detail_page`` applies for
``MediaSupportedModel`` detail routes. The per-entity wire output (the gallery
actually appearing on Person / Manufacturer / MachineModel / GameplayFeature
detail, create, restore and patch responses) is covered by those entities'
integration tests.
"""

from __future__ import annotations

import pytest
from ninja import Router, Schema

from apps.catalog.engine.entity_api.detail import (
    plain_page,
    register_entity_detail_page,
)
from apps.catalog.engine.entity_api.own_media import own_media
from apps.catalog.engine.schemas import OwnMediaSchema
from apps.catalog.models import GameplayFeature, Theme

# GameplayFeature is a MediaSupportedModel; Theme is not.


class _MediaSchema(OwnMediaSchema):
    """A detail schema that correctly inherits the gallery mixin."""


class _PlainSchema(Schema):
    """A detail schema missing the gallery mixin (a misconfiguration)."""


# ---------------------------------------------------------------------------
# Registration-time guard
# ---------------------------------------------------------------------------


def test_detail_registrar_rejects_media_model_without_mixin():
    """A MediaSupportedModel whose detail schema omits OwnMediaSchema must fail
    at registration (import time), not on the first request."""
    router = Router()
    with pytest.raises(TypeError, match="must inherit OwnMediaSchema"):
        register_entity_detail_page(
            router,
            GameplayFeature,
            detail_qs=lambda: GameplayFeature.objects.all(),
            serialize_page=plain_page(lambda _o: _PlainSchema()),
            response_schema=_PlainSchema,
        )


def test_detail_registrar_accepts_media_model_with_mixin():
    """A MediaSupportedModel whose detail schema inherits OwnMediaSchema
    registers cleanly."""
    router = Router()
    register_entity_detail_page(
        router,
        GameplayFeature,
        detail_qs=lambda: GameplayFeature.objects.all(),
        serialize_page=plain_page(lambda _o: _MediaSchema()),
        response_schema=_MediaSchema,
    )


def test_detail_registrar_ignores_non_media_model():
    """A non-media model is unaffected by the guard — its detail schema need
    not inherit OwnMediaSchema."""
    router = Router()
    register_entity_detail_page(
        router,
        Theme,
        detail_qs=lambda: Theme.objects.all(),
        serialize_page=plain_page(lambda _o: _PlainSchema()),
        response_schema=_PlainSchema,
    )


# ---------------------------------------------------------------------------
# own_media decorator
# ---------------------------------------------------------------------------


def test_own_media_is_a_noop_for_non_media_model():
    """Decorating a non-media serializer returns it unchanged."""

    def serialize(_o: object) -> _PlainSchema:
        return _PlainSchema()

    assert own_media(Theme)(serialize) is serialize


def test_own_media_fills_gallery_for_media_model():
    """For a media model, the wrapper fills uploaded_media from prefetched
    own media (empty here — non-empty is covered by integration tests)."""

    def serialize(_o: object) -> _MediaSchema:
        return _MediaSchema()

    decorated = own_media(GameplayFeature)(serialize)
    feature = GameplayFeature(name="X", slug="x")
    # media_prefetch()'s to_attr="all_media" lands in the instance __dict__;
    # populate it directly so all_media() finds an (empty) prefetched list.
    feature.__dict__["all_media"] = []
    result = decorated(feature)
    assert result.uploaded_media == []


def test_own_media_asserts_when_schema_lacks_mixin():
    """The decorator's request-time backstop: a media serializer that returns a
    schema without the mixin fails loudly rather than silently dropping media."""

    def serialize(_o: object) -> _PlainSchema:
        return _PlainSchema()

    decorated = own_media(GameplayFeature)(serialize)
    with pytest.raises(AssertionError, match="OwnMediaSchema"):
        decorated(GameplayFeature(name="X", slug="x"))
