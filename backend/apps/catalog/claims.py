"""Catalog-specific relationship-claim helpers.

Domain knowledge about relationship claim shapes lives here via
``register_catalog_relationship_schemas()``, called from
``CatalogConfig.ready()``. The unified registry is owned by
``apps.provenance.validation``; this module declares the catalog namespaces
and keeps the two catalog-coupled helpers — ``build_media_attachment_claim``
(validates against the entity's ``MEDIA_CATEGORIES``) and
``make_authoritative_scope``. The generic, model-agnostic construction
helpers (``build_relationship_claim``, the normalizers) live in
``apps.provenance.claims``.
"""

from __future__ import annotations

from collections.abc import Iterable

from django.contrib.contenttypes.models import ContentType

from apps.media.models import MediaSupportedModel
from apps.provenance.claims import RelationshipClaim, build_relationship_claim
from apps.provenance.models import ClaimControlledModel
from apps.provenance.validation import (
    FkTarget,
    RelationshipSchema,
    ValueKeySpec,
    get_all_relationship_schemas,
    register_relationship_schema,
)

# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_catalog_relationship_schemas() -> None:
    """Register every catalog relationship namespace. Called from ``ready()``.

    Each namespace is declared exactly once with its value-keys and the set
    of subject models it applies to.
    """
    from apps.catalog.models import (
        CorporateEntity,
        CreditRole,
        GameplayFeature,
        Location,
        MachineModel,
        ModelAbbreviation,
        Person,
        RewardType,
        Series,
        Tag,
        Theme,
        Title,
        TitleAbbreviation,
    )
    from apps.media.models import MediaAsset

    from ._alias_registry import discover_alias_types

    # Credit: Person + CreditRole on MachineModel and Series.
    register_relationship_schema(
        namespace="credit",
        value_keys=(
            ValueKeySpec(
                name="person",
                scalar_type=int,
                required=True,
                identity="person",
                fk_target=FkTarget(Person, "pk"),
            ),
            ValueKeySpec(
                name="role",
                scalar_type=int,
                required=True,
                identity="role",
                fk_target=FkTarget(CreditRole, "pk"),
            ),
        ),
        valid_subjects={MachineModel, Series},
    )

    # Gameplay feature M2M on MachineModel — with optional integer count.
    register_relationship_schema(
        namespace="gameplay_feature",
        value_keys=(
            ValueKeySpec(
                name="gameplay_feature",
                scalar_type=int,
                required=True,
                identity="gameplay_feature",
                fk_target=FkTarget(GameplayFeature, "pk"),
            ),
            ValueKeySpec(
                name="count",
                scalar_type=int,
                required=False,
                nullable=True,
            ),
        ),
        valid_subjects={MachineModel},
    )

    # Simple M2Ms on MachineModel — theme / tag / reward_type.
    register_relationship_schema(
        namespace="theme",
        value_keys=(
            ValueKeySpec(
                name="theme",
                scalar_type=int,
                required=True,
                identity="theme",
                fk_target=FkTarget(Theme, "pk"),
            ),
        ),
        valid_subjects={MachineModel},
    )
    register_relationship_schema(
        namespace="tag",
        value_keys=(
            ValueKeySpec(
                name="tag",
                scalar_type=int,
                required=True,
                identity="tag",
                fk_target=FkTarget(Tag, "pk"),
            ),
        ),
        valid_subjects={MachineModel},
    )
    register_relationship_schema(
        namespace="reward_type",
        value_keys=(
            ValueKeySpec(
                name="reward_type",
                scalar_type=int,
                required=True,
                identity="reward_type",
                fk_target=FkTarget(RewardType, "pk"),
            ),
        ),
        valid_subjects={MachineModel},
    )

    # Abbreviation (literal) on Title + MachineModel. The stored value lives on
    # two separate through-models; read the bound from both and require they
    # agree so a future divergence fails registration instead of silently
    # picking one. Drives the data-patch over-length guard (see ValueKeySpec).
    model_abbr_len = ModelAbbreviation._meta.get_field("value").max_length
    title_abbr_len = TitleAbbreviation._meta.get_field("value").max_length
    assert model_abbr_len is not None, "ModelAbbreviation.value must declare max_length"
    assert model_abbr_len == title_abbr_len, (
        "ModelAbbreviation.value and TitleAbbreviation.value must declare the "
        f"same max_length (got {model_abbr_len!r} / {title_abbr_len!r})"
    )
    register_relationship_schema(
        namespace="abbreviation",
        value_keys=(
            ValueKeySpec(
                name="value",
                scalar_type=str,
                required=True,
                identity="value",
                max_length=model_abbr_len,
            ),
        ),
        valid_subjects={Title, MachineModel},
    )

    # Location on CorporateEntity.
    register_relationship_schema(
        namespace="location",
        value_keys=(
            ValueKeySpec(
                name="location",
                scalar_type=int,
                required=True,
                identity="location",
                fk_target=FkTarget(Location, "pk"),
            ),
        ),
        valid_subjects={CorporateEntity},
    )

    # Hierarchy parents (self-referential).
    register_relationship_schema(
        namespace="theme_parent",
        value_keys=(
            ValueKeySpec(
                name="parent",
                scalar_type=int,
                required=True,
                identity="parent",
                fk_target=FkTarget(Theme, "pk"),
            ),
        ),
        valid_subjects={Theme},
    )
    register_relationship_schema(
        namespace="gameplay_feature_parent",
        value_keys=(
            ValueKeySpec(
                name="parent",
                scalar_type=int,
                required=True,
                identity="parent",
                fk_target=FkTarget(GameplayFeature, "pk"),
            ),
        ),
        valid_subjects={GameplayFeature},
    )

    # Alias namespaces — one schema per AliasModel subclass.
    for alias_type in discover_alias_types():
        alias_value_len = alias_type.alias_model._meta.get_field("value").max_length
        assert alias_value_len is not None, (
            f"{alias_type.alias_model.__name__}.value must declare a max_length"
        )
        register_relationship_schema(
            namespace=alias_type.claim_field,
            value_keys=(
                ValueKeySpec(
                    name="alias_value",
                    scalar_type=str,
                    required=True,
                    identity="alias",
                    display_key="alias_display",
                    max_length=alias_value_len,
                ),
                ValueKeySpec(
                    name="alias_display",
                    scalar_type=str,
                    required=False,
                ),
            ),
            valid_subjects={alias_type.parent_model},
        )

    # cross-app: walks all apps intentionally — MediaSupportedModel may gain
    # non-catalog inheritors.
    from django.apps import apps as _apps

    media_subjects: set[type[ClaimControlledModel]] = {
        m
        for m in _apps.get_models()
        if issubclass(m, MediaSupportedModel) and not m._meta.abstract
    }
    register_relationship_schema(
        namespace="media_attachment",
        value_keys=(
            ValueKeySpec(
                name="media_asset",
                scalar_type=int,
                required=True,
                identity="media_asset",
                fk_target=FkTarget(MediaAsset, "pk"),
            ),
            ValueKeySpec(
                name="category",
                scalar_type=str,
                required=False,
                nullable=True,
            ),
            ValueKeySpec(
                name="is_primary",
                scalar_type=bool,
                required=False,
            ),
        ),
        valid_subjects=media_subjects,
    )


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_all_namespace_keys() -> dict[str, list[str]]:
    """Return namespace → list of identity value-key names for every namespace.

    Used by tests to verify that every namespace classifies correctly.
    """
    result: dict[str, list[str]] = {}
    for namespace, schema in get_all_relationship_schemas().items():
        result[namespace] = [
            spec.name for spec in schema.value_keys if spec.identity is not None
        ]
    return result


def build_media_attachment_claim(
    entity: MediaSupportedModel,
    asset_pk: int,
    *,
    category: str | None = None,
    is_primary: bool = False,
    exists: bool = True,
) -> RelationshipClaim:
    """Return ``(claim_key, value)`` for a ``media_attachment`` claim.

    Validates *category* against the entity's ``MEDIA_CATEGORIES`` before
    building the claim.  Raises ``ValueError`` for invalid categories.
    All code paths that create ``media_attachment`` claims should use this
    helper so that category validation happens exactly once.
    """
    model_class = type(entity)
    allowed = model_class.MEDIA_CATEGORIES
    if category is not None:
        if not allowed:
            raise ValueError(f"No media categories defined for {model_class.__name__}.")
        if category not in allowed:
            raise ValueError(
                f"Invalid category {category!r} for {model_class.__name__}. "
                f"Allowed: {', '.join(allowed)}."
            )

    claim_key, value = build_relationship_claim(
        "media_attachment",
        {"media_asset": asset_pk},
        exists=exists,
    )
    # Non-identity payload only on an assert. A detach tombstone carries the
    # identity (media_asset) + exists only — honoring build_relationship_claim's
    # tombstone invariant; the resolver skips an exists=False claim before it
    # would read category/is_primary anyway.
    if exists:
        value["category"] = category
        value["is_primary"] = is_primary
    return RelationshipClaim(claim_key, value)


def make_authoritative_scope(
    model_class: type[ClaimControlledModel],
    object_ids: Iterable[int],
) -> set[tuple[int, int]]:
    """Build an authoritative_scope set from a model class and object IDs.

    Convenience wrapper for the common single-content-type case used by
    ingest commands.
    """
    ct_id = ContentType.objects.get_for_model(model_class).pk
    return {(ct_id, obj_id) for obj_id in object_ids}


# Public surface. ``RelationshipSchema`` / ``ValueKeySpec`` are re-exported
# because this module instantiates them; downstream code should import from
# whichever module they already use.
__all__ = [
    "RelationshipSchema",
    "ValueKeySpec",
    "build_media_attachment_claim",
    "get_all_namespace_keys",
    "make_authoritative_scope",
    "register_catalog_relationship_schemas",
]
