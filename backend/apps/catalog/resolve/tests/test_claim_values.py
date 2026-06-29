"""Consistency test: TypedDicts in ``_claim_values`` mirror their registered schema.

Proves that for each TypedDict in :mod:`apps.catalog.resolve._claim_values`,
the registered :class:`RelationshipSchema` for its namespace(s) agrees on
key set, scalar type, required/optional flag, and nullability.

Limit — see CatalogResolveTyping.md Phase A: this test does NOT prove
that every resolver uses the right TypedDict for the namespace it's
resolving. A resolver casting to the wrong shape passes mypy and passes
this test. The cast site itself is the editorial checkpoint.
"""

from __future__ import annotations

import types
from typing import Union, get_args, get_origin, get_type_hints

from apps.catalog.engine.aliases import discover_alias_types
from apps.catalog.resolve._claim_values import (
    AliasClaimValue,
    MediaAttachmentClaimValue,
    ParentClaimValue,
)
from apps.provenance.validation import RelationshipSchema, get_relationship_schema


def _alias_namespaces() -> tuple[str, ...]:
    return tuple(at.claim_field for at in discover_alias_types())


# Only the bespoke shapes remain a TypedDict: aliases (case-folded), parents
# (self-referential) and media (content-type keyed). The explicit through-model
# namespaces no longer have a read-side TypedDict — their schema is derived from
# the spec and locked by ``test_through_model_schemas`` instead.
TYPEDDICT_NAMESPACES: list[tuple[type, tuple[str, ...]]] = [
    (AliasClaimValue, _alias_namespaces()),
    (ParentClaimValue, ("theme_parent", "gameplay_feature_parent")),
    (MediaAttachmentClaimValue, ("media_attachment",)),
]


def _is_nullable(annotation: object) -> bool:
    """True iff ``annotation`` is a union including ``type(None)``."""
    origin = get_origin(annotation)
    if origin is Union or origin is types.UnionType:
        return type(None) in get_args(annotation)
    return False


def _unwrap_nullable(annotation: object) -> object:
    """Return the sole non-``None`` branch of a ``T | None`` union, else the annotation.

    Raises if the union has more than one non-``None`` branch — current
    schemas never produce that shape, and this test is the place to
    notice if one ever does.
    """
    if not _is_nullable(annotation):
        return annotation
    non_none = [a for a in get_args(annotation) if a is not type(None)]
    assert len(non_none) == 1, (
        f"expected single non-None branch, got {non_none!r} for {annotation!r}"
    )
    return non_none[0]


def _check_against_schema(td: type, schema: RelationshipSchema) -> None:
    hints = get_type_hints(td)
    required = td.__required_keys__  # type: ignore[attr-defined]
    optional = td.__optional_keys__  # type: ignore[attr-defined]

    # exists is required on every TypedDict and implicit in the validator
    # (not a registered value-key).
    assert "exists" in required, f"{td.__name__} missing Required[exists]"
    assert hints["exists"] is bool, (
        f"{td.__name__}.exists must be bool, got {hints['exists']!r}"
    )

    # Key set (excluding exists) must match registered value_keys.
    td_keys = (required | optional) - {"exists"}
    schema_keys = {spec.name for spec in schema.value_keys}
    assert td_keys == schema_keys, (
        f"{td.__name__} keys {td_keys} != schema {schema.namespace!r} keys {schema_keys}"
    )

    for spec in schema.value_keys:
        annotation = hints[spec.name]
        is_required = spec.name in required
        assert is_required == spec.required, (
            f"{td.__name__}.{spec.name}: required={is_required} "
            f"but schema {schema.namespace!r} has required={spec.required}"
        )
        is_nullable = _is_nullable(annotation)
        assert is_nullable == spec.nullable, (
            f"{td.__name__}.{spec.name}: nullable={is_nullable} "
            f"but schema {schema.namespace!r} has nullable={spec.nullable}"
        )
        scalar = _unwrap_nullable(annotation)
        assert scalar is spec.scalar_type, (
            f"{td.__name__}.{spec.name}: scalar {scalar!r} "
            f"!= schema {schema.namespace!r} scalar {spec.scalar_type!r}"
        )


def test_every_typeddict_has_at_least_one_namespace() -> None:
    for td, namespaces in TYPEDDICT_NAMESPACES:
        assert namespaces, f"{td.__name__} has no associated namespaces"


def test_alias_namespaces_discovered() -> None:
    # Guards against an empty discover_alias_types() silently skipping the
    # AliasClaimValue mirror check.
    assert _alias_namespaces(), "expected at least one alias namespace"


def test_typeddicts_mirror_schemas() -> None:
    for td, namespaces in TYPEDDICT_NAMESPACES:
        for namespace in namespaces:
            schema = get_relationship_schema(namespace)
            assert schema is not None, (
                f"namespace {namespace!r} (for {td.__name__}) not registered"
            )
            _check_against_schema(td, schema)


def test_typeddicts_are_typeddicts() -> None:
    # Sanity: each entry is an actual TypedDict subclass with the
    # __required_keys__ / __optional_keys__ introspection attributes.
    for td, _ in TYPEDDICT_NAMESPACES:
        assert issubclass(td, dict), f"{td.__name__} is not a TypedDict"
        assert hasattr(td, "__required_keys__"), (
            f"{td.__name__} missing __required_keys__"
        )
        assert hasattr(td, "__optional_keys__"), (
            f"{td.__name__} missing __optional_keys__"
        )
