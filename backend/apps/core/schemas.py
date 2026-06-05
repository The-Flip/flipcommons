"""Shared Ninja schemas reused across apps."""

from __future__ import annotations

from typing import Literal

from ninja import Schema


class ErrorDetailSchema(Schema):
    """Plain 422 / 404 / 409 / 403 error body: just a ``detail`` string.

    The shared shape used for non-structured failures across endpoints.
    Structured 422s (with ``field_errors`` / ``form_errors``) come from
    :class:`apps.catalog.api.edit_claims.StructuredValidationError` and have
    their own wire format; this schema covers the simpler "detail only" case.
    """

    detail: str


class StructuredErrorBodySchema(Schema):
    """Shared base for structured-error body schemas.

    Concrete variants override ``kind`` with a ``Literal`` so each emits a
    discriminated TypeScript type via codegen. Inheritance-only — not used
    as a router ``response=`` directly.
    """

    kind: str
    message: str


class ValidationErrorBodySchema(StructuredErrorBodySchema):
    kind: Literal["validation_error"]
    field_errors: dict[str, str]
    form_errors: list[str]


class ValidationErrorSchema(Schema):
    """Structured 422 body produced by ``StructuredValidationError`` and by
    Ninja's malformed-body handler (see ``config/api.py``)."""

    detail: ValidationErrorBodySchema


class RateLimitErrorBodySchema(StructuredErrorBodySchema):
    kind: Literal["rate_limit"]
    bucket: str
    retry_after: int


class RateLimitErrorSchema(Schema):
    """Structured 429 body produced by ``RateLimitExceededError``."""

    detail: RateLimitErrorBodySchema


class EntityLinkSchema(Schema):
    """A reference to a catalog entity of unknown type.

    Carries everything needed to render a link to the entity: a pre-built
    ``href`` (the consumer can't construct it without knowing the model),
    the display ``name``, and a human-readable ``type_label``.
    """

    href: str
    name: str
    type_label: str


class LinkTypeSchema(Schema):
    """One *kind* of wikilink target (title, model, person, …) — populates
    the type selector in the wikilink picker. Targets within a chosen type
    are returned as :class:`LinkTargetSchema`.
    """

    name: str
    label: str
    description: str
    flow: str


class LinkTargetSchema(Schema):
    """One autocomplete result within a chosen :class:`LinkTypeSchema`.
    ``ref`` is the wikilink string the editor inserts.
    """

    ref: str
    label: str


class LinkTargetListSchema(Schema):
    """Response body for ``/link-types/targets/``."""

    results: list[LinkTargetSchema]


class EntityAutocompleteResultSchema(Schema):
    """One autocomplete result from ``/entity-autocomplete/``.

    ``value`` is the identity string the consumer **saves** — a ``public_id``
    (slug) for catalog entities, a ``username`` for ``user`` later. ``label`` is
    the display text; ``sublabel`` is an optional second line disambiguating
    same-labeled rows (e.g. a title's "manufacturer · year").

    Distinct from :class:`LinkTargetSchema` despite the similar shape: ``value``
    is an FK to persist, whereas ``ref`` there is a wikilink token to insert.
    Same-ish wire shape, different semantics — kept separate per ApiDesign.md.
    """

    value: str
    label: str
    sublabel: str | None = None


class EntityAutocompleteListSchema(Schema):
    """Response body for ``/entity-autocomplete/``."""

    results: list[EntityAutocompleteResultSchema]
