"""Cross-app shared types."""

from __future__ import annotations

from collections.abc import Mapping
from typing import NamedTuple, TypedDict

# JSON-shaped dict — object keys, arbitrary JSON values. ``object`` (not
# ``Any``) forces callers to isinstance-narrow before use, which matches
# the free-form-but-typed nature of JSON.
#
# ``JsonBody`` (invariant dict): test-client request/response bodies.
# ``JsonData`` (covariant Mapping): read-only views of JSON — function
# params that only read, e.g. ``extra_data`` JSONField contents. A
# covariant alias is needed because dict literals like
# ``{"k": [1, 2]}`` have inferred type ``dict[str, list[int]]``, which
# is not a subtype of ``dict[str, object]`` but is a subtype of
# ``Mapping[str, object]``.
type JsonBody = dict[str, object]
type JsonData = Mapping[str, object]


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


class EntityKey(NamedTuple):
    """Hashable reference to a catalog entity via content-type + object id.

    Used both as a dict key and as the input shape for helpers that fan out
    across content types (e.g. ``batch_resolve_entities``).
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
