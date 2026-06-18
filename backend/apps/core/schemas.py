"""Shared Ninja schemas reused across apps."""

from __future__ import annotations

from typing import Literal

from ninja import Field, Schema


class ErrorDetailSchema(Schema):
    """Plain 422 / 404 / 409 / 403 error body: just a ``detail`` string."""

    # The shared shape for non-structured failures. Structured 422s (with
    # ``field_errors`` / ``form_errors``) come from
    # ``apps.core.exceptions.StructuredValidationError`` and have their
    # own wire format; this schema covers the simpler "detail only" case.
    detail: str = Field(description="A human-readable error message.")


class StructuredErrorBodySchema(Schema):
    """Shared base for structured-error body schemas."""

    # Concrete variants override ``kind`` with a ``Literal`` so each emits a
    # discriminated TypeScript type via codegen. Inheritance-only — not used as a
    # router ``response=`` directly.
    kind: str = Field(description="Discriminator identifying the kind of error.")
    message: str = Field(description="A human-readable summary of the error.")


class ValidationErrorBodySchema(StructuredErrorBodySchema):
    """Structured 422 error body for validation failures."""

    kind: Literal["validation_error"] = Field(
        description='Discriminator; always "validation_error".'
    )
    field_errors: dict[str, str] = Field(
        description="Error messages keyed by the input field they apply to."
    )
    form_errors: list[str] = Field(
        description="Form-level errors not tied to any single field."
    )


class ValidationErrorSchema(Schema):
    """Structured 422 body produced by ``StructuredValidationError`` and by
    Ninja's malformed-body handler (see ``config/api.py``)."""

    detail: ValidationErrorBodySchema = Field(description="The validation error body.")


class RateLimitErrorBodySchema(StructuredErrorBodySchema):
    """Structured 429 error body for rate-limit failures."""

    kind: Literal["rate_limit"] = Field(
        description='Discriminator; always "rate_limit".'
    )
    bucket: str = Field(
        description="The rate-limit bucket that was exceeded (create, edit, delete, export etc)."
    )
    retry_after: int = Field(description="Seconds to wait before retrying the request.")


class RateLimitErrorSchema(Schema):
    """Structured 429 body produced by ``RateLimitExceededError``."""

    detail: RateLimitErrorBodySchema = Field(description="The rate-limit error body.")


class EntityLinkSchema(Schema):
    """A reference to a catalog entity of unknown type."""

    # Carries everything needed to render a link without knowing the model: a
    # pre-built ``href`` the consumer can't construct itself, plus display text.
    href: str = Field(description="Ready-to-use URL path to the entity's page.")
    name: str = Field(description="The entity's display name.")
    type_label: str = Field(
        description='Human-readable entity type, e.g. "Title" or "Machine Model".'
    )


class LinkTypeSchema(Schema):
    """One kind of wikilink target (title, model, person, …) — populates the
    type selector in the wikilink picker."""

    # Targets within a chosen type are returned as ``LinkTargetSchema``.
    name: str = Field(
        description='Identifier for this link type (e.g. "title", "person").'
    )
    label: str = Field(description="Human-readable name shown in the type picker.")
    description: str = Field(
        description="Explanation of what this type targets, shown in the picker."
    )
    flow: str = Field(
        description=(
            'How targets are chosen for this type: "standard" uses the shared '
            'autocomplete search; "custom" uses a type-specific frontend flow '
            "(e.g. citations)."
        )
    )


class LinkTargetSchema(Schema):
    """One autocomplete result within a chosen :class:`LinkTypeSchema`."""

    ref: str = Field(
        description="The wikilink reference the editor inserts for this target."
    )
    label: str = Field(description="Display text for the result.")


class LinkTargetListSchema(Schema):
    """Response body for ``/link-types/targets/``."""

    results: list[LinkTargetSchema] = Field(description="The matching link targets.")


class EntityAutocompleteResultSchema(Schema):
    """One autocomplete result from ``/entity-autocomplete/``."""

    # Distinct from ``LinkTargetSchema`` despite the similar shape: ``value`` is
    # an FK identity to persist, whereas ``LinkTargetSchema.ref`` is a wikilink
    # token to insert. Same-ish wire shape, different semantics — kept separate
    # per ApiDesign.md.
    value: str = Field(
        description="The identity string to save for this entity — its public id (a slug for most entities, a location path for Location)."
    )
    label: str = Field(description="Display text for the result.")
    sublabel: str | None = Field(
        None,
        description="Optional second line disambiguating same-labeled results (e.g. a title's manufacturer and year).",
    )


class EntityAutocompleteListSchema(Schema):
    """Response body for ``/entity-autocomplete/``."""

    results: list[EntityAutocompleteResultSchema] = Field(
        description="The matching autocomplete results."
    )
