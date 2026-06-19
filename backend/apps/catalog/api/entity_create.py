"""Shared helpers for user-driven catalog record creation.

Title Create was the first instance of the pattern; Model Create is the
second. These helpers were extracted once a second caller existed to
prove the shape fits more than one entity. Subsequent record types (Person,
Manufacturer, …) should reuse these rather than copy-pasting.

What lives here:

* Slug format validation (regex + length).
* Generic name / slug availability pre-checks parameterized by model class
  and an optional scope filter (for entities whose collision rules are
  scoped, e.g. Model names are scoped to parent Title).
* A ``create_entity_with_claims`` wrapper that owns the transactional unit
  of work: row creation, ChangeSet + claims, and TOCTOU-safe translation
  of a DB unique-constraint violation into a field-level slug error.

What does not live here: name normalization (see ``apps.catalog.engine.naming``),
rate limiting (see ``apps.provenance.rate_limits``), or the claim
machinery itself (see :mod:`apps.claim_edit.claim_write`).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.db import IntegrityError, transaction
from django.db import models as db_models
from django.db.models import Q

from apps.catalog.engine.naming import normalize_catalog_name
from apps.catalog.models import AliasModel
from apps.claim_edit.claim_write import (
    ClaimSpec,
    execute_claims,
)
from apps.core.exceptions import StructuredValidationError
from apps.core.models import IdentifiableModel, LifecycleStatusModel, meta_unique_fields
from apps.core.validators import SLUG_FORMAT_MESSAGE, SLUG_RE
from apps.provenance.models import (
    ChangeSetAction,
    LinkableClaimModel,
    LinkableLifecycleClaimModel,
)
from apps.provenance.schemas import CitationReferenceInputSchema

from .schemas import EntityCreateInputSchema

_UserLike = AbstractBaseUser | AnonymousUser

MAX_SLUG_LENGTH = 300


def validate_slug_format(slug: str) -> str:
    """Return *slug* stripped, or raise a field-level 422 on bad shape."""
    slug = (slug or "").strip()
    if not slug:
        raise StructuredValidationError(
            message="Slug cannot be blank.",
            field_errors={"slug": "Slug cannot be blank."},
        )
    if len(slug) > MAX_SLUG_LENGTH:
        raise StructuredValidationError(
            message="Slug too long.",
            field_errors={
                "slug": f"Slug must be {MAX_SLUG_LENGTH} characters or fewer."
            },
        )
    if not SLUG_RE.match(slug):
        raise StructuredValidationError(
            message="Invalid slug.",
            field_errors={"slug": SLUG_FORMAT_MESSAGE},
        )
    return slug


def validate_name(name: str, *, max_length: int) -> str:
    """Return *name* stripped, or raise a field-level 422 on blank/overlong."""
    name = (name or "").strip()
    if not name:
        raise StructuredValidationError(
            message="Name cannot be blank.",
            field_errors={"name": "Name cannot be blank."},
        )
    if len(name) > max_length:
        raise StructuredValidationError(
            message="Name too long.",
            field_errors={"name": f"Name must be {max_length} characters or fewer."},
        )
    return name


def _resolve_alias_relation(
    model_cls: type[db_models.Model],
) -> tuple[type[AliasModel], str] | None:
    """Return ``(alias_model, parent_fk_name)`` if *model_cls* exposes an
    ``aliases`` reverse manager, else ``None``.

    Catalog alias models inherit from :class:`apps.catalog.models.AliasModel`
    (value column + ``related_name="aliases"`` on the parent FK). Using
    ``_meta.related_objects`` instead of ``getattr`` on the class keeps
    the lookup robust across model reloads and avoids hardcoding FK
    field names per entity (``theme``, ``reward_type``, ``feature``, …).
    """
    for rel in model_cls._meta.related_objects:
        if rel.get_accessor_name() == "aliases":
            related_model = rel.related_model
            assert isinstance(related_model, type)
            assert issubclass(related_model, AliasModel)
            return related_model, rel.field.name
    return None


def assert_name_available(
    model_cls: type[LifecycleStatusModel],
    name: str,
    *,
    normalize: Callable[[str], str],
    scope_filter: Q | None = None,
    exclude_pk: int | None = None,
    friendly_label: str,
    include_deleted: bool = False,
) -> None:
    """Raise a field-level 422 if *name* collides with an existing record.

    Names are compared after passing through *normalize* — typically
    :func:`apps.catalog.engine.naming.normalize_catalog_name`. The normalization
    rule is shared with the frontend so the UI's "search returned zero
    results" signal and the API's enforcement stay in sync.

    *scope_filter* narrows the collision set. ``None`` means "all active
    records" (Title). For Model, pass ``Q(title_id=title.pk)`` so two
    titles can legitimately share a model name.

    *friendly_label* is the noun shown to the user, e.g. "title" or
    "model": "A model named 'Pro' already exists."

    *include_deleted* extends the collision scan to soft-deleted rows.
    Required for any entity whose ``name`` column is DB-unique (e.g.
    ``System.name``, ``Manufacturer.name``): a name that collides with a
    soft-deleted row would otherwise pass this pre-check and trip the DB
    unique constraint, which ``create_entity_with_claims`` misreports as a
    slug collision. With this flag set, the collision surfaces as a
    field-level name error before the insert is attempted.

    The alias-collision scan below does NOT follow ``include_deleted`` —
    it continues to filter ``parent__status=active``. Aliases have their
    own uniqueness (per-parent), separate from the parent ``name`` UNIQUE
    constraint, so they don't contribute to the IntegrityError this flag
    exists to prevent. If a future entity needs alias collisions against
    soft-deleted parents to count, extend both scans together.

    When *model_cls* exposes an ``aliases`` reverse manager (Theme,
    GameplayFeature, RewardType, …), aliases of active parents also count
    as collisions because aliases behave like alternate names for
    duplicate-prevention purposes.
    """
    normalized = normalize(name)
    if not normalized:
        raise StructuredValidationError(
            message="Name cannot be blank.",
            field_errors={"name": "Name cannot be blank."},
        )

    manager = model_cls._default_manager
    qs = manager.all() if include_deleted else manager.active()
    if scope_filter is not None:
        qs = qs.filter(scope_filter)
    # ``name`` is a field only on concrete subclasses — the abstract
    # ``LifecycleStatusModel`` bound carries none — so the django-stubs plugin
    # can't see it here (see ``LabeledModel`` for the rationale).
    for pk, other_name in qs.values_list("pk", "name"):  # type: ignore[misc]
        if exclude_pk is not None and pk == exclude_pk:
            continue
        if normalize(other_name) == normalized:
            raise StructuredValidationError(
                message="Name collision.",
                field_errors={
                    "name": (
                        f"A {friendly_label} named {other_name!r} already "
                        "exists. Pick a disambiguating name."
                    )
                },
            )

    alias_rel = _resolve_alias_relation(model_cls)
    if alias_rel is None:
        return
    alias_model, parent_fk_name = alias_rel
    alias_qs = alias_model._default_manager.filter(
        **{f"{parent_fk_name}__status": "active"}
    )
    if scope_filter is not None:
        # Rewrite the scope filter so it applies to the alias's parent.
        alias_qs = alias_qs.filter(
            _rewrite_scope_for_alias(scope_filter, parent_fk_name)
        )
    for parent_pk, alias_value in alias_qs.values_list(f"{parent_fk_name}_id", "value"):
        if exclude_pk is not None and parent_pk == exclude_pk:
            continue
        if normalize(alias_value) == normalized:
            raise StructuredValidationError(
                message="Name collision.",
                field_errors={
                    "name": (
                        f"An alias {alias_value!r} already points at an "
                        f"existing {friendly_label}. Pick a disambiguating name."
                    )
                },
            )


def _rewrite_scope_for_alias(scope_filter: Q, parent_fk_name: str) -> Q:
    """Prefix each leaf lookup in *scope_filter* with ``{parent_fk_name}__``.

    The caller's ``scope_filter`` targets fields on the parent model
    (``title_id=...``); when applied against the alias table those same
    fields live behind the FK to the parent.
    """

    def _walk(node: Q) -> Q:
        new = Q()
        new.connector = node.connector
        new.negated = node.negated
        for child in node.children:
            if isinstance(child, Q):
                new.children.append(_walk(child))
            else:
                # ``Q.children`` holds nested ``Q`` nodes or ``(lookup,
                # value)`` tuples. After the ``Q`` check above, the only
                # remaining shape is the tuple — the assert narrows for
                # mypy and tripwires any future django-internals shape
                # change.
                assert isinstance(child, tuple)
                lookup, value = child
                new.children.append((f"{parent_fk_name}__{lookup}", value))
        return new

    return _walk(scope_filter)


def validate_create_input(
    data: EntityCreateInputSchema,
    model_cls: type[LinkableLifecycleClaimModel],
    *,
    scope_filter: Q | None = None,
    include_deleted_name_check: bool | None = None,
) -> tuple[str, str]:
    """Run the standard name + slug validation suite for a create.

    Composes :func:`validate_name`, :func:`validate_slug_format`, and
    :func:`assert_name_available` against ``data.name`` / ``data.slug``,
    deriving ``name`` max-length and the ``include_deleted_name_check``
    default from ``model_cls`` metadata. Returns the validated
    ``(name, slug)`` tuple; raises 422 on any failure.

    *scope_filter* narrows the name-collision scan (sibling-scoped or
    root-tier checks). ``None`` means global.

    *include_deleted_name_check* defaults to ``True`` when ``name`` is
    DB-unique on the model, matching the factory's logic. Pass an
    explicit bool to override.

    This is the primitive the create factory composes; outlier entities
    that need to roll their own create handler call it directly to stay
    aligned with the standard validation phase.
    """
    # ``name`` is registered as a Django field on each concrete subclass;
    # the django-stubs plugin can't see it on the abstract
    # ``LinkableLifecycleClaimModel`` base (see ``LabeledModel`` for the
    # rationale).
    name_field = model_cls._meta.get_field("name")  # type: ignore[misc]
    assert isinstance(name_field, db_models.Field)
    name_max = name_field.max_length
    assert name_max is not None
    if include_deleted_name_check is None:
        include_deleted_name_check = bool(
            getattr(name_field, "unique", False)
        ) or "name" in meta_unique_fields(model_cls)
    friendly = model_cls.entity_type.replace("-", " ")

    name = validate_name(data.name, max_length=name_max)
    slug = validate_slug_format(data.slug)
    assert_name_available(
        model_cls,
        name,
        normalize=normalize_catalog_name,
        scope_filter=scope_filter,
        friendly_label=friendly,
        include_deleted=include_deleted_name_check,
    )
    return name, slug


def assert_public_id_available(
    model_cls: type[IdentifiableModel],
    value: str,
    *,
    form_value: str | None = None,
) -> None:
    """Raise a field-level 422 if *value* collides on the model's public-id field.

    Public-id uniqueness is DB-enforced (including against soft-deleted
    rows, whose DB rows still exist). This pre-check produces a nice
    field-scoped error for the common case; the DB constraint remains the
    authoritative backstop and is translated to the same shape by
    :func:`create_entity_with_claims` if a concurrent create wins the race.

    ``model_cls.public_id_field`` selects the column to query — ``"slug"``
    for every shipped catalog model, but Location uses ``"location_path"``
    so the freshly-built path is what's checked, not the bare slug.

    ``form_value`` (defaulting to *value*) is what the error message
    echoes back to the user. Pair with ``model_cls.public_id_form_field``
    to surface the collision under the form input the user can edit:
    for shipped models the form input *is* the public-id, so the two
    coincide; Location's public-id is server-derived from the ``slug``
    input, so the route passes ``data.slug`` as ``form_value`` and the
    error binds under ``"slug"``.
    """
    public_id_field = model_cls.public_id_field
    form_field = model_cls.public_id_form_field or public_id_field
    if form_value is None:
        form_value = value
    if model_cls._default_manager.filter(**{public_id_field: value}).exists():
        raise StructuredValidationError(
            message=f"{public_id_field.capitalize()} collision.",
            field_errors={
                form_field: (
                    f"The {form_field} {form_value!r} is already taken. "
                    f"Edit the {form_field} field."
                )
            },
        )


def create_entity_with_claims[M: LinkableClaimModel](
    model_cls: type[M],
    *,
    row_kwargs: dict[str, Any],
    claim_specs: list[ClaimSpec],
    user: _UserLike,
    note: str = "",
    citation: CitationReferenceInputSchema | None = None,
) -> M:
    """Create a new catalog row + its initial claims atomically.

    * Opens a ``transaction.atomic`` block so that a claim-write failure
      rolls the row back (and vice versa).
    * Creates the row via ``model_cls.objects.create(**row_kwargs)``.
    * Writes a user ChangeSet with ``action=create`` and the given
      *claim_specs* via :func:`apps.claim_edit.claim_write.execute_claims`.
    * Translates a DB ``IntegrityError`` on the slug into the same
      field-level 422 that the pre-check produces. This covers the tiny
      TOCTOU window between ``assert_public_id_available`` and the insert.

    Callers are responsible for name/slug validation and rate-limiting
    before invoking this helper. ``row_kwargs`` must contain a value for
    ``model_cls.public_id_field`` — the unique-constrained column this
    helper expects to be writing, whose value is echoed into the TOCTOU
    fallback error.

    .. warning::

        The IntegrityError handler unconditionally reports a public-id
        collision. Reaching it implies a TOCTOU race (the matching
        pre-check just succeeded), so in practice the misreport surfaces
        only when a name-uniqueness or CHECK constraint trips here
        instead — paths that require concurrent writes or callers
        bypassing the pre-checks. The user can retry; the pre-check will
        then produce the right field-level message. If those paths
        become common, swap this for constraint-name-based dispatch.
    """
    public_id_field = model_cls.public_id_field
    public_id_value = row_kwargs[public_id_field]
    form_field = model_cls.public_id_form_field or public_id_field
    # ``form_field`` and ``public_id_field`` coincide for every shipped
    # model (both ``"slug"``); on Location the form input is ``slug`` and
    # the public-id is the server-derived ``location_path``. Pull the
    # form-side value from row_kwargs when available so the echoed
    # collision message reads "slug 'chicago'", not "slug 'usa/il/chicago'".
    form_value = row_kwargs.get(form_field, public_id_value)
    try:
        with transaction.atomic():
            entity = model_cls._default_manager.create(**row_kwargs)
            execute_claims(
                entity,
                claim_specs,
                user=user,
                action=ChangeSetAction.CREATE,
                note=note,
                citation=citation,
            )
    except IntegrityError as err:
        raise StructuredValidationError(
            message=f"{public_id_field.capitalize()} collision.",
            field_errors={
                form_field: (
                    f"The {form_field} {form_value!r} is already taken. "
                    f"Edit the {form_field} field."
                )
            },
        ) from err
    return entity
