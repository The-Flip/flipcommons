"""Typing protocols and small typed shapes for catalog API query plumbing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple, Protocol, TypedDict


class FacetOptionDict(TypedDict):
    """The JSON-serializable twin of ``schemas.FacetOptionSchema`` — a faceted
    listing page's ``{public_id, name, count}`` option as a **plain dict**.

    The facet page payload is assembled as plain dicts (not Schema instances) so the
    cache's ``json.dumps`` fast path and the live path stay byte-equivalent (see
    ``set_cached_response``). This names that dict's shape so the assembly isn't typed
    as a faceless ``dict[str, object]``; ``set_cached_response`` still validates the
    whole payload against the Ninja schema in DEBUG.
    """

    public_id: str
    name: str
    count: int


class HasModelCount(Protocol):
    model_count: int


class CorporateEntityListAnnotations(Protocol):
    """Annotations the corporate-entity list queryset adds to each row:
    the model count and the production-span year bounds."""

    model_count: int
    year_of_first_model: int | None
    year_of_last_model: int | None


class HasTitleCount(Protocol):
    title_count: int


class HasCreditCount(Protocol):
    credit_count: int


class SlugName(NamedTuple):
    """A (slug, name) pair for a facet ref pulled in bulk from ``values_list``.

    Used throughout list-endpoint assembly where we collect slug+display-name
    pairs per row (tech generations, themes, gameplay features, etc.) without
    the overhead of a full Schema instance.
    """

    slug: str
    name: str


class CreditKey(NamedTuple):
    """A credit identified by (person_slug, role_slug) — the input-side key."""

    person_slug: str
    role_slug: str


class CreditPkKey(NamedTuple):
    """A credit identified by (person_pk, role_pk) — the DB-side key."""

    person_pk: int
    role_pk: int


@dataclass(frozen=True, slots=True)
class GameplayFeatureAgreement:
    """Per-feature agreement value in the agreed-specs intersection.

    Keyed by feature slug in the surrounding dict; carries the display name
    and per-model count (``None`` when counts disagree across models).
    A frozen dataclass rather than a NamedTuple because the field name
    ``count`` would shadow ``tuple.count``.
    """

    name: str
    count: int | None
