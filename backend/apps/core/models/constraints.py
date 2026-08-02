"""CHECK / UNIQUE constraint helpers used by models across all apps."""

from __future__ import annotations

from django.db import models
from django.db.models.functions import Lower

from .mixins import EntityStatus


def field_not_blank(field_name: str) -> models.CheckConstraint:
    """CHECK constraint: field != ''. Use in concrete model Meta.constraints."""
    return models.CheckConstraint(
        condition=~models.Q(**{field_name: ""}),
        name=f"%(app_label)s_%(class)s_{field_name}_not_blank",
    )


def field_lowercase(field_name: str) -> models.CheckConstraint:
    """CHECK constraint: field equals its own lowercased form.

    Asserts ``field = LOWER(field)`` — a column equals itself only when
    no character has a distinct lowercase form, which means there are no
    uppercase letters present (ASCII or Unicode). Pure SQL, portable
    across PostgreSQL and SQLite, and enforced even when the database is
    opened by a tool that doesn't load Django's regex function.

    Generic helper for any field that must be lowercase by shape (slugs,
    derived path strings like Location.location_path, etc.). For slug
    fields on SluggedModel subclasses use ``slug_lowercase()`` instead —
    the constraint is identical, the helper just hardcodes the field name.

    Once values are guaranteed lowercase, plain ``unique=True`` already
    collapses case-equal rows; no Lower()-wrapped UniqueConstraint needed.
    Pair with ``unique_ci()`` only when the field is mixed-case (names),
    not when it's lowercase-shape (slugs, paths).
    """
    return models.CheckConstraint(
        condition=models.Q(**{field_name: Lower(field_name)}),
        name=f"%(app_label)s_%(class)s_{field_name}_lowercase",
    )


def unique_ci(field_name: str) -> models.UniqueConstraint:
    """Case-insensitive UniqueConstraint on a single field.

    System-wide rule: name-like uniqueness collapses case. Use in Meta
    constraints in place of ``unique=True`` so ``"Bally"`` and ``"BALLY"``
    cannot both exist.
    """
    return models.UniqueConstraint(
        Lower(field_name),
        name=f"%(app_label)s_%(class)s_unique_{field_name}_ci",
    )


def meta_unique_fields(model_class: type[models.Model]) -> set[str]:
    """Names of fields referenced by any Meta ``UniqueConstraint``.

    Covers both ``fields=[...]`` and expression-based forms like
    ``UniqueConstraint(Lower("name"))`` — both make the underlying field
    behave as unique even though ``field.unique`` is False. Walks
    expression trees and picks up ``F`` references; other expression
    nodes are ignored.
    """
    names: set[str] = set()

    def _collect(expr: object) -> None:
        if isinstance(expr, models.F):
            names.add(expr.name)  # type: ignore[attr-defined]  # django-stubs omits F.name
        children = getattr(expr, "get_source_expressions", None)
        if callable(children):
            for child in children():
                _collect(child)

    for constraint in model_class._meta.constraints:
        if not isinstance(constraint, models.UniqueConstraint):
            continue
        for fname in constraint.fields or ():
            names.add(fname)
        for expr in constraint.expressions or ():
            _collect(expr)
    return names


def self_fk_field_names(model_class: type[models.Model]) -> tuple[str, ...]:
    """Names of *model_class*'s concrete self-referential FKs, in field order.

    Structural, not semantic: this answers "does this field point back at its
    own model", which Django already knows. What such a reference *means*
    (lineage, bookkeeping) is a separate question no introspection can settle
    — see ``MachineModel.self_fk_roles``.

    The single source of truth for the self-FK set: the ``not_self`` constraint
    audit, the API self-reference guard and the edge vocabulary all read it
    here, so a newly added self-FK reaches every one of them at once.
    """
    return tuple(
        f.name
        for f in model_class._meta.fields
        if f.is_relation and f.related_model is model_class
    )


def self_fk_not_self(field_name: str, *, message: str) -> models.CheckConstraint:
    """CHECK constraint: a self-referential FK is NULL or points elsewhere.

    Every self-FK in the system carries one — ``test_self_fk_constraints``
    walks the app registry and fails if a new one doesn't. *message* is the
    reader-facing wording and is required: "cannot be its own variant" and
    "cannot be a remake of itself" are not derivable from the field name.

    ``violation_error_code`` is load-bearing, not decoration. The claim
    resolver validates exactly those CheckConstraints that carry one
    (``apps.catalog.resolve``), which is what turns a self-reference into a
    clean 422 naming the field instead of a raw ``IntegrityError`` reported
    as a unique-constraint violation.
    """
    return models.CheckConstraint(
        condition=models.Q(**{f"{field_name}__isnull": True})
        | ~models.Q(**{field_name: models.F("pk")}),
        name=f"%(app_label)s_%(class)s_{field_name}_not_self",
        violation_error_message=message,
        violation_error_code="cross_field",
    )


def nullable_id_not_empty(field_name: str) -> models.CheckConstraint:
    """CHECK constraint: nullable string ID is NULL or non-empty.

    Prevents '' on optional unique CharField IDs (opdb_id, wikidata_id),
    which would consume the unique slot while being semantically null.
    """
    return models.CheckConstraint(
        condition=models.Q(**{f"{field_name}__isnull": True})
        | ~models.Q(**{field_name: ""}),
        name=f"%(app_label)s_%(class)s_{field_name}_not_empty",
    )


def slug_not_blank() -> models.CheckConstraint:
    """CHECK constraint: slug != ''. Use in each SluggedModel subclass Meta."""
    return models.CheckConstraint(
        condition=~models.Q(slug=""),
        name="%(app_label)s_%(class)s_slug_not_blank",
    )


def slug_lowercase() -> models.CheckConstraint:
    """CHECK constraint: slug equals its own lowercased form.

    Slug-specific specialization of :func:`field_lowercase`. Use in each
    SluggedModel subclass Meta alongside ``slug_not_blank()``. Plain
    ``unique=True`` on the slug field is sufficient — case-sensitive
    uniqueness already collapses case-equal rows once values are
    guaranteed lowercase.
    """
    return models.CheckConstraint(
        condition=models.Q(slug=Lower("slug")),
        name="%(app_label)s_%(class)s_slug_lowercase",
    )


def status_valid() -> models.CheckConstraint:
    """CHECK constraint: status must be 'active', 'deleted', or null."""
    return models.CheckConstraint(
        condition=(
            models.Q(status__in=[EntityStatus.ACTIVE, EntityStatus.DELETED])
            | models.Q(status__isnull=True)
        ),
        name="%(app_label)s_%(class)s_status_valid",
    )
