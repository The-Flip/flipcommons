"""
The named scalar types are transparent aliases (``type X = …``); they document
intent without changing interop with the bare ``int``/``str`` the Django ORM returns.
"""

from __future__ import annotations

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
