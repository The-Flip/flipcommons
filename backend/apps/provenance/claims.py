"""Claim construction: build claim keys/values and canonicalize claim inputs.

These are the generic, model-agnostic helpers every claim write path shares —
the interactive editor, the data-patch front end and the resolution layer.
They live in provenance (the layer that owns :class:`~apps.provenance.models.Claim`
and the relationship-schema registry) so a patch alias and an editor alias
fold to byte-identical claims by construction.

Claim *validation* lives in :mod:`apps.provenance.validation`; claim *ranking*
in :mod:`apps.provenance.claim_ranking_in_db`; member *presence* in
:mod:`apps.provenance.claim_presence`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import NamedTuple

from apps.core.types import JsonBody
from apps.provenance.models import IdentityPart, make_claim_key
from apps.provenance.validation import get_relationship_schema


class RelationshipClaim(NamedTuple):
    """A ``(claim_key, value)`` pair ready to write as a relationship Claim row.

    ``claim_key`` is the canonical compound string; ``value`` is the JSONField
    payload — identity fields plus ``exists``, optionally ``category`` /
    ``is_primary``. A ``NamedTuple`` so the two positions are labelled at the
    type level while staying tuple-unpackable (``claim_key, value = ...``).
    """

    claim_key: str
    value: JsonBody


class AliasIdentity(NamedTuple):
    """The canonical fold of one raw alias string.

    ``value`` is the lowercased identity (drives the claim_key); ``display``
    is the original-case rendering stored in ``alias_display``. Both the
    in-app editor (``plan_alias_claims``) and the data-patch adapter build
    alias claims through this one fold so their bytes are identical by
    construction — a patch alias and an editor alias supersede/dedup against
    each other only if the (value, display) pair matches exactly.
    """

    value: str
    display: str


def normalize_alias_identity(raw: str) -> AliasIdentity:
    """Canonical alias fold: strip, lowercase for identity, keep original case."""
    s = raw.strip()
    return AliasIdentity(value=s.lower(), display=s)


def normalize_abbreviation_value(raw: str) -> str:
    """Canonical abbreviation fold: strip only — abbreviations are case-sensitive."""
    return raw.strip()


def normalize_fk_value(value: object) -> str | None:
    """Canonicalize an FK claim value to its public_id lookup key.

    The single normalization an FK claim value passes through before it becomes a
    public_id lookup: cast to ``str`` and trim. A falsy or whitespace-only value
    resolves to nothing (``None``). Shared by both FK-*resolution* lookups —
    catalog's ``_resolve_fk_generic`` (apply-time) and the patch front end's
    ``_lookup_pk`` (build-time create/member resolution) — so a padded or
    non-string value can't normalize one way and look up another.

    Distinct from the FK-*existence* check in :mod:`apps.provenance.validation`,
    which answers a different question — does the value name an existing row —
    and keeps its own slug normalization.
    """
    if not value:
        return None
    return str(value).strip() or None


def build_relationship_claim(
    field_name: str,
    identity: Mapping[str, IdentityPart],
    exists: bool = True,
) -> RelationshipClaim:
    """Return ``(claim_key, value)`` for a relationship claim.

    ``identity`` contains the identity fields for this relationship, e.g.,
    ``{"person": 42, "role": 5}`` or ``{"alias_value": "foo"}``. Keys are
    value-dict names (``alias_value``), not identity labels (``alias``) —
    the mapping is resolved via ``ValueKeySpec.identity``. The mapping may
    also carry non-identity keys (e.g. ``alias_display``) for an assert.

    The claim_key is derived from identity using the registered schema for
    *field_name*.

    Tombstone invariant: when ``exists=False`` the value carries **only** the
    schema-identity keys plus ``exists`` — any non-identity payload in
    *identity* is dropped. No resolver reads a non-identity key off an absent
    member (they short-circuit on ``exists=False`` first), so dropping it keeps
    tombstone bytes canonical and lets every write path supersede/dedup
    byte-identically. This is a no-op for callers that already pass
    identity-only dicts on removal (all of them, today).
    """
    schema = get_relationship_schema(field_name)
    if schema is None:
        raise ValueError(f"Unknown relationship namespace: {field_name!r}")

    identity_parts: dict[str, IdentityPart] = {}
    identity_key_names: list[str] = []
    for spec in schema.value_keys:
        if spec.identity is None:
            continue
        if spec.name not in identity:
            raise ValueError(f"Missing required key {spec.name!r} for {field_name!r}")
        identity_parts[spec.identity] = identity[spec.name]
        identity_key_names.append(spec.name)
    claim_key = make_claim_key(field_name, **identity_parts)
    value: JsonBody
    if exists:
        value = {**identity, "exists": True}
    else:
        value = {name: identity[name] for name in identity_key_names}
        value["exists"] = False
    return RelationshipClaim(claim_key, value)


__all__ = [
    "AliasIdentity",
    "RelationshipClaim",
    "build_relationship_claim",
    "normalize_abbreviation_value",
    "normalize_alias_identity",
    "normalize_fk_value",
]
