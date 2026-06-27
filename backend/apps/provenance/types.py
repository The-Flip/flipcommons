"""
The named types here are transparent aliases (``type X = …``); they document
intent without changing interop with the bare ``int``/``str``/``dict`` the Django
ORM and JSONField return.
"""

from __future__ import annotations

from collections.abc import Mapping

type IngestSourceId = int
"""The primary key of an Ingest Source — the non-human Actor, such as the data
patch pipeline or a bot, to which a claim may be attributed."""

type ChangeSetId = int
"""The primary key of a ChangeSet — the atomic, attributed edit in which a
claim was written or retracted."""

type IngestRunId = int
"""The primary key of an IngestRun — the bulk import to which a change belongs,
which marks it as ingested rather than interactively created by a human."""

type ClaimValueKey = str
"""Names one slot inside a relationship claim's value — the person and role of a
credit, the count of a gameplay feature. The schema fixes which slots form member
identity and which carry payload."""

type RelationshipClaimValue = Mapping[ClaimValueKey, object]
"""A relationship claim's stored value payload: the namespace-specific slots its
ValueKeySpecs declare, plus the ``exists`` presence flag. Values are deliberately
wide — an FK pk (``int``), a literal identity (``str``), a payload scalar
(``int``/``bool``/``None``) — with schema validation fixing the per-slot shape at
the write boundary."""
