"""API schemas for the provenance app.

Used by api.py and the page-oriented changes endpoints (page_endpoints.py).

Claim payloads are stored as JSON (``Claim.value`` is a ``JSONField``), so
the ``raw`` field of :class:`ClaimValueSchema` (used wherever a claim
value crosses the wire — ``old_value`` / ``new_value`` / ``value``) is
typed as ``object``: it carries scalars, dicts, lists, or null depending
on the claim kind, and the catalog-level schema is what actually
constrains each field's shape.
"""

from __future__ import annotations

from typing import Annotated, ClassVar, Literal

from django.db.models import Model
from ninja import Field, Schema

from apps.core.authz import Activity

from .models import (
    CHANGESET_NOTE_MAX_LENGTH,
    CITATION_INSTANCE_LOCATOR_MAX_LENGTH,
    ChangeSet,
)

ClaimDisplayIdentityState = Literal["resolved", "deleted", "missing"]
"""Discriminant for :class:`ClaimDisplayIdentityPartSchema`.

See that schema for what each value implies about the surrounding fields.
"""


class ClaimDisplayIdentityPartSchema(Schema):
    """One identity slot of a relationship claim's user-facing rendering.

    ``key`` names the identity ``ValueKeySpec`` (e.g. ``"person"``,
    ``"alias_value"``).

    ``state`` (see :data:`ClaimDisplayIdentityState`) discriminates three cases that
    frontends typically want to render differently:

    - ``"resolved"``: the backend produced a real label; ``label`` is the
      non-empty user-facing string.
    - ``"deleted"``: the claim references an FK target row that no longer
      exists in the catalog (e.g. a Person was removed after the claim
      was made). Legitimate runtime condition; ``label`` is null.
    - ``"missing"``: the claim dict didn't carry this identity key at
      all — an invariant violation that validation should have prevented.
      Backend logs loudly when this happens; ``label`` is null.

    No default on ``state``: every construction must pick one. Defaulting
    to ``"resolved"`` would let ``ClaimDisplayIdentityPartSchema(key=..., label=None)``
    construct silently with an incoherent ``(resolved, null)`` pair.
    """

    key: str
    label: str | None
    state: ClaimDisplayIdentityState


class ClaimDisplayQualifierPartSchema(Schema):
    """One qualifier on a relationship claim's user-facing rendering.

    ``key`` names a non-identity ``ValueKeySpec`` (e.g. ``"count"``,
    ``"category"``, ``"is_primary"``); ``value`` is the raw scalar so the
    frontend can apply per-key rendering rules (``count > 1``, ``is_primary
    === true``, etc.).

    Union ordering is **most specific first**: ``bool`` before ``int``
    because ``bool`` is an ``int`` subclass and Pydantic v2's default union
    resolution would otherwise coerce ``True`` into ``1``, silently breaking
    frontend ``v === true`` checks.
    """

    key: str
    value: bool | int | str | None = None


class ClaimDisplayValueSchema(Schema):
    """Structured user-facing rendering of a relationship-claim value.

    ``identity`` and ``qualifiers`` are lists (not dicts) so declaration
    order is part of the wire format, not an implicit dict-insertion-order
    contract. Direct-field scalar claims and non-relationship namespaces
    have no ``ClaimDisplayValueSchema`` — the frontend falls back to the raw
    ``old_value`` / ``new_value`` in that case.
    """

    identity: list[ClaimDisplayIdentityPartSchema]
    qualifiers: list[ClaimDisplayQualifierPartSchema]


class ClaimValueSchema(Schema):
    """A claim value paired with its structured user-facing rendering.

    ``raw`` is the JSONField payload (scalar/dict/list/null). ``display`` is
    the structured rendering for relationship claims (see
    :class:`ClaimDisplayValueSchema`) or ``None`` when there's no
    structured rendering — direct-field scalars, unknown namespaces,
    non-dict values. Clients fall back to ``raw`` when ``display`` is null.
    """

    raw: object
    display: ClaimDisplayValueSchema | None = None


class FieldChangeSchema(Schema):
    """A single field change within a ChangeSet (old -> new).

    ``old_value`` / ``new_value`` are :class:`ClaimValueSchema` — each
    bundles the raw JSON payload with its structured display rendering.

    ``old_value`` is null in two cases that this wire format does not
    distinguish: (1) no prior claim exists in the chain, or (2) a prior
    claim exists but its value is JSON null.
    """

    field_name: str
    claim_key: str
    old_value: ClaimValueSchema | None = None
    new_value: ClaimValueSchema
    claim_id: int | None = None
    claim_user_id: int | None = None
    is_active: bool | None = None
    is_winning: bool | None = None
    is_retracted: bool | None = None


class RetractionSchema(Schema):
    """A claim that was retracted (not superseded) within a ChangeSet.

    Distinct from :class:`FieldChangeSchema`: a retraction removes a prior
    claim without replacing it, so there is no ``new_value``.
    """

    claim_id: int
    field_name: str
    claim_key: str
    old_value: ClaimValueSchema


class ClaimUserAuthorSchema(Schema):
    """A Claim/ChangeSet authored by a user."""

    kind: Literal["user"] = "user"
    username: str


class ClaimSourceAuthorSchema(Schema):
    """A Claim/ChangeSet attributed to an ingest source."""

    kind: Literal["source"] = "source"
    name: str


ClaimAuthorSchema = Annotated[
    ClaimUserAuthorSchema | ClaimSourceAuthorSchema,
    Field(discriminator="kind"),
]
"""Tagged union: a Claim/ChangeSet is authored by exactly one of a user or
an ingest source. Mirrors the DB-level XOR CHECK constraints
(``provenance_claim_source_xor_user``,
``provenance_changeset_user_xor_ingest_run``) on the wire."""


class ClaimAttributionSchema(Schema):
    """Who asserted a Claim and when."""

    author: ClaimAuthorSchema
    created_at: str


class ChangeSetBaseSchema(Schema):
    """Common fields for any read-side ChangeSet representation."""

    id: int
    attribution: ClaimAttributionSchema
    note: str


class ChangeSetSchema(ChangeSetBaseSchema):
    """A grouped edit session with per-field diffs.

    ``capabilities`` is the wire contract for every ChangeSet row variant
    in the codebase — see also ``ChangeSetSummarySchema``,
    ``ChangeSetDetailSchema``, ``CitedChangeSetSchema``, and
    ``UserChangeSetSchema``. The contract:

    Each entry answers "is the caller authorized to *attempt* this
    activity on this row" — it is **not** a guarantee the action will
    succeed. ``capabilities['changeset.undo'] is True`` only means the
    policy lets this caller call the undo endpoint with this changeset;
    the endpoint additionally enforces operational invariants
    (``action == DELETE``, claims not superseded) that aren't expressible
    as pure-attribute policy predicates and so don't reflect on the wire.

    A future per-row Undo UI MUST AND the embedded verdict with operational
    eligibility before rendering an affordance, or design a separate
    operational-eligibility wire field at that time.
    """

    changes: list[FieldChangeSchema]
    retractions: list[RetractionSchema] = []
    capabilities: dict[Activity, bool] = Field(default_factory=dict)

    # Declared on each concrete row variant (not on the base) — the
    # ``authz.E101–E106`` system check reads these from ``__dict__``,
    # so inherited declarations don't trigger the structural check.
    policy_activities: ClassVar[tuple[Activity, ...]] = (Activity.CHANGESET_UNDO,)
    policy_target_model: ClassVar[type[Model]] = ChangeSet


class ClaimSchema(Schema):
    """A single per-field claim as surfaced to the Sources UI."""

    attribution: ClaimAttributionSchema
    field_name: str
    value: ClaimValueSchema
    citation: str
    is_winner: bool
    changeset_note: str | None = None


class CitationReferenceInputSchema(Schema):
    """Reference an existing CitationInstance to clone onto a user edit."""

    citation_instance_id: int


class ChangeSetInputSchema(Schema):
    """Base shape for any user-attributed mutation that produces a ChangeSet."""

    note: Annotated[str, Field(max_length=CHANGESET_NOTE_MAX_LENGTH)] = ""
    citation: CitationReferenceInputSchema | None = None


class AttributionSchema(Schema):
    """License and source attribution for rendered content."""

    license_slug: str | None = None
    license_name: str | None = None
    license_url: str | None = None
    permissiveness_rank: int | None = None
    requires_attribution: bool = False
    source_name: str | None = None
    source_url: str | None = None
    attribution_text: str | None = None


class ReviewLinkSchema(Schema):
    """A link out to an external page relevant to a needs-review item."""

    label: str
    url: str


class CitationLinkSchema(Schema):
    """A link attached to a citation source."""

    url: str
    label: str


class InlineCitationSchema(Schema):
    """Metadata for an inline citation in rendered markdown."""

    id: int
    index: int
    source_name: str
    source_type: str
    author: str
    year: int | None = None
    locator: str
    links: list[CitationLinkSchema] = []


class RichTextSchema(Schema):
    """A text field bundled with rendered HTML plus provenance metadata."""

    text: str = ""
    html: str = ""
    plain: str = ""
    citations: list[InlineCitationSchema] = []
    attribution: AttributionSchema | None = None


class CitationSourceSchema(Schema):
    """A reusable citation source (a book, website, person, etc.).

    The source itself — not an individual reference *to* it. Distinct from
    :class:`CitationInstanceSchema`, which is one use of a source on a
    specific claim.
    """

    name: str
    slug: str
    source_type: str
    priority: int
    url: str
    description: str


class ReviewClaimSchema(Schema):
    """A flagged claim as surfaced in the global review queue.

    Self-contains subject context (``subject_*``, ``title_slug``,
    ``review_links``) because the review UI displays claims *outside* any
    entity page. Distinct from :class:`ClaimSchema`, which assumes the
    entity context is already known (Sources page) and instead carries
    priority/citation metadata (``citation``, ``is_winner``).
    """

    id: int
    source_name: str
    field_name: str
    value: ClaimValueSchema
    needs_review_notes: str
    created_at: str
    # Context about the subject (the entity this claim targets).
    # Canonical hyphenated CatalogModel.entity_type, e.g. "manufacturer".
    subject_type: str
    subject_name: str
    subject_slug: str | None = None
    # Title that this claim created (for group claims).
    title_slug: str | None = None
    review_links: list[ReviewLinkSchema] = []


class RevertNoteSchema(Schema):
    """Input for reverting a single claim to a prior value. ``note`` is required."""

    note: Annotated[str, Field(max_length=CHANGESET_NOTE_MAX_LENGTH)]


class UndoChangeSetSchema(Schema):
    """Input for undoing an entire ChangeSet (a create/edit/delete grouping)."""

    note: Annotated[str, Field(max_length=CHANGESET_NOTE_MAX_LENGTH)] = ""


class UndoResultSchema(Schema):
    """Result of an undo: the id of the new compensating ChangeSet."""

    changeset_id: int


class CitationInstanceSchema(Schema):
    """One use of a CitationSource on a specific claim, with a locator.

    The "instance" half of source/instance: a :class:`CitationSourceSchema`
    is the source itself; a CitationInstance attaches it to a claim with a
    page number, URL fragment, or other locator.
    """

    id: int
    citation_source_id: int
    citation_source_name: str
    claim_id: int | None = None
    locator: str
    created_at: str


class CitationInstanceBatchSchema(Schema):
    """A CitationInstance flattened with its source fields for batch rendering.

    Used where the UI needs source metadata (name, type, author, year)
    alongside the instance without a separate source lookup — typically
    when rendering many citations at once.
    """

    id: int
    source_name: str
    source_type: str
    author: str
    year: int | None = None
    locator: str
    links: list[CitationLinkSchema] = []


class CitationInstanceCreateSchema(Schema):
    """Input for creating a new CitationInstance against an existing source."""

    citation_source_id: int
    locator: Annotated[str, Field(max_length=CITATION_INSTANCE_LOCATOR_MAX_LENGTH)] = ""
