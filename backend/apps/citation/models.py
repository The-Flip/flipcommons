"""Citation source models: works and evidence objects that can be cited."""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from apps.citation.hosts import normalize_host
from apps.citation.source_type_traits import SourceType, source_type_traits
from apps.core.models import (
    BoundedTextField,
    TimeStampedModel,
    field_lowercase,
    field_not_blank,
    nullable_id_not_empty,
)
from apps.core.validators import validate_no_mojibake

__all__ = ["CitationSource", "CitationSourceLink", "CitationSourceRootDomain"]

YEAR_MIN, YEAR_MAX = 1800, 2100
MONTH_MIN, MONTH_MAX = 1, 12
DAY_MIN, DAY_MAX = 1, 31

CITATION_SOURCE_NAME_MAX_LENGTH = 500
CITATION_SOURCE_AUTHOR_MAX_LENGTH = 300
CITATION_SOURCE_PUBLISHER_MAX_LENGTH = 300
CITATION_SOURCE_DATE_NOTE_MAX_LENGTH = 200
CITATION_SOURCE_ISBN_MAX_LENGTH = 20
CITATION_SOURCE_IDENTIFIER_MAX_LENGTH = 200
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


class CitationSourceQuerySet(models.QuerySet["CitationSource"]):
    """Adds the root/child split the whole citation hierarchy turns on."""

    def roots(self) -> CitationSourceQuerySet:
        """Top-level sources with no parent (books, magazines, website roots)."""
        return self.filter(parent__isnull=True)

    def children(self) -> CitationSourceQuerySet:
        """Sources nested under a parent (editions, articles, pages, records)."""
        return self.filter(parent__isnull=False)


CitationSourceManager = models.Manager.from_queryset(CitationSourceQuerySet)


class CitationSource(TimeStampedModel):
    """A work or evidence object that can be cited: book, flyer, web page, etc.

    NOT claims-controlled — edited directly through admin or future UI.
    Hierarchy via self-referential parent FK enables grouping (e.g., article
    within magazine issue, edition within book).
    """

    id: int
    objects = CitationSourceManager()
    links: models.Manager[CitationSourceLink]
    root_domains: models.Manager[CitationSourceRootDomain]
    parent_id: int | None

    # ``SourceType`` and its per-type trait table live in
    # ``source_type_traits.py`` (a dependency-free leaf, so ``models`` imports it
    # without a cycle); re-exported here so ``CitationSource.SourceType`` stays
    # the canonical handle.
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
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    description = BoundedTextField(
        max_length=CITATION_SOURCE_DESCRIPTION_MAX_LENGTH,
        blank=True,
        default="",
        db_default="",
        validators=[validate_no_mojibake],
    )

    class IdentifierKey(models.TextChoices):
        IPDB = "ipdb", "IPDB"
        OPDB = "opdb", "OPDB"
        YOUTUBE = "youtube", "YouTube"

    identifier_key = models.CharField(
        max_length=50,
        blank=True,
        default="",
        db_default="",
        choices=IdentifierKey.choices,
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

    class Meta:
        ordering = ["name"]
        constraints = [
            field_not_blank("name"),
            field_not_blank("source_type"),
            # Belt-and-suspenders: source_type must be a valid enum value
            models.CheckConstraint(
                condition=models.Q(source_type__in=["book", "magazine", "web"]),
                name="citation_citationsource_source_type_valid",
            ),
            # Prevent self-referencing
            models.CheckConstraint(
                condition=models.Q(parent__isnull=True)
                | ~models.Q(parent=models.F("pk")),
                name="citation_citationsource_parent_not_self",
                violation_error_message="A citation source cannot be its own parent.",
                violation_error_code="cross_field",
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
            # identifier_key must be blank or a valid enum value
            models.CheckConstraint(
                condition=models.Q(identifier_key__in=["", "ipdb", "opdb", "youtube"]),
                name="citation_citationsource_identifier_key_valid",
            ),
            # identifier_key lives on roots only
            models.CheckConstraint(
                condition=models.Q(identifier_key="") | models.Q(parent__isnull=True),
                name="citation_citationsource_identifier_key_requires_root",
            ),
            # identifier_key is for web sources only
            models.CheckConstraint(
                condition=models.Q(identifier_key="") | models.Q(source_type="web"),
                name="citation_citationsource_identifier_key_requires_web",
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
        ]

    @property
    def is_root(self) -> bool:
        """Whether this is a hierarchy root — a source with no parent."""
        return self.parent_id is None

    @property
    def skip_locator(self) -> bool:
        """Web children skip the locator stage — their URL is the locator."""
        return (
            source_type_traits(self.source_type).child_skips_locator
            and not self.is_root
        )

    def is_abstract(self, *, has_children: bool) -> bool:
        """Whether the UI should steer away from citing this directly.

        A **per-request display hint, not an enforced write invariant**:
        abstract when it has children (prefer a specific child) or it's a
        parentless web/magazine root (a site/publication container). "Don't
        cite a web root" is handled structurally, not by a citation-time guard:
        URL recognition always resolves to a child under the matched root, so an
        abstract web/magazine root is never the cited record. A standalone book
        stays a valid cite target whether or not it gains editions, so
        abstractness is deliberately *not* used to reject a target.

        ``has_children`` is supplied by the caller so a bulk lister can pass a
        queryset annotation while a single-row caller passes ``children.exists()``
        — this method issues no query of its own.
        """
        return has_children or (
            self.is_root and source_type_traits(self.source_type).parentless_abstract
        )

    def clean(self) -> None:
        super().clean()
        # D2 web-flatness: a ``flat_hierarchy`` type (web) nests exactly one
        # level — root → child — so recognition can always resolve a host to the
        # root and mint a child directly under it. A grandchild (its parent is
        # itself a child) would be unreachable, so reject it.
        #
        # Test the parent's rootness with a ``children()`` ``exists()`` query
        # rather than dereferencing ``self.parent``: a dangling ``parent_id``
        # then matches no row (guard skips) and the FK field validator owns that
        # error, instead of ``self.parent`` raising a raw ``DoesNotExist``
        # mid-``clean``. The ``in SourceType.values`` guard likewise keeps an
        # invalid ``source_type`` the field validator's error, not a
        # ``ValueError`` from the trait lookup.
        if (
            self.parent_id is not None
            and self.source_type in SourceType.values
            and source_type_traits(self.source_type).flat_hierarchy
            and CitationSource.objects.children().filter(pk=self.parent_id).exists()
        ):
            raise ValidationError(
                {
                    "parent": (
                        f"A {self.source_type} source nests only one level deep: "
                        "its parent must be a root (a source with no parent of "
                        "its own)."
                    )
                }
            )

    def __str__(self) -> str:
        if self.author and self.year:
            return f"{self.name} ({self.author}, {self.year})"
        if self.year:
            return f"{self.name} ({self.year})"
        return self.name


class CitationSourceLink(TimeStampedModel):
    """A URL where a reader can inspect a CitationSource.

    Wholly owned by its parent CitationSource — CASCADE on delete.
    A source may have zero, one, or many links (e.g., archive.org
    scan, publisher page, Google Books preview).
    """

    class LinkType(models.TextChoices):
        HOMEPAGE = "homepage", "Homepage"
        CATALOG = "catalog", "Catalog"
        PUBLISHER = "publisher", "Publisher"
        REFERENCE = "reference", "Reference"
        ARCHIVE = "archive", "Archive"

    citation_source = models.ForeignKey(
        CitationSource,
        on_delete=models.CASCADE,
        related_name="links",
    )
    link_type = models.CharField(max_length=20, choices=LinkType.choices)
    url = models.URLField(max_length=CITATION_SOURCE_LINK_URL_MAX_LENGTH)
    label = models.CharField(
        max_length=CITATION_SOURCE_LINK_LABEL_MAX_LENGTH,
        blank=True,
        validators=[validate_no_mojibake],
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
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

    def __str__(self) -> str:
        if self.label:
            return f"{self.label} ({self.url})"
        return self.url


class CitationSourceRootDomain(TimeStampedModel):
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
    without the caller having to remember. The DB lowercase CHECK is a backstop
    for writes that bypass validation (raw SQL / bulk), which it can only
    partially cover (case, not ``www.``-stripping).

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
