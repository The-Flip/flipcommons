"""Read-side TypedDict vocabulary for relationship-claim JSON payloads.

Only the bespoke shapes keep a read-side TypedDict: case-folded aliases and
content-type-keyed media. The explicit through-model namespaces (theme, credit,
abbreviation, parents, …) carry no TypedDict — their payload shape is
spec-derived and locked by ``tests/test_through_model_schemas.py`` instead. Each
surviving TypedDict mirrors its registered :class:`RelationshipSchema`; the
consistency test in ``tests/test_claim_values.py`` enforces that mirror.

Resolvers ``cast(<Shape>, claim.value)`` at the top of their loop body;
reads stay on ``.get()`` until every required relationship-payload key is
guaranteed by validation on historical and newly written claims.

``from __future__ import annotations`` is deliberately omitted — TypedDict
computes ``__required_keys__`` at class-creation time and cannot see
through stringified ``Required``/``NotRequired`` wrappers.
"""

from typing import NotRequired, Required, TypedDict


class AliasClaimValue(TypedDict):
    """Payload for ``*_alias`` relationship claims across all AliasModel subjects."""

    alias_value: Required[str]
    exists: Required[bool]
    alias_display: NotRequired[str]


class MediaAttachmentClaimValue(TypedDict):
    """Payload for ``media_attachment`` claims on every MediaSupportedModel subject."""

    media_asset: Required[int]
    exists: Required[bool]
    category: NotRequired[str | None]
    is_primary: NotRequired[bool]
