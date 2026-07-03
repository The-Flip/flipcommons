"""API schemas for the citation app — the "Sources" UI for cited evidence.

A :class:`~apps.citation.models.CitationSource` is a work or evidence object
that can be cited: a book, magazine or web page. Sources form a one-level
hierarchy through a self FK — a *root* source (e.g. the IPDB website, or a
magazine title) groups *child* sources (e.g. one IPDB machine page, or a
single issue/article). ``source_type`` is one of the registered
citation types (``book`` / ``magazine`` / ``web`` / ``video``).

Two derived notions recur across these schemas:

- **abstract** — a source that is a container rather than a directly-citable
  work: any source that has children, or a root ``web`` / ``magazine`` source.
  The UI offers such a source's children for citation instead of the source
  itself.
- **skip_locator** — a web *child* needs no locator (page/section/fragment)
  because its URL already pins the exact evidence; every other source needs a
  locator when cited.

Sources are NOT claims-controlled: unlike catalog entities they are edited
directly through admin / the Sources UI. Citation *search* additionally
recognizes a pasted URL or ISBN as belonging to a known root source (see
:class:`CitationRecognitionSchema`), and the *extract* endpoint fetches
metadata for a pasted URL/ISBN from an external API to prefill a create form
(see :class:`CitationExtractResultSchema`).
"""

from __future__ import annotations

from typing import Annotated, Literal

from ninja import Field, Schema
from pydantic import ConfigDict, field_validator

from .citation_types import SourceTypeValue
from .models import (
    CITATION_SOURCE_AUTHOR_MAX_LENGTH,
    CITATION_SOURCE_DATE_NOTE_MAX_LENGTH,
    CITATION_SOURCE_DESCRIPTION_MAX_LENGTH,
    CITATION_SOURCE_IDENTIFIER_MAX_LENGTH,
    CITATION_SOURCE_ISBN_MAX_LENGTH,
    CITATION_SOURCE_LINK_LABEL_MAX_LENGTH,
    CITATION_SOURCE_LINK_URL_MAX_LENGTH,
    CITATION_SOURCE_NAME_MAX_LENGTH,
    CITATION_SOURCE_PUBLISHER_MAX_LENGTH,
)

# String fields that are non-nullable CharFields on the model: an update that
# sends ``null`` for one of these is coerced to ``""`` (see
# ``CitationSourceUpdateSchema.coerce_null_to_empty``).
NONNULLABLE_STR_FIELDS = (
    "name",
    "source_type",
    "author",
    "publisher",
    "date_note",
    "description",
)

# Length-bounded string aliases, one per model CharField, so input schemas
# reject over-long values at the API boundary with the same limits the DB
# enforces.
NameStr = Annotated[str, Field(max_length=CITATION_SOURCE_NAME_MAX_LENGTH)]
AuthorStr = Annotated[str, Field(max_length=CITATION_SOURCE_AUTHOR_MAX_LENGTH)]
PublisherStr = Annotated[str, Field(max_length=CITATION_SOURCE_PUBLISHER_MAX_LENGTH)]
DateNoteStr = Annotated[str, Field(max_length=CITATION_SOURCE_DATE_NOTE_MAX_LENGTH)]
IsbnStr = Annotated[str, Field(max_length=CITATION_SOURCE_ISBN_MAX_LENGTH)]
DescriptionStr = Annotated[
    str, Field(max_length=CITATION_SOURCE_DESCRIPTION_MAX_LENGTH)
]
IdentifierStr = Annotated[str, Field(max_length=CITATION_SOURCE_IDENTIFIER_MAX_LENGTH)]
LinkUrlStr = Annotated[str, Field(max_length=CITATION_SOURCE_LINK_URL_MAX_LENGTH)]
LinkLabelStr = Annotated[str, Field(max_length=CITATION_SOURCE_LINK_LABEL_MAX_LENGTH)]


class CitationSourceSearchSchema(Schema):
    """One source row in citation typeahead search results."""

    id: int = Field(description="The source's identifier.")
    name: str = Field(description="The source's display name.")
    source_type: SourceTypeValue = Field(description="Kind of source.")
    author: str = Field(description="Author or creator, or an empty string.")
    publisher: str = Field(description="Publisher, or an empty string.")
    year: int | None = Field(None, description="Publication year, if known.")
    isbn: str | None = Field(None, description="ISBN, if known.")
    parent_id: int | None = Field(
        None,
        description="Identifier of the root source this is a child of, or null if it is itself a root.",
    )
    has_children: bool = Field(
        False,
        description="Whether other sources are grouped under this one as children.",
    )
    is_abstract: bool = Field(
        False,
        description=(
            "Whether this source is a container rather than a directly-citable "
            "work (it has children, or is a root web/magazine source); the UI "
            "cites its children instead."
        ),
    )
    skip_locator: bool = Field(
        False,
        description="Whether citing this source needs no locator — true for a web child, whose URL is the locator.",
    )
    identifier_key: str = Field(
        "",
        description=(
            "For a root web source, the identifier scheme its children use "
            '("ipdb", "opdb" or "youtube"); an empty string otherwise.'
        ),
    )


class CitationSourceMatchSchema(Schema):
    """A minimal reference to an existing source the user can re-cite.

    Returned when search recognition or metadata extraction finds a source
    that already exists, so the UI can offer it instead of creating a duplicate.
    """

    id: int = Field(description="The matched source's identifier.")
    name: str = Field(description="The matched source's display name.")
    source_type: SourceTypeValue = Field(
        description=(
            "The matched source's citation type — the frontend's key into "
            "the per-type locator behavior."
        ),
    )
    skip_locator: bool = Field(
        False,
        description="Whether citing the matched source needs no locator (true for a web child).",
    )


class CitationSourceParentSchema(Schema):
    """A minimal reference to a source's root/parent."""

    id: int = Field(description="The parent source's identifier.")
    name: str = Field(description="The parent source's display name.")


class CitationRecognitionSchema(Schema):
    """Recognition of a URL or ISBN typed into search as a known root source."""

    # Built by walking the registered extractors: an extractor matches the input
    # by URL pattern (or ISBN) to a known ``parent`` root source and, when
    # present, the extracted ``identifier``; ``child`` is filled when a source
    # with that identifier already exists. A bare domain match yields ``parent``
    # only (no ``identifier``, no ``child``).
    parent: CitationSourceParentSchema = Field(
        description="The known root source the input belongs to."
    )
    child: CitationSourceMatchSchema | None = Field(
        None,
        description=(
            "The existing child source for the input, when one already exists; "
            "null when the input is new (the UI prefills a create form)."
        ),
    )
    identifier: str | None = Field(
        None,
        description=(
            "The structured identifier extracted from the input (e.g. an IPDB "
            "machine id), or null when only the source's domain matched."
        ),
    )
    locator_hint: str = Field(
        "",
        description=(
            "Canonical locator text extracted from the input, to prefill the "
            "locator stage — e.g. '1:35' from a video URL's t= start time. "
            "Empty when the input carries no usable hint."
        ),
    )


class CitationSourceSearchResponseSchema(Schema):
    """Response body for the citation search typeahead."""

    results: list[CitationSourceSearchSchema] = Field(
        description="Matching source rows."
    )
    recognition: CitationRecognitionSchema | None = Field(
        None,
        description="Set when the query was recognized as a known URL or ISBN; null for plain-text queries.",
    )


class CitationSourceCreateSchema(Schema):
    """Input to create a book/magazine root or a linkless authored child.

    This endpoint creates plain authored sources only. Web roots/children are
    minted by ``cite-url``/``pages/`` and scheme children by ``records/``, so
    ``source_type`` excludes ``web`` and no ``url``/``identifier``/link fields
    are accepted; ``extra='forbid'`` turns a stray one into a loud 422.
    """

    model_config = ConfigDict(extra="forbid")

    name: NameStr = Field(description="The source's display name.")
    source_type: Literal["book", "magazine"] = Field(
        description='Kind of source: "book" or "magazine".'
    )
    author: AuthorStr = Field("", description="Author or creator.")
    publisher: PublisherStr = Field("", description="Publisher.")
    year: int | None = Field(None, description="Publication year.")
    month: int | None = Field(None, description="Publication month; requires year.")
    day: int | None = Field(None, description="Publication day; requires month.")
    date_note: DateNoteStr = Field(
        "",
        description="Free-text note about the date (e.g. a season or approximate date).",
    )
    isbn: IsbnStr | None = Field(
        None,
        description="ISBN; must be unique across sources. Empty input is stored as null.",
    )
    description: DescriptionStr = Field("", description="Free-text description.")
    parent_id: int | None = Field(
        None,
        description="Identifier of the root source to nest this under, or null to create a root.",
    )

    @field_validator("isbn", mode="before")
    @classmethod
    def coerce_empty_isbn_to_none(cls, v: object) -> object:
        """Empty string → None for nullable unique field."""
        return None if v == "" else v


class CitationCiteUrlSchema(Schema):
    """Input to cite a web page, creating its site root + page child as needed.

    The interactive web-create flow's finalize call. ``site_*`` describe a *new*
    site root and are used only when the URL's domain isn't yet recognized; for
    a domain that already matches a root they're ignored (the root isn't renamed
    from here).
    """

    url: LinkUrlStr = Field(description="The page URL to cite.")
    site_name: NameStr = Field(
        "",
        description="Display name for a new site root; falls back to the domain when blank.",
    )
    site_description: DescriptionStr = Field(
        "", description="Optional free-text description for a new site root."
    )
    page_name: NameStr = Field(
        "",
        description="Display name for the page child; falls back to the URL or its host when blank.",
    )


class CitationPageCreateSchema(Schema):
    """Input to mint a web page child under an explicit parent root.

    The parent is the path param, so only the page's own fields ride the body:
    the URL and an optional display name (the backend derives one from the URL
    when blank). ``extra='forbid'`` so a stray ``source_type``/``link_type`` from
    a stale client is a loud 422, not a silent drop.
    """

    model_config = ConfigDict(extra="forbid")

    url: LinkUrlStr = Field(description="The page URL to cite.")
    page_name: NameStr = Field(
        "",
        description="Display name for the page child; falls back to the URL or its host when blank.",
    )


class CitationRecordCreateSchema(Schema):
    """Input to mint a scheme child (IPDB/OPDB/…) under an explicit parent root.

    The parent is the path param and the leaf owns the name and canonical link,
    so the identifier is the only body field. ``extra='forbid'`` so a stray
    ``name``/``source_type`` from a stale client is a loud 422.
    """

    model_config = ConfigDict(extra="forbid")

    identifier: IdentifierStr = Field(
        description="Structured identifier for this child within its parent's scheme (e.g. an IPDB machine id).",
    )


class CitationSourceUpdateSchema(Schema):
    """Input to update a citation source; a partial update.

    Omitted fields are left unchanged (the endpoint applies only the keys the
    client sends). Sending ``null`` for a non-nullable string field clears it to
    an empty string; sending ``null`` (or empty) for ``isbn`` clears it to null.
    """

    name: NameStr | None = Field(None, description="New display name.")
    source_type: SourceTypeValue | None = Field(None, description="New source type.")
    author: AuthorStr | None = Field(None, description="New author or creator.")
    publisher: PublisherStr | None = Field(None, description="New publisher.")
    year: int | None = Field(None, description="New publication year.")
    month: int | None = Field(None, description="New publication month; requires year.")
    day: int | None = Field(None, description="New publication day; requires month.")
    date_note: DateNoteStr | None = Field(
        None, description="New free-text note about the date."
    )
    isbn: IsbnStr | None = Field(
        None, description="New ISBN; must be unique across sources."
    )
    description: DescriptionStr | None = Field(
        None, description="New free-text description."
    )

    @field_validator(*NONNULLABLE_STR_FIELDS, mode="before")
    @classmethod
    def coerce_null_to_empty(cls, v: object) -> object:
        """None → empty string for non-nullable CharFields."""
        return "" if v is None else v

    @field_validator("isbn", mode="before")
    @classmethod
    def coerce_empty_isbn_to_none(cls, v: object) -> object:
        """Empty string → None for nullable unique field."""
        return None if v == "" else v


class CitationSourceChildSchema(Schema):
    """A child source as nested under its parent in the detail view."""

    id: int = Field(description="The child source's identifier.")
    name: str = Field(description="The child source's display name.")
    source_type: SourceTypeValue = Field(description="Kind of source.")
    year: int | None = Field(None, description="Publication year, if known.")
    isbn: str | None = Field(None, description="ISBN, if known.")
    skip_locator: bool = Field(
        False,
        description="Whether citing this child needs no locator — true for a web child, whose URL is the locator.",
    )
    urls: list[str] = Field(
        [],
        description="URLs of every link attached to this child, regardless of link type.",
    )


class CitationSourceLinkSchema(Schema):
    """A link attached to a citation source."""

    id: int = Field(description="The link's identifier.")
    link_type: str = Field(
        description='Kind of link: "homepage", "catalog", "publisher", "reference" or "archive".'
    )
    url: str = Field(description="The link's URL.")
    label: str = Field(description="Human-readable label, or an empty string.")


class CitationSourceDetailSchema(Schema):
    """Full detail for a single citation source, with its links and children."""

    id: int = Field(description="The source's identifier.")
    name: str = Field(description="The source's display name.")
    source_type: SourceTypeValue = Field(description="Kind of source.")
    author: str = Field(description="Author or creator, or an empty string.")
    publisher: str = Field(description="Publisher, or an empty string.")
    year: int | None = Field(None, description="Publication year, if known.")
    month: int | None = Field(None, description="Publication month, if known.")
    day: int | None = Field(None, description="Publication day, if known.")
    date_note: str = Field(
        description="Free-text note about the date, or an empty string."
    )
    isbn: str | None = Field(None, description="ISBN, if known.")
    description: str = Field(description="Free-text description, or an empty string.")
    identifier_key: str = Field(
        "",
        description='For a root web source, the identifier scheme its children use ("ipdb", "opdb" or "youtube"); an empty string otherwise.',
    )
    skip_locator: bool = Field(
        False,
        description="Whether citing this source needs no locator (true for a web child).",
    )
    parent: CitationSourceParentSchema | None = Field(
        None, description="The root source this is a child of, or null if it is a root."
    )
    links: list[CitationSourceLinkSchema] = Field(
        [], description="Links where a reader can inspect this source."
    )
    children: list[CitationSourceChildSchema] = Field(
        [], description="Sources grouped under this one as children."
    )
    created_at: str = Field(
        description="When the source was created, as an ISO 8601 timestamp."
    )
    updated_at: str = Field(
        description="When the source was last updated, as an ISO 8601 timestamp."
    )


class CitationSourceLinkCreateSchema(Schema):
    """Input to attach a new link to a citation source."""

    link_type: str = Field(
        description='Kind of link: "homepage", "catalog", "publisher", "reference" or "archive".'
    )
    url: LinkUrlStr = Field(description="The link's URL; must be unique on the source.")
    label: LinkLabelStr = Field("", description="Human-readable label for the link.")


class CitationSourceLinkUpdateSchema(Schema):
    """Input to update a link; a partial update (omitted fields unchanged)."""

    link_type: str | None = Field(
        None,
        description='New link type: "homepage", "catalog", "publisher", "reference" or "archive".',
    )
    url: LinkUrlStr | None = Field(None, description="New URL for the link.")
    label: LinkLabelStr | None = Field(None, description="New label for the link.")

    @field_validator("label", mode="before")
    @classmethod
    def coerce_null_to_empty(cls, v: object) -> object:
        return "" if v is None else v


class CitationExtractInputSchema(Schema):
    """Input to the metadata-extraction endpoint."""

    input: str = Field(
        description=(
            "A pasted URL (with an http(s):// scheme) or an ISBN-10/ISBN-13. The "
            "endpoint classifies it automatically; an ISBN takes priority."
        )
    )


class CitationExtractDraftSchema(Schema):
    """Metadata scraped from an external lookup, to prefill the create form."""

    name: str = Field(description="The extracted title.")
    source_type: SourceTypeValue = Field(
        description='Inferred source type: "book" for an ISBN, "web" for a URL.'
    )
    author: str = Field(description="Extracted author, or an empty string.")
    publisher: str = Field(
        description="Extracted publisher or site name, or an empty string."
    )
    year: int | None = Field(None, description="Extracted publication year, if found.")
    isbn: str | None = Field(
        None, description="The ISBN, for a book draft; null for a web draft."
    )
    url: str | None = Field(
        None, description="The URL, for a web draft; null for a book draft."
    )


class CitationExtractResultSchema(Schema):
    """Result of looking up a pasted URL/ISBN via an external API.

    Exactly one of ``match``, ``draft`` or ``error`` is the meaningful outcome:
    ``match`` when a source already exists (re-cite it), ``draft`` when metadata
    was fetched for a new source (prefill the create form), ``error`` when the
    lookup failed.
    """

    draft: CitationExtractDraftSchema | None = Field(
        None,
        description="Prefill metadata for the create form, when extraction succeeded.",
    )
    match: CitationSourceMatchSchema | None = Field(
        None,
        description="An existing source with the same ISBN or identifier, when one was found.",
    )
    error: str | None = Field(
        None,
        description=(
            "Failure reason, when the lookup failed: one of ``not_found``, "
            "``timeout``, ``api_error``, ``parse_error`` or ``blocked``."
        ),
    )
    confidence: str = Field(
        "",
        description=(
            'How reliable the draft is: "high" for an ISBN lookup, "low" for URL '
            "meta-tag scraping; empty when there is no draft."
        ),
    )
    source_api: str = Field(
        "",
        description=(
            'Which external source produced the draft: "openlibrary" for an ISBN, '
            '"og_meta" for URL Open Graph tags; empty when there is no draft.'
        ),
    )
