"""Cross-app shared types."""

from __future__ import annotations

from collections.abc import Mapping
from typing import NamedTuple, TypedDict

# ---------------------------------------------------------------------------
# JSON payloads
# ---------------------------------------------------------------------------

type JsonBody = dict[str, object]
"""A JSON object as an invariant dict — string keys, arbitrary JSON values.
``object`` (not ``Any``) forces callers to isinstance-narrow before use. For
read-write payloads, e.g. test-client request/response bodies."""

type JsonData = Mapping[str, object]
"""A read-only, covariant view of a JSON object — for params that only read it,
e.g. ``extra_data`` contents. Covariant because a dict literal like
``{"k": [1, 2]}`` is a ``Mapping[str, object]`` but not a ``dict[str, object]``."""


# ---------------------------------------------------------------------------
# Claim and entity identity scalars
# ---------------------------------------------------------------------------

type ContentTypeId = int
"""The primary key of a Django ContentType — the entity-type half of a claim's
polymorphic target."""

type ClaimSubjectId = int
"""The primary key of the entity a claim is about — the subject its claims are
grouped and resolved under."""

type ClaimKey = str
"""Identifies one assertable slot on an entity: a scalar field, or a single
member of a relationship set. The unit a winner is picked for."""

type ClaimFieldName = str
"""Identifies which claim-controlled field an assertion targets — a scalar
column, an FK, or the shared namespace of a relationship's members."""

type ClaimFieldMap = dict[ClaimFieldName, str]
"""Maps each claim-controlled field name to the model attribute it resolves into."""

type ClaimValueKey = str
"""Names one slot inside a relationship claim's value — the person and role of a
credit, the count of a gameplay feature. The schema fixes which slots form member
identity and which carry payload."""

type IdentityPartName = str
"""One key in a claim_key's identity-parts mapping — the label of an identity
slot (e.g. ``person``, ``role``, ``alias``). Distinct from the relationship
value-dict key it derives from: usually equal, occasionally not (``alias`` for
the ``alias_value`` slot)."""

type ColumnName = str
"""A through-table column, FK attribute, or model field name. The element type of
the resolution engine's ``ColumnNames = tuple[ColumnName, ...]``."""

type PublicId = str
"""An entity's URL-identity: the value of its public_id field, by which an FK or
relationship member names its target. It's usually a slug, but is a path for
hierarchical entities like Location, whose nesting a flat slug can't express."""


# ---------------------------------------------------------------------------
# Primary keys of models owned by other apps
#
# Parked here (rather than beside their models) so annotation-only importers
# stay dependency-free: a leaf alias never drags in the owning Django model.
# ---------------------------------------------------------------------------

type LicenseId = int
"""The primary key of a License — the reuse terms attached to a claim's value."""

type CitationSourceId = int
"""The primary key of a Citation Source — a citable work (book, web page) to
which evidence (aka Citation Instances) attach."""

type CitationInstanceId = int
"""The primary key of a CitationInstance — one use of a CitationSource at a
point in text. Distinct from ``CitationSourceId`` (the cited work itself)."""

type UserId = int
"""The primary key of a User — the human account behind an interactive action.
Distinct from an ``Actor`` (the provenance attribution); a claim's author is a
User, but ingest-authored claims have a null one."""


# ---------------------------------------------------------------------------
# Identity tuples
# ---------------------------------------------------------------------------


class EntityKey(NamedTuple):
    """Hashable reference to a catalog entity via content-type + object id.

    Used both as a dict key and as the input shape for helpers that fan out
    across content types (e.g. ``build_entity_links``).
    """

    content_type_id: ContentTypeId
    object_id: ClaimSubjectId


class ClaimTarget(TypedDict):
    """Spreadable form of ``EntityKey`` for ``PlannedClaimAssert(**target)`` calls.

    Same fields as ``EntityKey`` but a TypedDict because ingest adapters
    spread it into dataclass kwargs; NamedTuple doesn't unpack as ``**``.
    """

    content_type_id: ContentTypeId
    object_id: ClaimSubjectId


class ClaimIdentity(NamedTuple):
    """Hashable identity of a claim on an entity.

    Matches the ``(content_type, object_id, claim_key)`` uniqueness scope
    used by provenance writes and catalog ingest when deduplicating
    pending claims or joining against existing active rows.
    """

    content_type_id: ContentTypeId
    object_id: ClaimSubjectId
    claim_key: ClaimKey
