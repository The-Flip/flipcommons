"""
The named types here are transparent aliases (``type X = …``); they document
intent without changing interop with the bare ``int``/``str``/``dict`` the Django
ORM and JSONField return.
"""

from __future__ import annotations

from collections.abc import Mapping

# ClaimValueKey lives in apps.core.types (the dependency-free leaf); imported here
# only because RelationshipClaimValue below is defined in terms of it. Do not
# remove this import — RelationshipClaimValue needs it in scope.
from apps.core.types import ClaimValueKey

type IngestSourceId = int
"""The primary key of an Ingest Source — the non-human Actor, such as the data
patch pipeline or a bot, to which a claim may be attributed."""

type ChangeSetId = int
"""The primary key of a ChangeSet — the atomic, attributed edit in which a
claim was written or retracted."""

type ClaimId = int
"""The primary key of a Claim row — one assertion's identity in the provenance
ledger. Distinct from ``ClaimSubjectId`` (the entity the claim is *about*) and
``ClaimKey`` (the slot it asserts); this names the assertion record itself."""

type IngestRunId = int
"""The primary key of an IngestRun — the bulk import to which a change belongs,
which marks it as ingested rather than interactively created by a human."""

type RelationshipClaimValue = Mapping[ClaimValueKey, object]
"""A relationship claim's stored value payload: the namespace-specific slots its
ValueKeySpecs declare, plus the ``exists`` presence flag. Values are deliberately
wide — an FK pk (``int``), a literal identity (``str``), a payload scalar
(``int``/``bool``/``None``) — with schema validation fixing the per-slot shape at
the write boundary."""
