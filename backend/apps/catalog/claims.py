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
from django.core.validators import MinValueValidator
from django.db.models import CharField, ForeignKey, IntegerField, Model

from apps.core.types import ClaimFieldName
from apps.media.models import MediaSupportedModel
from apps.provenance.claims import RelationshipClaim, build_relationship_claim
from apps.provenance.model_bases import (
    ClaimRelationshipBinding,
    MemberField,
    PayloadField,
    all_relationship_bindings,
)
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

    The explicit through-model namespaces (theme, tag, reward_type,
    gameplay_feature, credit, abbreviation, location, and the self-referential
    parents theme_parent/gameplay_feature_parent) are *derived* from the
    ``claim_relationship_spec`` ClassVar on each ``ClaimThroughModel`` — one
    schema per namespace, see :func:`_register_through_model_schemas`. The two
    that have no through-model — aliases (case-folded) and media (content-type
    keyed) — are still declared by hand here.
    """
    from apps.media.models import MediaAsset

    from .engine.aliases import discover_alias_types

    # Derived from the through-model specs.
    _register_through_model_schemas()

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
# Through-model schema derivation
# ---------------------------------------------------------------------------


def _register_through_model_schemas() -> None:
    """Derive one ``RelationshipSchema`` per namespace from the through-model specs.

    Groups every relationship binding by namespace (spec→schema is many-to-one),
    derives the value-keys from each binding's through-model + spec by
    introspecting ``_meta``, requires every binding in a namespace to derive
    identical value-keys (the cross-model parity check — e.g. ``abbreviation``'s
    two through-models must agree on ``max_length``), then registers one schema
    with the union of the group's subjects. The XOR-subject credit namespace
    yields two bindings on one through-model, so its subjects union to
    ``{MachineModel, Series}``.
    """
    by_namespace: dict[ClaimFieldName, list[ClaimRelationshipBinding]] = {}
    for binding in all_relationship_bindings():
        by_namespace.setdefault(binding.spec.namespace, []).append(binding)

    for namespace, bindings in by_namespace.items():
        value_keys_per_binding = [_value_keys_for(b) for b in bindings]
        canonical = value_keys_per_binding[0]
        for other, binding in zip(
            value_keys_per_binding[1:], bindings[1:], strict=True
        ):
            assert other == canonical, (
                f"namespace {namespace!r}: bindings "
                f"{bindings[0].through_model.__name__}/"
                f"{bindings[0].subject_model.__name__} and "
                f"{binding.through_model.__name__}/{binding.subject_model.__name__} "
                f"derive different value-keys ({canonical!r} != {other!r})"
            )
        register_relationship_schema(
            namespace=namespace,
            value_keys=canonical,
            valid_subjects={b.subject_model for b in bindings},
            xor_groups=_xor_groups_for(bindings[0]),
        )


def _xor_groups_for(
    binding: ClaimRelationshipBinding,
) -> tuple[tuple[str, ...], ...] | None:
    """The spec's ``MemberXor`` groups translated from field names to value keys.

    The spec declares groups in through-model column names (consistent with
    ``members``); the validator operates on value-dict keys, so squished columns
    (``rewardtype`` keyed as ``reward_type``) translate through
    ``member.value_key``. Multi-binding namespaces share one through-model spec,
    so any binding yields the same groups.
    """
    member_xor = binding.spec.member_xor
    if member_xor is None:
        return None
    key_by_field = {m.field: (m.value_key or m.field) for m in binding.spec.members}
    return tuple(
        tuple(key_by_field[field] for field in group) for group in member_xor.groups
    )


def _value_keys_for(binding: ClaimRelationshipBinding) -> tuple[ValueKeySpec, ...]:
    """The value-key specs a binding's spec implies — members then payload."""
    through = binding.through_model
    members = tuple(_member_value_key(through, m) for m in binding.spec.members)
    payload = tuple(_payload_value_key(through, p) for p in binding.spec.payload)
    return members + payload


def _member_value_key(through_model: type[Model], member: MemberField) -> ValueKeySpec:
    """Derive an identity value-key from a through-model member field.

    The value-key ``name`` is the value-dict key (``member.value_key or
    member.field``) — *not* the column — so a squished FK column (``rewardtype``
    keyed as ``reward_type``) keeps its value-dict name. An FK member carries an
    ``fk_target`` (its target model introspected from the relation, never named
    in the spec); a literal ``CharField`` member carries its ``max_length``.
    """
    field = through_model._meta.get_field(member.field)
    name = member.value_key or member.field
    if isinstance(field, ForeignKey):
        target = field.related_model
        assert not isinstance(target, str)  # resolved to a class once apps are ready
        # A nullable member's key is still required — always present in the
        # value dict, with null expressing absence — so the canonical claim_key
        # covers every identity part ("null" included).
        return ValueKeySpec(
            name=name,
            scalar_type=int,
            required=True,
            nullable=member.nullable,
            identity=member.identity,
            fk_target=FkTarget(target, member.lookup_field),
        )
    assert isinstance(field, CharField), (
        f"{through_model.__name__}.{member.field} must be a ForeignKey or CharField"
    )
    max_length = field.max_length
    assert max_length is not None, (
        f"{through_model.__name__}.{member.field} must declare a max_length"
    )
    return ValueKeySpec(
        name=name,
        scalar_type=str,
        required=True,
        identity=member.identity,
        max_length=max_length,
    )


def _payload_value_key(
    through_model: type[Model], payload: PayloadField
) -> ValueKeySpec:
    """Derive a non-identity payload value-key (gameplay ``count``,
    model-relationship ``relationship_type``/``license_status``).

    Integer payloads: the lower bound is harvested from the field's own
    ``MinValueValidator`` so the patch adapter rejects a too-small payload at
    plan time (see ``ValueKeySpec.min_value``). No symmetric *upper* bound is
    derived: ``PositiveSmallIntegerField`` declares no ``MaxValueValidator``,
    only the backend integer range — which SQLite (the patch author's local DB)
    reports as the full 64-bit range, not Postgres's 32767 — so a meaningful max
    is not model-derivable and an over-large payload falls through to a Postgres
    range error in prod (the same reason ``max_length`` is the only string bound
    we pre-check).

    String payloads: ``max_length`` and the field's ``choices`` vocabulary (when
    declared) carry over, so an out-of-vocab value fails validation rather than
    deferring to the DB CHECK.
    """
    field = through_model._meta.get_field(payload.field)
    name = payload.value_key or payload.field
    if isinstance(field, CharField):
        max_length = field.max_length
        assert max_length is not None, (
            f"{through_model.__name__}.{payload.field} must declare a max_length"
        )
        choices = (
            tuple(str(value) for value, _label in field.flatchoices)
            if field.choices
            else None
        )
        return ValueKeySpec(
            name=name,
            scalar_type=str,
            required=payload.required,
            nullable=payload.nullable,
            max_length=max_length,
            choices=choices,
        )
    assert isinstance(field, IntegerField), (
        f"{through_model.__name__}.{payload.field} payload must be an "
        f"IntegerField or CharField"
    )
    min_value = max(
        (
            int(v.limit_value)
            for v in field.validators
            if isinstance(v, MinValueValidator)
        ),
        default=None,
    )
    assert min_value is not None, (
        f"{through_model.__name__}.{payload.field} must declare a MinValueValidator"
    )
    return ValueKeySpec(
        name=name,
        scalar_type=int,
        required=payload.required,
        nullable=payload.nullable,
        min_value=min_value,
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
