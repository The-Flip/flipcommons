"""Own-media gallery consolidation for entity detail serializers.

A ``MediaSupportedModel``'s own uploaded-media gallery is uniform across every
such entity — ``serialize_uploaded_media(all_media(x))`` into the
``OwnMediaSchema.uploaded_media`` field — so the engine owns it rather than each
domain serializer hand-weaving the same line. ``own_media`` is the generic
decorator that fills the field; ``assert_own_media_detail_schema`` is the
registration-time guard the detail registrar uses to enforce the mixin.

The injection point is the *serializer*, not a registrar: one detail serializer
per entity is shared across the detail-page GET, the create ``201``, the restore
``200`` and the hand-wired PATCH ``.../claims/`` route, so filling the gallery at
the serializer is the only chokepoint all four share. Thumbnail/hero are *not*
handled here — they are domain (MachineModel derives them from ``extra_data``;
others borrow cross-entity) and stay in the per-entity serializers.
"""

from __future__ import annotations

import functools
from collections.abc import Callable

from django.db.models import Model
from ninja import Schema

from apps.media.helpers import all_media
from apps.media.models import MediaSupportedModel
from apps.media.selectors import serialize_uploaded_media

from ..schemas import OwnMediaSchema


def own_media[ModelT: Model, SchemaT: Schema](
    model_cls: type[ModelT],
) -> Callable[[Callable[[ModelT], SchemaT]], Callable[[ModelT], SchemaT]]:
    """Decorate a detail serializer to fill the entity's own-media gallery.

    For a ``MediaSupportedModel``, the returned wrapper runs the inner
    serializer and then fills ``OwnMediaSchema.uploaded_media`` from the
    entity's prefetched media. For any other model it returns the serializer
    unchanged (a discovered-capability no-op).

    Apply once per media-supporting entity; the decorated callable is what the
    detail / create / delete-restore registrars and the PATCH route all
    serialize through, so every path emits the gallery without per-path wiring.

    Preconditions (not statically checkable here, so enforced elsewhere):

    * the entity's ``detail_qs`` applies ``media_prefetch()`` — every path
      refetches through it before serializing, and ``all_media`` asserts it;
    * the entity's detail schema inherits ``OwnMediaSchema`` —
      ``register_entity_detail_page`` asserts this at registration (import
      time) via :func:`assert_own_media_detail_schema`.
    """
    is_media = issubclass(model_cls, MediaSupportedModel)

    def decorate(
        serialize: Callable[[ModelT], SchemaT],
    ) -> Callable[[ModelT], SchemaT]:
        if not is_media:
            return serialize

        @functools.wraps(serialize)
        def wrapped(obj: ModelT) -> SchemaT:
            result = serialize(obj)
            # The detail schema inherits OwnMediaSchema (registration guard);
            # narrow a separate name so ``result`` keeps its ``SchemaT`` type
            # for the return while we fill the engine-owned field in place.
            media_schema = result
            assert isinstance(media_schema, OwnMediaSchema), (
                f"{model_cls.__name__} is a MediaSupportedModel; its detail "
                f"serializer must return an OwnMediaSchema subclass."
            )
            media_schema.uploaded_media = serialize_uploaded_media(all_media(obj))
            return result

        return wrapped

    return decorate


def assert_own_media_detail_schema(
    model_cls: type[Model], response_schema: type[Schema]
) -> None:
    """Enforce, at registration, that a media model's detail schema carries the
    gallery field.

    A ``MediaSupportedModel`` whose detail schema does not inherit
    ``OwnMediaSchema`` would leave :func:`own_media` with no field to fill. This
    promotes that wiring slip from a first-request ``AssertionError`` to an
    import-time ``TypeError`` (registration runs at import), matching the
    project's registration-site-error standard.
    """
    if issubclass(model_cls, MediaSupportedModel) and not issubclass(
        response_schema, OwnMediaSchema
    ):
        raise TypeError(
            f"{model_cls.__name__} is a MediaSupportedModel; its detail "
            f"response_schema {response_schema.__name__} must inherit "
            f"OwnMediaSchema."
        )
