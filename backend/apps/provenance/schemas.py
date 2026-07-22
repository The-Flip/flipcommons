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

from apps.citation.models import (
    CITATION_INSTANCE_LOCATOR_MAX_LENGTH,
    CITATION_INSTANCE_QUOTE_MAX_LENGTH,
)
from apps.core.authz import Activity, PolicyActivities

from .models import (
    CHANGESET_NOTE_MAX_LENGTH,
    ChangeSet,
)

ClaimDisplayIdentityState = Literal["resolved", "deleted", "missing"]
"""Discriminant for :class:`ClaimDisplayIdentityPartSchema`.

See that schema's ``state`` field for what each value implies.
"""


class ClaimDisplayIdentityPartSchema(Schema):
    """One identity slot of a relationship claim's user-facing rendering."""

    key: str = Field(
        description='Names the identity this slot fills (e.g. "person", "alias_value").'
    )
    label: str | None = Field(
        description=(
            "The user-facing label for the referenced entity, or null when no "
            "label could be produced (see ``state``)."
        )
    )
    state: ClaimDisplayIdentityState = Field(
        description=(
            'Whether a label could be produced. "resolved": a real label is '
            'present. "deleted": the referenced catalog row no longer exists, so '
            '``label`` is null. "missing": the claim did not carry this identity '
            "key, so ``label`` is null."
        )
    )
    # No default on ``state``: every construction must pick one. Defaulting to
    # ``"resolved"`` would let ``ClaimDisplayIdentityPartSchema(key=..., label=None)``
    # construct silently with an incoherent ``(resolved, null)`` pair. The
    # ``"missing"`` case is an invariant violation validation should have
    # prevented; the backend logs loudly when it happens.


class ClaimDisplayQualifierPartSchema(Schema):
    """One qualifier on a relationship claim's user-facing rendering."""

    key: str = Field(
        description='Names the non-identity qualifier (e.g. "count", "category", "is_primary").'
    )
    value: bool | int | str | None = Field(
        None,
        description="The qualifier's raw scalar value, for per-key frontend rendering.",
    )
    # Union ordering is most specific first: ``bool`` before ``int`` because
    # ``bool`` is an ``int`` subclass and Pydantic v2's default union resolution
    # would otherwise coerce ``True`` into ``1``, silently breaking frontend
    # ``v === true`` checks.


class ClaimDisplayValueSchema(Schema):
    """Structured user-facing rendering of a relationship-claim value.

    The ``relationship`` arm of :data:`ClaimDisplaySchema`.
    """

    kind: Annotated[
        Literal["relationship"],
        Field(description='Discriminator; always "relationship".'),
    ] = "relationship"
    identity: list[ClaimDisplayIdentityPartSchema] = Field(
        description="The claim's identity slots, in display order."
    )
    qualifiers: list[ClaimDisplayQualifierPartSchema] = Field(
        description="The claim's qualifiers, in display order."
    )
    # Lists (not dicts) so declaration order is part of the wire format, not an
    # implicit dict-insertion-order contract. Direct-field scalar claims and
    # non-relationship namespaces have no ``ClaimDisplayValueSchema`` — the
    # frontend falls back to the raw ``old_value`` / ``new_value`` there.


class MarkdownClaimDisplaySchema(Schema):
    """User-facing rendering of a markdown-field claim value.

    The ``markdown`` arm of :data:`ClaimDisplaySchema`. ``text`` is the value
    in authoring form — ``[[type:id:N]]`` storage markers resolved to their
    ``[[type:slug]]`` authoring keys — so the edit-history diff and the editor
    show the same legible representation rather than raw pks. Deleted targets
    keep storage form.
    """

    kind: Annotated[
        Literal["markdown"], Field(description='Discriminator; always "markdown".')
    ] = "markdown"
    text: str = Field(description="The claim's markdown value in authoring form.")


ClaimDisplaySchema = Annotated[
    ClaimDisplayValueSchema | MarkdownClaimDisplaySchema,
    Field(discriminator="kind"),
]
"""Tagged union of a claim value's user-facing rendering, keyed on ``kind``.

``relationship`` carries the structured identity/qualifier parts;
``markdown`` carries the authoring-form text. Direct-field scalars and
unknown namespaces have no rendering — :class:`ClaimValueSchema.display` is
null and the frontend falls back to ``raw``."""


class ClaimValueSchema(Schema):
    """A claim value paired with its structured user-facing rendering."""

    raw: object = Field(
        description=(
            "The claim's raw JSON payload — a scalar, dict, list or null "
            "depending on the claim kind."
        )
    )
    display: ClaimDisplaySchema | None = Field(
        None,
        description=(
            "Structured rendering for relationship claims or authoring-form text "
            "for markdown fields, or null when there is none (direct-field "
            "scalars, unknown namespaces, non-dict values); clients fall back to "
            "``raw``."
        ),
    )


class CitationLinkSchema(Schema):
    """A link attached to a citation source, ready for display."""

    url: str = Field(
        description="The link's URL, deep-linked to the locator when possible."
    )
    link_type: str = Field(
        description="Kind of link: one of ``homepage``, ``catalog``, ``publisher``, ``reference`` or ``archive``."
    )
    display_name: str = Field(
        description="Human-readable link text — the link's label, or its link-type name when unlabeled. Never blank."
    )


class ClaimCitationSchema(Schema):
    """A citation backing a claim — an edit-history field change or a
    Sources-page assertion; both render it through the same client component.

    Covers both kinds of evidence: instances attached to the claim as
    supporting evidence (``slug`` is null) and instances referenced by
    inline ``[[cite:slug]]`` markers in a markdown value (``slug`` set, so
    clients can match the entry to its marker in the text).
    """

    id: int = Field(
        description=(
            "The citation instance's primary key — the identity the citation "
            "tooltip keys on, matching the ``data-cite-id`` its marker carries."
        )
    )
    source_name: str = Field(description="The cited source's display name.")
    source_type: str = Field(
        description="Kind of source: one of ``database``, ``wiki``, ``book``, ``editorial`` or ``other``."
    )
    author: str = Field(description="Author of the cited source, if recorded.")
    year: int | None = Field(
        None, description="Publication year of the source, if known."
    )
    locator: str = Field(
        description="Specific location within the source, such as a page or section."
    )
    quote: str = Field(
        description=(
            "Verbatim excerpt from the source backing the claim, or an empty "
            "string when none was recorded."
        )
    )
    slug: str | None = Field(
        None,
        description=(
            "The citation instance's authoring slug when the citation is an "
            "inline ``[[cite:slug]]`` marker in the change's text; null for "
            "evidence attached directly to the claim."
        ),
    )
    links: list[CitationLinkSchema] = Field(
        default_factory=list,
        description="External links for the cited source.",
    )


class FieldChangeSchema(Schema):
    """A single field change within a ChangeSet (old → new)."""

    field_name: str = Field(description="The entity field that changed.")
    claim_key: str = Field(
        description=(
            "Identity of the claim within the field — equal to ``field_name`` for "
            "scalar fields, or a composite key identifying one element of a "
            "relationship."
        )
    )
    # ``old_value`` is null in two cases this wire format does not distinguish:
    # (1) no prior claim exists in the chain, or (2) a prior claim exists but its
    # value is JSON null.
    old_value: ClaimValueSchema | None = Field(
        None,
        description=(
            "The immediately preceding claim value for the same claim key in "
            "chronological claim-log order, regardless of actor, priority, "
            "active state or winning state — NOT the previously "
            "resolved/materialized catalog value. Null when there was no "
            "prior claim."
        ),
    )
    new_value: ClaimValueSchema = Field(
        description="The new value asserted by this change."
    )
    claim_id: int | None = Field(
        None, description="Identifier of the underlying claim, when available."
    )
    claim_user_id: int | None = Field(
        None,
        description="Identifier of the user who authored the claim, or null when it was authored by an ingest source.",
    )
    is_active: bool | None = Field(
        None,
        description="Whether the claim is currently active (not superseded or retracted).",
    )
    is_winning: bool | None = Field(
        None,
        description="Whether the claim currently wins resolution for its field; null when not computed for this response.",
    )
    is_retracted: bool | None = Field(
        None, description="Whether the claim has been retracted."
    )
    citations: list[ClaimCitationSchema] = Field(
        default_factory=list,
        description="Citations attached to this change's claim (e.g. an IPDB page).",
    )


class RetractionSchema(Schema):
    """A claim that was retracted (not superseded) within a ChangeSet.

    A retraction removes a prior claim without replacing it, so it has no
    ``new_value`` — unlike :class:`FieldChangeSchema`.
    """

    claim_id: int = Field(description="Identifier of the retracted claim.")
    field_name: str = Field(
        description="The entity field the retracted claim applied to."
    )
    claim_key: str = Field(
        description="Identity of the retracted claim within the field."
    )
    old_value: ClaimValueSchema = Field(description="The value that was removed.")


class ClaimUserAuthorSchema(Schema):
    """A Claim/ChangeSet authored by a user."""

    kind: Annotated[
        Literal["user"], Field(description='Discriminator; always "user".')
    ] = "user"
    username: str = Field(description="The authoring user's username.")


class ClaimSourceAuthorSchema(Schema):
    """A Claim/ChangeSet attributed to an ingest source."""

    kind: Annotated[
        Literal["source"], Field(description='Discriminator; always "source".')
    ] = "source"
    name: str = Field(description="The ingest source's name.")


ClaimAuthorSchema = Annotated[
    ClaimUserAuthorSchema | ClaimSourceAuthorSchema,
    Field(discriminator="kind"),
]
"""Tagged union: a Claim/ChangeSet is authored by exactly one of a user or
an ingest source. The one-of-two invariant comes from the attribution ``Actor``
having exactly one backing record (its ``backing_model``); the wire shape
reflects that on the API."""


class ClaimAttributionSchema(Schema):
    """Who asserted a Claim and when."""

    author: ClaimAuthorSchema = Field(
        description="The user or ingest source that made the assertion."
    )
    created_at: str = Field(
        description="When the assertion was made, as an ISO 8601 timestamp."
    )


class ChangeSetBaseSchema(Schema):
    """Common fields for any read-side ChangeSet representation."""

    id: int = Field(description="The ChangeSet's identifier.")
    attribution: ClaimAttributionSchema = Field(
        description="Who created the ChangeSet and when."
    )
    note: str = Field(
        description="The author's note explaining the edit, or an empty string."
    )


class ChangeSetSchema(ChangeSetBaseSchema):
    """A grouped edit session with per-field diffs."""

    changes: list[FieldChangeSchema] = Field(
        description="The field changes in this ChangeSet, one per modified field."
    )
    retractions: list[RetractionSchema] = Field(
        [], description="Claims removed without replacement in this ChangeSet."
    )
    capabilities: dict[Activity, bool] = Field(
        default_factory=dict,
        description=(
            "Per-activity authorization for the calling user: whether policy "
            "permits attempting each action (e.g. ``changeset.undo``) on this row."
        ),
    )
    # Each capability answers only "is the caller authorized to *attempt* this
    # activity" — not a guarantee it will succeed. ``capabilities['changeset.undo']
    # is True`` only means policy lets this caller call the undo endpoint; the
    # endpoint additionally enforces operational invariants (``action == DELETE``,
    # claims not superseded) that aren't expressible as pure-attribute policy
    # predicates and so don't reflect on the wire. A future per-row Undo UI MUST
    # AND the embedded verdict with operational eligibility before rendering an
    # affordance, or design a separate operational-eligibility wire field then.

    # Declared on each concrete row variant (not on the base) — the
    # ``authz.E101–E106`` system check reads these from ``__dict__``, so
    # inherited declarations don't trigger the structural check.
    policy_activities: ClassVar[PolicyActivities] = (Activity.CHANGESET_UNDO,)
    policy_target_model: ClassVar[type[Model]] = ChangeSet


class ClaimSchema(Schema):
    """A single per-field claim as surfaced to the Sources UI."""

    attribution: ClaimAttributionSchema = Field(
        description="Who asserted the claim and when."
    )
    field_name: str = Field(description="The entity field the claim applies to.")
    claim_key: str = Field(
        description=(
            "Identity of the slot this claim competes for. Claims sharing it "
            "are rival values and exactly one wins; claims of the same field "
            "under different keys coexist. Composite for a relationship member "
            '("credit|person:42|role:7" — one winner per related row), equal '
            "to ``field_name`` for a direct or ``extra_data`` field (one "
            "winner per column)."
        )
    )
    value: ClaimValueSchema = Field(description="The claim's asserted value.")
    is_winner: bool = Field(
        description="Whether this claim currently wins resolution for its claim_key."
    )
    citations: list[ClaimCitationSchema] = Field(
        description=(
            "Citations backing this claim: instances attached as supporting "
            "evidence, then the ``[[cite:...]]`` markers its value carries. "
            "Always present, empty when the claim has none — required, not "
            "defaulted, so the generated client type is not optional."
        )
    )


class CitationInstanceCreateSchema(Schema):
    """Content spec for a citation: what to cite and where in it.

    The single input shape for minting a ``CitationInstance``, always at save
    time: edit cites ride the save payload's ``citations`` list, and inline
    cites ride ``inline_citations`` (as :class:`InlineCitationSpecSchema`,
    which adds the reserved slug the marker already carries).
    """

    citation_source_id: int = Field(description="Identifier of the source to cite.")
    locator: Annotated[
        str,
        Field(
            max_length=CITATION_INSTANCE_LOCATOR_MAX_LENGTH,
            description="Specific location within the source, such as a page or section.",
        ),
    ] = ""
    quote: Annotated[
        str,
        Field(
            max_length=CITATION_INSTANCE_QUOTE_MAX_LENGTH,
            description=(
                "Verbatim excerpt from the source: exact source text and "
                "'[...]' ellipses only."
            ),
        ),
    ] = ""


class InlineCitationSpecSchema(CitationInstanceCreateSchema):
    """Content spec for a pending inline cite, keyed by its reserved slug.

    The editor reserved *slug* up front (so its ``[[cite:slug]]`` marker could
    be placed) and the save handler mints the instance under that slug,
    consuming the reservation in the same transaction as the claims whose
    content references it.
    """

    slug: str = Field(
        description=(
            "The reserved citation slug this spec mints under — must match a "
            "live slug reservation held by the requesting user, and must be "
            "referenced by a [[cite:slug]] marker in the save's field values."
        )
    )


class CitationSlugReservationSchema(Schema):
    """A freshly reserved citation slug for a pending inline cite."""

    slug: str = Field(
        description=(
            "The reserved slug: place it in a [[cite:slug]] marker and send "
            "its content spec in the save payload's inline_citations list."
        )
    )


class ChangeSetInputSchema(Schema):
    """Base shape for any user-attributed mutation that produces a ChangeSet."""

    note: Annotated[
        str,
        Field(
            max_length=CHANGESET_NOTE_MAX_LENGTH,
            description="Optional note explaining the edit.",
        ),
    ] = ""
    citations: Annotated[
        list[CitationInstanceCreateSchema],
        Field(
            description=(
                "Evidence supporting this edit. Each entry mints one shared "
                "citation instance, attached to every claim in the save."
            )
        ),
    ] = []


class InlineCitationsInputSchema(Schema):
    """Mixin for save bodies whose field values may carry pending inline cites.

    Mixed into the ``fields``-carrying claim-patch schemas (the only bodies
    whose values can contain markdown with ``[[cite:slug]]`` markers), not
    into ``ChangeSetInputSchema`` — a create or delete body has no field
    value a marker could live in, so accepting specs there would only create
    unreferencable payloads.
    """

    inline_citations: Annotated[
        list[InlineCitationSpecSchema],
        Field(
            description=(
                "Pending inline cites: content specs for the [[cite:slug]] "
                "markers this save introduces. Each is minted under its "
                "reserved slug in the save transaction; every spec must be "
                "referenced by a marker in the saved field values."
            )
        ),
    ] = []


class AttributionSchema(Schema):
    """License and source attribution for rendered content."""

    license_slug: Annotated[
        str | None, Field(description="Identifier of the content's license, if any.")
    ] = None
    license_name: Annotated[
        str | None, Field(description="Short display name of the license.")
    ] = None
    license_url: Annotated[
        str | None, Field(description="URL of the license text.")
    ] = None
    requires_attribution: Annotated[
        bool,
        Field(
            description="Whether the license requires attribution when this content is reused."
        ),
    ] = False
    source_name: Annotated[
        str | None,
        Field(description="Name of the source this content was derived from."),
    ] = None
    source_url: Annotated[str | None, Field(description="URL of that source.")] = None


class InlineCitationSchema(Schema):
    """Metadata for an inline citation in rendered markdown."""

    id: int = Field(
        description="The citation instance's identifier (matches ``data-cite-id`` in the rendered HTML)."
    )
    index: int = Field(
        description="The citation's sequential number in the text, shown as ``[1]``, ``[2]``, …"
    )
    source_name: str = Field(description="Name of the cited source.")
    source_type: str = Field(
        description="Kind of source: one of ``database``, ``wiki``, ``book``, ``editorial`` or ``other``."
    )
    author: str = Field(description="Author of the cited source, if recorded.")
    year: Annotated[
        int | None, Field(description="Publication year of the source, if known.")
    ] = None
    locator: str = Field(
        description="Specific location within the source, such as a page or section."
    )
    quote: str = Field(
        description="Verbatim excerpt from the source backing the citation, or an empty string."
    )
    links: Annotated[
        list[CitationLinkSchema],
        Field(description="External links for the cited source."),
    ] = []


class RichTextSchema(Schema):
    """A text field bundled with rendered HTML plus provenance metadata."""

    text: Annotated[
        str,
        Field(
            description=(
                "The source text in authoring format — Markdown with "
                "``[[type:slug]]`` tokens for entity links. Mainly for edit forms; "
                "prefer ``html`` or ``plain`` for display."
            )
        ),
    ] = ""
    html: Annotated[str, Field(description="Display-ready rendered HTML.")] = ""
    plain: Annotated[
        str,
        Field(
            description=(
                "Plain-text projection with markup and link tokens stripped — for "
                "previews, meta descriptions and machine-readable use."
            )
        ),
    ] = ""
    citations: Annotated[
        list[InlineCitationSchema],
        Field(description="Inline citations referenced in the rendered content."),
    ] = []
    attribution: Annotated[
        AttributionSchema | None,
        Field(
            description=(
                "License and source attribution for this content, when it derives "
                "from an attributed source."
            )
        ),
    ] = None


class CitationSourceSchema(Schema):
    """A reusable ingest source — a database, wiki, book, editorial team, etc.

    Despite the legacy name, this serializes the provenance ``Source`` model
    (who asserted data into the project), NOT a citation source; its
    ``source_type`` enum is unrelated to citation types.
    """

    # The source itself — not an individual reference *to* it. Distinct from
    # :class:`CitationInstanceSchema`, which is one use of a citation source on a claim.
    name: str = Field(description="The ingest source's display name.")
    slug: str = Field(description="The ingest source's URL slug.")
    source_type: str = Field(
        description="Kind of source: one of ``database``, ``wiki``, ``book``, ``editorial`` or ``other``."
    )
    priority: int = Field(
        description="Resolution weight; when claims conflict, the higher-priority source wins."
    )
    url: str = Field(
        description="URL where the source can be found, or an empty string."
    )
    description: str = Field(
        description="Free-text description of the source, or an empty string."
    )


class RevertNoteSchema(Schema):
    """Input for reverting a single claim to a prior value."""

    note: Annotated[
        str,
        Field(
            max_length=CHANGESET_NOTE_MAX_LENGTH,
            description="Required note explaining the revert.",
        ),
    ]


class UndoChangeSetSchema(Schema):
    """Input for undoing an entire ChangeSet (a create/edit/delete grouping)."""

    note: Annotated[
        str,
        Field(
            max_length=CHANGESET_NOTE_MAX_LENGTH,
            description="Optional note explaining the undo.",
        ),
    ] = ""


class UndoResultSchema(Schema):
    """Result of an undo: the id of the new compensating ChangeSet."""

    changeset_id: int = Field(
        description="Identifier of the compensating ChangeSet created by the undo."
    )


class CitationInstanceSchema(Schema):
    """One use of a CitationSource at a specific location, with a locator.

    The "instance" half of source/instance: a :class:`CitationSourceSchema`
    is the source itself; a CitationInstance pins it to a page number, URL
    fragment, or other locator. An instance is shared evidence — claims
    reference it through the claim↔instance join, and inline markdown cites
    reference it through their ``[[cite:...]]`` marker.
    """

    id: int = Field(description="The citation instance's identifier.")
    slug: str = Field(
        description="Author-stable handle used in [[cite:<slug>]] authoring markers."
    )
    citation_source_id: int = Field(description="Identifier of the cited source.")
    citation_source_name: str = Field(description="Display name of the cited source.")
    locator: str = Field(
        description="Specific location within the source, such as a page or section, or an empty string."
    )
    quote: str = Field(
        description="Verbatim excerpt from the source, or an empty string."
    )
    created_at: str = Field(
        description="When the instance was created, as an ISO 8601 timestamp."
    )


class CitationInstanceBatchSchema(Schema):
    """A CitationInstance flattened with its source fields for batch rendering.

    Carries source metadata (name, type, author, year) alongside the
    instance so callers rendering many citations at once avoid a separate
    source lookup.
    """

    id: int = Field(description="The citation instance's identifier.")
    source_name: str = Field(description="Name of the cited source.")
    source_type: str = Field(
        description="Kind of source: one of ``database``, ``wiki``, ``book``, ``editorial`` or ``other``."
    )
    author: str = Field(description="Author of the cited source, or an empty string.")
    year: int | None = Field(
        None, description="Publication year of the source, if known."
    )
    locator: str = Field(
        description="Specific location within the source, or an empty string."
    )
    quote: str = Field(
        description="Verbatim excerpt from the source backing the citation, or an empty string."
    )
    links: list[CitationLinkSchema] = Field(
        [], description="External links for the cited source."
    )
