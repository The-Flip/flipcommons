"""Shared SSR-detail-page registrar for any ``SitemappedModel`` subclass.

Mounts ``GET /{entity_type}/{public_id}`` on a Ninja router. The route
segment comes from ``model_cls.entity_type``; the lookup field from
``model_cls.public_id_field``; the ``last_modified`` annotation from
``model_cls.lastmod_expression()`` (the ``LastUpdatedModel`` half of
``SitemappedModel``). ``{public_id}`` uses the Ninja ``path`` converter so
multi-segment ids round-trip through one registration. The bound is
``SitemappedModel`` (addressing + freshness) rather than a claim base
because the body reads no claims — serialization is caller-injected.

Used exclusively by :mod:`apps.catalog.api.page_endpoints`; lives next to
:mod:`apps.catalog.api.entity_crud` (both register routes over addressable
entities) but shares no helpers with the write registrars, so it stays in
its own module.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from django.db.models import QuerySet
from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from apps.core.models import SitemappedModel

from ..own_media import assert_own_media_detail_schema


def register_entity_detail_page[ModelT: SitemappedModel, SchemaT: Schema](
    router: Router,
    model_cls: type[ModelT],
    *,
    detail_qs: Callable[[], QuerySet[ModelT]],
    serialize_detail: Callable[[ModelT], SchemaT],
    response_schema: type[SchemaT],
) -> None:
    """Mount ``GET /{entity_type}/{public_id}`` on *router*.

    Replaces the per-entity boilerplate of ``get_object_or_404`` +
    serializer + response_schema for SSR detail pages mounted under
    ``/api/pages/``.

    For a ``MediaSupportedModel``, asserts at registration that
    *response_schema* inherits ``OwnMediaSchema`` — the gallery field the
    ``own_media`` decorator fills — so a missing mixin fails at import, not on
    the first request.
    """
    assert_own_media_detail_schema(model_cls, response_schema)
    entity_type = model_cls.entity_type
    public_id_field = model_cls.public_id_field

    def _detail(request: HttpRequest, public_id: str) -> SchemaT:
        _ = request
        # Annotate the freshness value from the one shared definition
        # (``LastUpdatedModel.lastmod_expression()``) so the detail response's
        # ``last_modified`` and the sitemap's ``<lastmod>`` can't disagree —
        # including ``Title``'s child-Model aggregation. ``last_modified``
        # (the model property) reads this ``_last_modified`` annotation.
        # ``.annotate()`` widens the queryset's element type to a
        # ``WithAnnotations[...]`` variant in django-stubs; the row is still a
        # ``ModelT`` instance at runtime (with an extra ``_last_modified`` attr
        # the model's ``last_modified`` property reads), so cast it back.
        annotated_qs = detail_qs().annotate(
            _last_modified=model_cls.lastmod_expression()
        )
        obj = cast(
            "ModelT", get_object_or_404(annotated_qs, **{public_id_field: public_id})
        )
        return serialize_detail(obj)

    _detail.__name__ = f"{entity_type.replace('-', '_')}_detail_page"
    router.get(
        f"/{entity_type}/{{path:public_id}}",
        response=response_schema,
    )(_detail)
