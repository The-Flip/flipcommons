"""Citation models: cited works and the evidence instances drawn from them."""

from __future__ import annotations

import re
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import (
    MaxValueValidator,
    MinValueValidator,
    RegexValidator,
)
from django.db import IntegrityError, models, transaction
from django.db.models.functions import Length, Now
from django.utils.crypto import get_random_string

from apps.accounts.models import User
from apps.actors.models import ActorAttributedModel
from apps.citation.citation_types import (
    ISBN_CITE_PREFIX,
    SourceType,
    citation_type_spec,
    identifier_key_choices,
    identifier_key_values,
    known_scheme_keys,
    scheme_bindings,
    slug_addressed_source_types,
)
from apps.citation.deliverers import deliverer_for_host
from apps.citation.hosts import is_dns_host, normalize_host
from apps.citation.psl import is_public_suffix
from apps.core.models import (
    BoundedTextField,
    TimeStampedModel,
    field_lowercase,
    field_not_blank,
    nullable_id_not_empty,
    self_fk_not_self,
)
from apps.core.types import CitationSourceId
from apps.core.validators import (
    SLUG_FORMAT_MESSAGE,
    SLUG_RE,
    validate_no_mojibake,
)

__all__ = [
    "CitationInstance",
    "CitationSource",
    "CitationSourceLink",
    "CitationSourceRootDomain",
    "ReservedCitationSlug",
    "reserve_citation_slug",
]

YEAR_MIN, YEAR_MAX = 1800, 2100
MONTH_MIN, MONTH_MAX = 1, 12
DAY_MIN, DAY_MAX = 1, 31

CITATION_SOURCE_NAME_MAX_LENGTH = 500
CITATION_SOURCE_AUTHOR_MAX_LENGTH = 300
CITATION_SOURCE_PUBLISHER_MAX_LENGTH = 300
CITATION_SOURCE_DATE_NOTE_MAX_LENGTH = 200
CITATION_SOURCE_ISBN_MAX_LENGTH = 20
CITATION_SOURCE_IDENTIFIER_MAX_LENGTH = 200
CITATION_SOURCE_SLUG_MAX_LENGTH = 200
CITATION_SOURCE_DESCRIPTION_MAX_LENGTH = 5_000
CITATION_SOURCE_LINK_URL_MAX_LENGTH = 2_000
CITATION_SOURCE_LINK_LABEL_MAX_LENGTH = 200
CITATION_ROOT_DOMAIN_HOST_MAX_LENGTH = 253  # RFC 1035 DNS hostname limit

# Shown when a write tries to claim a recognition host another root already owns
# (the `host` unique). A module constant so every surface that reports the
# collision reads identically.
CITATION_ROOT_DOMAIN_HOST_TAKEN_MSG = (
    "That domain is already recognized by another citation source."
)


def reserved_cite_handles() -> list[str]:
    """Root-slug values consumed by the other cite-ref grammars.

    A root slug is the left segment of a patch cite ref
    (``<root-slug>:<child-slug>``), a namespace it shares with ``isbn:`` and
    ``scheme:identifier`` — and those parsers run first, so a root claiming one
    of their handles could never be reached by its slug. Derived from the one
    vocabulary constant and the scheme registry, never a hand-maintained list,
    so a new scheme flows into makemigrations.
    """
    return [ISBN_CITE_PREFIX, *known_scheme_keys()]


def _identifier_key_matches_scheme_type() -> models.Q:
    """The CHECK condition pairing each ``identifier_key`` with its owning type.

    Blank (a root without a scheme) or one of the registry's
    ``(key, source_type)`` pairs — built in stable registration order so the
    serialized constraint only changes when the registry does.
    """
    condition = models.Q(identifier_key="")
    for binding in scheme_bindings():
        condition |= models.Q(
            identifier_key=binding.identifier_key, source_type=binding.source_type
        )
    return condition


class CitationSourceQuerySet(models.QuerySet["CitationSource"]):
    """Adds the root/child split the whole citation hierarchy turns on."""

    def roots(self) -> CitationSourceQuerySet:
        """Top-level sources with no parent (books, periodicals, website roots)."""
        return self.filter(parent__isnull=True)

    def children(self) -> CitationSourceQuerySet:
        """Sources nested under a parent (editions, articles, pages, records)."""
        return self.filter(parent__isnull=False)


CitationSourceManager = models.Manager.from_queryset(CitationSourceQuerySet)


class CitationSource(TimeStampedModel, ActorAttributedModel):
    """A work or evidence object that can be cited: book, flyer, web page, etc.

    NOT claims-controlled — edited directly through admin or future UI.
    Hierarchy via self-referential parent FK enables grouping (e.g., article
    within periodical issue, edition within book).
    """

    id: int
    objects = CitationSourceManager()
    links: models.Manager[CitationSourceLink]
    root_domains: models.Manager[CitationSourceRootDomain]
    parent_id: int | None

    # ``SourceType`` and the per-type/per-scheme specs live in the
    # ``citation_types`` package (a dependency-free leaf, so ``models`` imports
    # it without a cycle); re-exported here so ``CitationSource.SourceType``
    # stays the canonical handle.
    SourceType = SourceType

    name = models.CharField(
        max_length=CITATION_SOURCE_NAME_MAX_LENGTH, validators=[validate_no_mojibake]
    )
    source_type = models.CharField(max_length=20, choices=SourceType.choices)
    author = models.CharField(
        max_length=CITATION_SOURCE_AUTHOR_MAX_LENGTH,
        blank=True,
        validators=[validate_no_mojibake],
    )
    publisher = models.CharField(
        max_length=CITATION_SOURCE_PUBLISHER_MAX_LENGTH,
        blank=True,
        validators=[validate_no_mojibake],
    )
    year = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(YEAR_MIN), MaxValueValidator(YEAR_MAX)],
    )
    month = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(MONTH_MIN), MaxValueValidator(MONTH_MAX)],
    )
    day = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(DAY_MIN), MaxValueValidator(DAY_MAX)],
    )
    date_note = models.CharField(
        max_length=CITATION_SOURCE_DATE_NOTE_MAX_LENGTH,
        blank=True,
        validators=[validate_no_mojibake],
    )
    isbn = models.CharField(
        max_length=CITATION_SOURCE_ISBN_MAX_LENGTH,
        null=True,
        blank=True,
        unique=True,
        validators=[validate_no_mojibake],
    )
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="children",
    )
    description = BoundedTextField(
        max_length=CITATION_SOURCE_DESCRIPTION_MAX_LENGTH,
        blank=True,
        default="",
        db_default="",
        validators=[validate_no_mojibake],
    )

    identifier_key = models.CharField(
        max_length=50,
        blank=True,
        default="",
        db_default="",
        # Derived from the scheme registry — registering a scheme is what makes
        # its key legal here; there is no hand-listed enum to keep in sync.
        choices=identifier_key_choices(),
        help_text=(
            "Identifies which URL/ID parsing convention applies to this source's "
            "children (e.g. 'ipdb' → numeric machine IDs, 'opdb' → slug IDs). "
            "Lives on root sources only; children carry `identifier` instead."
        ),
    )

    identifier = models.CharField(
        max_length=CITATION_SOURCE_IDENTIFIER_MAX_LENGTH,
        blank=True,
        default="",
        db_default="",
        help_text=(
            "Structured identifier for this child source within its parent's "
            "scheme (e.g. '4443' for IPDB machine 4443). Empty for root sources "
            "and children without structured identifiers."
        ),
    )

    # NOT the same word as ``CitationInstance.slug`` a few hundred lines below:
    # that one is 8 random consonants behind a ``[[cite:…]]`` marker; this one
    # is an authored kebab handle in the system-wide slug grammar. A plain
    # ``CharField`` (not ``SlugField``, which accepts uppercase and underscores
    # — the API could then mint ``game_room``, a handle no cite could resolve)
    # validated by the same ``SLUG_RE`` entity create and claim validation use.
    slug = models.CharField(
        max_length=CITATION_SOURCE_SLUG_MAX_LENGTH,
        null=True,
        blank=True,
        validators=[RegexValidator(SLUG_RE, SLUG_FORMAT_MESSAGE)],
        help_text=(
            "Authored kebab handle addressing this source in patch cite refs "
            "(<periodical-slug>:<issue-slug>, e.g. billboard:1945-09-29). "
            "Present exactly on slug-addressed types (periodical); null "
            "everywhere else."
        ),
    )

    class Meta:
        ordering = ["name"]
        constraints = [
            field_not_blank("name"),
            field_not_blank("source_type"),
            # Belt-and-suspenders: source_type must be a registered citation
            # type. Derived from ``SourceType`` so a new type flows into
            # makemigrations instead of a hand-edit.
            models.CheckConstraint(
                condition=models.Q(source_type__in=list(SourceType.values)),
                name="citation_citationsource_source_type_valid",
            ),
            self_fk_not_self(
                "parent",
                message="A citation source cannot be its own parent.",
            ),
            # Year range
            models.CheckConstraint(
                condition=models.Q(year__isnull=True)
                | models.Q(year__gte=YEAR_MIN, year__lte=YEAR_MAX),
                name="citation_citationsource_year_range",
            ),
            # Month range
            models.CheckConstraint(
                condition=models.Q(month__isnull=True)
                | models.Q(month__gte=MONTH_MIN, month__lte=MONTH_MAX),
                name="citation_citationsource_month_range",
            ),
            # Day range
            models.CheckConstraint(
                condition=models.Q(day__isnull=True)
                | models.Q(day__gte=DAY_MIN, day__lte=DAY_MAX),
                name="citation_citationsource_day_range",
            ),
            # Date component chains: month requires year, day requires month
            models.CheckConstraint(
                condition=models.Q(month__isnull=True) | models.Q(year__isnull=False),
                name="citation_citationsource_month_requires_year",
                violation_error_message="month requires year.",
                violation_error_code="cross_field",
            ),
            models.CheckConstraint(
                condition=models.Q(day__isnull=True) | models.Q(month__isnull=False),
                name="citation_citationsource_day_requires_month",
                violation_error_message="day requires month.",
                violation_error_code="cross_field",
            ),
            # ISBN: nullable unique, prevent empty string
            nullable_id_not_empty("isbn"),
            # identifier_key must be blank or a registered scheme key. Derived
            # from the scheme registry so a new scheme flows into
            # makemigrations instead of a hand-edit.
            models.CheckConstraint(
                condition=models.Q(identifier_key__in=["", *identifier_key_values()]),
                name="citation_citationsource_identifier_key_valid",
            ),
            # identifier_key lives on roots only
            models.CheckConstraint(
                condition=models.Q(identifier_key="") | models.Q(parent__isnull=True),
                name="citation_citationsource_identifier_key_requires_root",
            ),
            # A scheme root's own type is its scheme's owning type
            # (identifier_key='youtube' implies source_type='video'), so a
            # hierarchy stays uniformly typed. Derived per key from the scheme
            # registry, so a new scheme flows into makemigrations.
            models.CheckConstraint(
                condition=_identifier_key_matches_scheme_type(),
                name="citation_citationsource_identifier_key_scheme_type",
            ),
            # identifier lives on children only
            models.CheckConstraint(
                condition=models.Q(identifier="") | models.Q(parent__isnull=False),
                name="citation_citationsource_identifier_requires_parent",
            ),
            # A source is a scheme-holder OR a value-holder, never both
            models.CheckConstraint(
                condition=~(
                    models.Q(identifier__gt="") & models.Q(identifier_key__gt="")
                ),
                name="citation_citationsource_identifier_key_or_identifier",
            ),
            # No duplicate children with the same identifier under one parent
            models.UniqueConstraint(
                fields=["parent", "identifier"],
                condition=models.Q(identifier__gt=""),
                name="citation_citationsource_unique_child_identifier",
            ),
            # Authored slug (see the field's docstring): never empty, always
            # lowercase — the addressing grammar's cheap DB half; the full
            # ``SLUG_RE`` shape is the field validator's job.
            nullable_id_not_empty("slug"),
            field_lowercase("slug"),
            # Root slugs unique across roots, child slugs unique among
            # siblings. Two constraints, not one: SQL treats NULL parents as
            # distinct, so a plain UNIQUE(parent, slug) would not constrain
            # roots.
            models.UniqueConstraint(
                fields=["slug"],
                condition=models.Q(parent__isnull=True, slug__isnull=False),
                name="citation_citationsource_unique_slug_at_root",
            ),
            models.UniqueConstraint(
                fields=["parent", "slug"],
                condition=models.Q(parent__isnull=False, slug__isnull=False),
                name="citation_citationsource_unique_slug_per_parent",
            ),
            # A slug lives only on — and is required on, root AND child — a
            # slug-addressed type. Both derived from the type registry, so
            # flipping ``slug_addressed`` for a type flows into makemigrations
            # (plus a backfill), never a hand-edit. Required on children too:
            # a periodical child is never auto-minted (periodical isn't
            # flat_hierarchy, so no URL/scheme mint path reaches it), and an
            # unslugged one would be permanently unaddressable.
            models.CheckConstraint(
                condition=models.Q(slug__isnull=True)
                | models.Q(source_type__in=slug_addressed_source_types()),
                name="citation_citationsource_slug_only_when_slug_addressed",
            ),
            models.CheckConstraint(
                condition=models.Q(slug__isnull=False)
                | ~models.Q(source_type__in=slug_addressed_source_types()),
                name="citation_citationsource_slug_required_when_slug_addressed",
            ),
            # A root slug may not shadow the other cite-ref grammars' handles
            # (``isbn``, the scheme keys) — see ``reserved_cite_handles``.
            # Roots only: a child slug is the ref's right segment, where those
            # handles aren't special.
            models.CheckConstraint(
                condition=models.Q(slug__isnull=True)
                | models.Q(parent__isnull=False)
                | ~models.Q(slug__in=reserved_cite_handles()),
                name="citation_citationsource_slug_not_reserved_handle",
            ),
        ]

    @property
    def is_root(self) -> bool:
        """Whether this is a hierarchy root — a source with no parent."""
        return self.parent_id is None

    @property
    def skip_locator(self) -> bool:
        """Whether the cite picker skips this source's locator prompt.

        True for a web child — its URL usually pins the evidence, so the
        picker cites it one-click. Unprompted, not unavailable: the
        edit-evidence panel keeps a collapsed "Add a locator" affordance, and
        a stored locator on such a child is legal on every write path (a
        video post's ``1:35``, a long article's section heading).
        """
        return (
            citation_type_spec(self.source_type).child_skips_locator
            and not self.is_root
        )

    def is_abstract(self, *, has_children: bool) -> bool:
        """Whether the UI should steer away from citing this directly.

        A **per-request display hint, not an enforced write invariant**:
        abstract when it has children (prefer a specific child), or it's a
        platform/site root carrying an ``identifier_key`` (recognition resolves
        a URL to a child under it, so the root is never the cited record), or
        it's a schemeless parentless root of a container type — a periodical or a
        website. A standalone book and a movie (a schemeless parentless video)
        are the work themselves, so they stay valid cite targets; abstractness
        is deliberately *not* used to reject a target.

        The ``identifier_key`` case is universal (every scheme root is a
        container), so it lives here rather than as a per-type flag; the type's
        ``schemeless_parentless_abstract`` decides only the no-scheme case.

        ``has_children`` is supplied by the caller so a bulk lister can pass a
        queryset annotation while a single-row caller passes ``children.exists()``
        — this method issues no query of its own.
        """
        if has_children:
            return True
        if not self.is_root:
            return False
        # A scheme-holding root is a platform/site container — recognition
        # resolves to its children, never the root. Abstract regardless of type.
        if self.identifier_key:
            return True
        # A schemeless parentless root: abstract only when this type's
        # schemeless parentless form is a container (a periodical, a site) and
        # not the work itself (a book, a movie).
        return citation_type_spec(self.source_type).schemeless_parentless_abstract

    def clean(self) -> None:
        super().clean()
        # Guards that read through the parent FK, which a CHECK can't express.
        #
        # Read the parent's facts with one ``values()`` query rather than
        # dereferencing ``self.parent``: a dangling ``parent_id`` then matches
        # no row (guards skip) and the FK field validator owns that error,
        # instead of ``self.parent`` raising a raw ``DoesNotExist``
        # mid-``clean``. The ``in SourceType.values`` guard likewise keeps an
        # invalid ``source_type`` the field validator's error, not a
        # ``ValueError`` from the trait lookup.
        if self.parent_id is None or self.source_type not in SourceType.values:
            return
        spec = citation_type_spec(self.source_type)
        if not (spec.flat_hierarchy or spec.slug_addressed):
            return
        parent_row = (
            CitationSource.objects.filter(pk=self.parent_id)
            .values("parent_id", "identifier_key", "source_type")
            .first()
        )
        if parent_row is None:
            return
        # One level deep, two reasons. Web-flatness: a ``flat_hierarchy`` type
        # nests root → child so recognition can always resolve a host to the
        # root and mint a child directly under it. Slug addressing: the cite
        # ref grammar reaches exactly ``root_slug:child_slug`` and analytics
        # (``citation_tree_too_deep``) resolves roots with a single self-join,
        # so a slugged grandchild would be both unaddressable and misattributed.
        if parent_row["parent_id"] is not None:
            raise ValidationError(
                {
                    "parent": (
                        f"A {self.source_type} source nests only one level deep: "
                        "its parent must be a root (a source with no parent of "
                        "its own)."
                    )
                }
            )
        if not spec.slug_addressed:
            return
        # A slug-addressed child under a scheme root could never be reached:
        # ``<scheme-key>:<anything>`` is permanently consumed by the scheme
        # parser before slug resolution runs.
        if parent_row["identifier_key"]:
            raise ValidationError(
                {
                    "parent": (
                        f"A {self.source_type} source is addressed by its "
                        "parent's slug, so its parent cannot be a scheme root — "
                        "the scheme's cite prefix would shadow the slug."
                    )
                }
            )
        # And its parent must carry a slug to be addressed *by* — i.e. be a
        # root of the same slug-addressed type. A book root has no slug, so an
        # issue nested under it would be permanently unresolvable (resolution
        # joins ``parent__slug``). The API enforces same-type nesting too; this
        # covers admin and direct model writes.
        if parent_row["source_type"] != self.source_type:
            raise ValidationError(
                {
                    "parent": (
                        f"A {self.source_type} source is addressed by its "
                        f"parent's slug, so its parent must be a "
                        f"{self.source_type} root — a "
                        f"{parent_row['source_type']} parent has no slug to "
                        "address it by."
                    )
                }
            )

    def __str__(self) -> str:
        if self.author and self.year:
            return f"{self.name} ({self.author}, {self.year})"
        if self.year:
            return f"{self.name} ({self.year})"
        return self.name


# Short glosses for each link type, joined into the ``link_type`` field's
# help text so the admin dropdown and the API schema explain the choices.
CITATION_LINK_TYPE_HELP = {
    "homepage": "the source's own front page",
    "catalog": "a third-party catalog or database entry (e.g. IPDB)",
    "publisher": "the publisher's page for the work",
    "reference": "the canonical URL of this exact source",
    "archive": "a preserved snapshot such as a Wayback capture",
}


class CitationSourceLink(TimeStampedModel, ActorAttributedModel):
    """A URL where a reader can inspect a CitationSource.

    Wholly owned by its parent CitationSource — CASCADE on delete. A source
    may have zero, one, or many links, distinguished by ``link_type`` — an
    official homepage, a catalog entry, an archive snapshot. Only the URL is
    unique per source; a source may hold several links of the same type.
    """

    class LinkType(models.TextChoices):
        # The source's own front page. Display only — never the recognition
        # signal (recognition keys off CitationSourceRootDomain). Set on roots.
        HOMEPAGE = "homepage", "Homepage"
        # A third-party catalog or database entry for the work (e.g. IPDB).
        CATALOG = "catalog", "Catalog"
        # The publisher's or manufacturer's page for the work.
        PUBLISHER = "publisher", "Publisher"
        # The canonical URL of this exact source — the page or video it *is*.
        # The link the reader UI titles and deep-links.
        REFERENCE = "reference", "Reference"
        # A preserved snapshot: a Wayback capture, an archive.today page, an
        # uploaded scan.
        ARCHIVE = "archive", "Archive"

    citation_source = models.ForeignKey(
        CitationSource,
        on_delete=models.CASCADE,
        related_name="links",
    )
    link_type = models.CharField(
        max_length=20,
        choices=LinkType.choices,
        help_text="; ".join(
            f"{label}: {CITATION_LINK_TYPE_HELP[value]}"
            for value, label in LinkType.choices
        ),
    )
    url = models.URLField(max_length=CITATION_SOURCE_LINK_URL_MAX_LENGTH)
    # Optional. Blank is normal: a link's display name falls back to its
    # link-type name, so a link is never nameless. Set a label only to override
    # that with something more specific ("Google Books preview").
    label = models.CharField(
        max_length=CITATION_SOURCE_LINK_LABEL_MAX_LENGTH,
        blank=True,
        validators=[validate_no_mojibake],
    )

    class Meta:
        ordering = ["citation_source", "link_type", "label"]
        constraints = [
            field_not_blank("url"),
            field_not_blank("link_type"),
            models.CheckConstraint(
                condition=models.Q(
                    link_type__in=[
                        "homepage",
                        "catalog",
                        "publisher",
                        "reference",
                        "archive",
                    ]
                ),
                name="citation_citationsourcelink_link_type_valid",
            ),
            models.UniqueConstraint(
                fields=["citation_source", "url"],
                name="citation_citationsourcelink_unique_source_url",
            ),
        ]

    @property
    def display_name(self) -> str:
        """The link's human text: its label, or its link-type name when blank."""
        return self.label or self.get_link_type_display()

    def __str__(self) -> str:
        if self.label:
            return f"{self.label} ({self.url})"
        return self.url


class CitationSourceRootDomain(TimeStampedModel, ActorAttributedModel):
    """A recognition host owned by a root ``CitationSource``.

    The signal ``recognize_url`` keys off: a normalized host (lowercased,
    ``www.``-stripped — see ``apps.citation.hosts``) that resolves to the root
    that owns it, by longest label-boundary suffix. One root may own many hosts
    (a rebrand's old + new domain, ``.com`` + ``.co.uk``, an asset subdomain).

    Decoupled from the display ``homepage`` ``CitationSourceLink``: editing a
    display link never changes recognition, and there is no derived column to
    keep in sync. ``host`` is globally ``unique`` — two roots cannot claim the
    same recognition host. ``clean()`` canonicalizes ``host`` through
    ``hosts.normalize_host`` (lowercase, ``www.``-strip, trailing-dot), so every
    validated write — admin inline, API, patches — stores a normalized value
    without the caller having to remember. ``clean()`` also rejects a host that
    isn't a syntactic DNS name (an IP literal) or that is a bare public suffix
    (``com``, ``co.uk``) — the latter would over-match every site beneath it
    under longest-suffix recognition. The DB lowercase CHECK is a backstop for
    writes that bypass validation (raw SQL / bulk), which it can only partially
    cover (case, not ``www.``-stripping or the host-shape guard).

    **Root-only.** A domain may attach only to a root (a parentless source). A
    CHECK constraint cannot reach ``source.parent_id`` across the FK, so the
    invariant is enforced in ``clean()`` on every ``full_clean`` path; for rows
    that bypass validation (raw SQL / bulk) recognition keeps a defensive
    ``source__parent__isnull=True`` filter.
    """

    source = models.ForeignKey(
        CitationSource,
        on_delete=models.CASCADE,
        related_name="root_domains",
    )
    host = models.CharField(
        max_length=CITATION_ROOT_DOMAIN_HOST_MAX_LENGTH,
        unique=True,
        error_messages={"unique": CITATION_ROOT_DOMAIN_HOST_TAKEN_MSG},
    )

    class Meta:
        ordering = ["host"]
        constraints = [
            field_not_blank("host"),
            field_lowercase("host"),
        ]

    def clean(self) -> None:
        super().clean()
        self.host = normalize_host(self.host)
        # The universal recognition-host guard, on every validated write (cite-url,
        # admin inline, patch declare). A bare public suffix is the dangerous one:
        # under longest-suffix matching it would resolve every unrelated site
        # beneath it. is_reserved_tld is deliberately NOT checked here — declaring
        # a host is curator-trusted; only the derive funnel rejects reserved TLDs.
        if not is_dns_host(self.host):
            raise ValidationError(
                {
                    "host": "Enter a valid domain name (not an IP address or malformed host)."
                }
            )
        if is_public_suffix(self.host):
            raise ValidationError(
                {
                    "host": (
                        "A bare public suffix (e.g. com, co.uk) can't be a "
                        "recognition host — it would match every site beneath it. "
                        "Use a specific domain such as example.com."
                    )
                }
            )
        # A deliverer host (Amazon, Netflix, …) serves copies of works whose
        # identity lives elsewhere; recognizing it would fabricate identity, so
        # it may never become a recognition domain — on any validated write
        # path (API, admin inline, patch declare). App-level rather than a
        # CHECK constraint: suffix-matching the declared table isn't portable
        # DDL, and the table grows without migrations. ``self.host`` is
        # normalized above; ``normalize_host`` is idempotent, re-applied here
        # only to satisfy the ``Host`` provenance contract.
        deliverer = deliverer_for_host(normalize_host(self.host))
        if deliverer is not None:
            raise ValidationError(
                {
                    "host": (
                        f"{deliverer.label} is a deliverer — its pages are "
                        f"copies of works, not a citable site, so it can't be "
                        f"a recognition host. Cite the works themselves."
                    )
                }
            )
        if self.source_id is not None and not self.source.is_root:
            raise ValidationError(
                {
                    "source": (
                        "A recognition domain may attach only to a root source "
                        "(one with no parent)."
                    )
                }
            )

    def __str__(self) -> str:
        return self.host


# ---------------------------------------------------------------------------
# CitationInstance: a specific use of a CitationSource with a locator.
# ---------------------------------------------------------------------------

CITATION_INSTANCE_LOCATOR_MAX_LENGTH = 200
# Must clear the longest historical note-quote the backfill moves here (831
# chars measured); matches the old Claim.citation cap.
CITATION_INSTANCE_QUOTE_MAX_LENGTH = 2_000

# Slug alphabet: lowercase consonants only (vowels dropped). Digit-free so a
# slug can never collide with a numeric same-patch cite handle, and vowel-free
# so a slug can't accidentally spell a real word. 21 chars ^ 8 ≈ 3.8e10 space.
CITATION_SLUG_ALPHABET = "bcdfghjklmnpqrstvwxyz"
CITATION_SLUG_LENGTH = 8
# Retries on the (vanishingly rare) unique-slug collision before giving up.
_MINT_MAX_ATTEMPTS = 5

_SLUG_RE = re.compile(rf"\A[{CITATION_SLUG_ALPHABET}]{{{CITATION_SLUG_LENGTH}}}\Z")

# Register so the slug-length CHECK constraint below can use ``slug__length``.
# Django ships Length but doesn't auto-register it (it adds a query-time call by
# default); register_lookup is idempotent, so doing it here is safe even though
# apps.accounts also registers it.
models.CharField.register_lookup(Length)


def generate_citation_slug() -> str:
    """Generate a random, digit-free, author-stable citation slug.

    Not collision-checked here — uniqueness is enforced by the DB constraint
    and the mint helper's savepoint-wrapped retry.
    """
    return get_random_string(CITATION_SLUG_LENGTH, CITATION_SLUG_ALPHABET)


def validate_citation_slug(value: str) -> None:
    """Enforce the slug grammar: exactly ``CITATION_SLUG_LENGTH`` lowercase
    consonants (digit-free, vowel-free).

    Load-bearing: Step 2 classifies a cite marker handle lexically (all-digits =
    a new citation, all-lowercase-letters = an existing slug), so a digit or
    wrong-length slug would later be emitted by ``convert_storage_to_authoring``
    and rejected by the patch grammar. The charset half can't be a portable DB
    CHECK (``__regex`` isn't enforceable in SQLite CHECK DDL), so it lives here;
    the DB carries only the cross-backend length CHECK.
    """
    if not _SLUG_RE.match(value):
        raise ValidationError(
            f"Invalid citation slug {value!r}: expected {CITATION_SLUG_LENGTH} "
            "lowercase consonants (digit-free, vowel-free)."
        )


class CitationInstanceManager(models.Manager["CitationInstance"]):
    """Manager whose ``mint_many`` assigns unique slugs before ``bulk_create``.

    Single-row creates (``save()``/``objects.create()``) get their slug from
    ``CitationInstance.save()``. ``bulk_create`` skips ``save()``, so the bulk
    paths (ingest's scalar attach, and step 2's inline materialize) must go
    through here to populate the NOT NULL/unique ``slug`` column.
    """

    def mint_many(self, instances: list[CitationInstance]) -> list[CitationInstance]:
        """Assign unique slugs to every instance and ``bulk_create`` them.

        On a unique-slug collision we can't tell which row clashed (a partial
        ``bulk_create`` reports nothing), so regenerate ALL slugs and retry the
        whole batch. Each attempt runs in its own ``atomic()`` savepoint: a
        caller may already be inside ``transaction.atomic()`` (the ingest apply
        path is), where an ``IntegrityError`` poisons the outer transaction —
        the savepoint lets the failed insert roll back and the retry run clean.

        A generated slug must also dodge live ``ReservedCitationSlug`` rows —
        a separate table, so the instance unique constraint can't catch the
        clash and minting one would break the reservation-holding draft's
        save. One existence query per attempt covers the whole batch.
        """
        if not instances:
            return []
        for attempt in range(_MINT_MAX_ATTEMPTS):
            for inst in instances:
                inst.slug = generate_citation_slug()
            if ReservedCitationSlug.objects.filter(
                slug__in=[inst.slug for inst in instances]
            ).exists():
                continue
            try:
                with transaction.atomic():
                    self.bulk_create(instances)
                return instances
            except IntegrityError:
                if attempt == _MINT_MAX_ATTEMPTS - 1:
                    raise
        raise IntegrityError(
            f"Could not mint unique citation slugs after {_MINT_MAX_ATTEMPTS} attempts."
        )


class CitationInstance(models.Model):
    """A specific use of a CitationSource, with a locator and a verbatim quote.

    Immutable: corrections create a new instance (old one becomes orphaned).
    Only has created_at, no updated_at — matching the Claim immutability pattern.

    An instance is shared evidence: scalar/edit claims reach it through the
    ``ClaimCitationInstance`` join, and inline markdown citations
    (``[[cite:id:...]]``) reach it through their marker alone.

    ``slug`` is a globally-unique, digit-free, author-stable handle. It is the
    authoring key for the ``cite`` wikilink type (``[[cite:<slug>]]`` authoring
    ↔ ``[[cite:id:<pk>]]`` storage). Every instance carries one, including
    scalar/edit cites whose slug simply goes unused — a uniform column beats a
    conditional constraint. Assigned at mint, immutable.
    """

    citation_source_id: CitationSourceId

    slug = models.CharField(max_length=CITATION_SLUG_LENGTH, unique=True)
    citation_source = models.ForeignKey(
        "citation.CitationSource",
        on_delete=models.PROTECT,
        related_name="instances",
    )
    locator = models.CharField(
        max_length=CITATION_INSTANCE_LOCATOR_MAX_LENGTH,
        blank=True,
        default="",
        db_default="",
        validators=[validate_no_mojibake],
    )
    # A verbatim excerpt from the source: only exact source text and "[...]"
    # ellipses belong here — a reviewer should be able to follow the citation's
    # URL and ctrl-F find each span. Interpretation, translation and rationale
    # go in ChangeSet.note instead.
    #
    # No validate_no_mojibake here, unlike our authored fields: a faithful quote
    # of a garbled source is itself garbled (e.g. IPDB serves a literal U+FFFD),
    # and reproducing that verbatim is correct. flippatch's
    # verify-quote-verbatim gate guards quote fidelity against the canonical
    # cached source upstream.
    quote = BoundedTextField(
        max_length=CITATION_INSTANCE_QUOTE_MAX_LENGTH,
        blank=True,
        default="",
        db_default="",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    objects = CitationInstanceManager()

    class Meta:
        # The model began life in the provenance app and was relocated here
        # with a state-only migration; the table was never renamed.
        db_table = "provenance_citationinstance"
        constraints = [
            # Cross-backend belt for the slug length. The charset half is
            # app-layer (validate_citation_slug) since __regex isn't enforceable
            # in SQLite CHECK DDL; this catches a wrong-length slug even on the
            # bulk_create path that skips save().
            models.CheckConstraint(
                condition=models.Q(slug__length=CITATION_SLUG_LENGTH),
                name="prov_citinst_slug_length",
            ),
        ]
        indexes = [
            models.Index(
                fields=["citation_source"],
                name="prov_citinst_source_idx",
            ),
        ]

    def __str__(self) -> str:
        loc = f" @ {self.locator}" if self.locator else ""
        return f"Citation: {self.citation_source_id}{loc}"

    # Django's Model.save signature is owned by the framework; the override
    # only enforces immutability before delegating upstream.
    def save(
        self,
        *args: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        if self.pk is not None:
            raise ValueError(
                "CitationInstance is immutable. Create a new instance instead."
            )
        # Assign a slug on create when one wasn't set explicitly. bulk_create
        # skips save(), so those paths must use the manager's mint_many() — see
        # CitationInstanceManager. A (vanishingly rare) collision here surfaces
        # as IntegrityError; the bulk path additionally retries under a savepoint.
        # A generated slug must dodge live reservations (separate table, so the
        # unique constraint can't catch it); an explicit slug is exempt — it IS
        # a reservation being consumed by the save-time mint.
        if not self.slug:
            for _ in range(_MINT_MAX_ATTEMPTS):
                candidate = generate_citation_slug()
                if not ReservedCitationSlug.objects.filter(slug=candidate).exists():
                    self.slug = candidate
                    break
            else:
                raise IntegrityError(
                    "Could not generate a citation slug clear of reservations "
                    f"after {_MINT_MAX_ATTEMPTS} attempts."
                )
        # save() is the one chokepoint that sees every explicit slug: the API and
        # field-evidence paths call full_clean(exclude=["slug"]) (slug isn't set
        # yet there) and bulk_create skips save() entirely, so a field-level
        # validator would never fire. Validating here covers explicit slugs and
        # re-checks the generated one for free; bulk leans on the generator plus
        # the DB length CHECK.
        validate_citation_slug(self.slug)
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# ReservedCitationSlug: a slug held for a pending inline cite in a draft.
# ---------------------------------------------------------------------------


class ReservedCitationSlug(models.Model):
    """A citation slug reserved for a draft's pending inline cite.

    The interactive editor reserves a slug the moment the citation picker
    completes, places a ``[[cite:<slug>]]`` marker in the draft, and defers
    minting the immutable ``CitationInstance`` to save time (the save handler
    consumes the reservation in the ChangeSet transaction). The row is a bare
    slug on purpose: the moment it carries source/locator/quote it has rebuilt
    the eager mint with its immutability and orphan problems.

    No TTL, no sweep, ever. A reservation may be held by a long-lived draft
    (autosave recovery, a tab open for weeks); expiry would break that draft's
    save. An abandoned reservation is inert junk — a burned random string —
    unlike an orphaned instance, which is wrong data.
    """

    slug = models.CharField(max_length=CITATION_SLUG_LENGTH, unique=True)
    # CASCADE: a reservation is wholly owned by the drafting user — their
    # drafts (and thus any save that could consume it) die with the account.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reserved_citation_slugs",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_default=Now())

    class Meta:
        constraints = [
            # Same cross-backend length belt as CitationInstance.slug; the
            # charset half stays app-layer (validate_citation_slug in save()).
            models.CheckConstraint(
                condition=models.Q(slug__length=CITATION_SLUG_LENGTH),
                name="citation_reserved_slug_length",
            ),
        ]

    def __str__(self) -> str:
        return f"Reserved citation slug: {self.slug}"

    # Django's Model.save signature is owned by the framework; the override
    # only validates the slug grammar before delegating upstream.
    def save(
        self,
        *args: Any,  # noqa: ANN401
        **kwargs: Any,  # noqa: ANN401
    ) -> None:
        validate_citation_slug(self.slug)
        super().save(*args, **kwargs)


def reserve_citation_slug(user: User) -> ReservedCitationSlug:
    """Reserve a fresh citation slug for *user* and return the row.

    The insert is the uniqueness guarantee (no concurrent-draft race): each
    attempt generates a candidate, skips it if an instance already holds it,
    and lets the reservation table's unique constraint arbitrate concurrent
    reservers. Each insert runs in its own savepoint so a collision doesn't
    poison a caller's open transaction.
    """
    for attempt in range(_MINT_MAX_ATTEMPTS):
        candidate = generate_citation_slug()
        if CitationInstance.objects.filter(slug=candidate).exists():
            continue
        try:
            with transaction.atomic():
                return ReservedCitationSlug.objects.create(
                    slug=candidate, created_by=user
                )
        except IntegrityError:
            if attempt == _MINT_MAX_ATTEMPTS - 1:
                raise
    raise IntegrityError(
        f"Could not reserve a unique citation slug after {_MINT_MAX_ATTEMPTS} attempts."
    )
