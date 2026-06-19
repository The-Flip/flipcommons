"""Get-or-create citation sources for the data-patch ``sources:`` block.

The patch path (``apps.claim_ingest``) is the only caller. It is flat
(roots only) and **additive-only**: ``ensure_root_source`` creates a missing
source or backfills a missing link, but never overwrites an existing row or
link. A collision is a warning, never a failure — so a user-created source
can't wedge the patch queue. See ``docs/DataPatches.md``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, NamedTuple

from apps.citation.seed_data.types import SeedLink, SeedSource

if TYPE_CHECKING:
    from apps.citation.models import CitationSource


# Fields that are model columns (excluding children, links, and parent).
_SOURCE_FIELDS = frozenset(
    {
        "name",
        "source_type",
        "author",
        "publisher",
        "year",
        "month",
        "day",
        "date_note",
        "isbn",
        "description",
        "identifier_key",
    }
)


class SourceUpsertResult(NamedTuple):
    """Outcome of one ``ensure_root_source`` call, tallied by the caller.

    Source-agnostic by design: the data-patch hook reads these counts into its
    ``RunReport`` (a catalog type the citation app must not import).
    """

    source_created: bool
    links_created: int


# ---------------------------------------------------------------------------
# Shared leaf primitives (used by both the seed walk and the patch path)
# ---------------------------------------------------------------------------


def _source_fields(node: SeedSource) -> dict[str, object]:
    """The model-column subset of a seed/patch node (no parent/links/children)."""
    return {k: v for k, v in node.items() if k in _SOURCE_FIELDS}


def _lookup_source(fields: dict[str, object]) -> tuple[CitationSource | None, int]:
    """Find an existing source by the soft natural key. Returns (first, count).

    Keys on ``isbn`` when present (DB-unique → at most one), else on
    ``(name, source_type)`` scoped to parentless rows (count can exceed 1; the
    caller decides what to do).

    The ``(name, source_type)`` match is root-scoped because the patch path
    creates *roots*: a same-named child (one a ``cite:`` minted, say) must not
    shadow the root it should create — otherwise the root is never made and
    links land on a child, where ``recognize_url`` can't see them. The ``isbn``
    path is deliberately **not** scoped: ``isbn`` is globally unique (a flat
    book root carries one), and excluding a child that holds the isbn would
    force a create that violates the unique constraint.
    """
    from apps.citation.models import CitationSource

    isbn = fields.get("isbn")
    if isbn:
        obj = CitationSource.objects.filter(isbn=isbn).first()
        return obj, (1 if obj is not None else 0)
    qs = CitationSource.objects.filter(
        name=fields["name"], source_type=fields["source_type"], parent__isnull=True
    )
    return qs.first(), qs.count()


def _create_source(fields: dict[str, object]) -> CitationSource:
    """Validate + save a new ``CitationSource``. ``fields`` may include ``parent``."""
    from apps.citation.models import CitationSource

    obj = CitationSource(**fields)
    obj.full_clean()
    obj.save()
    return obj


def _create_link(source: CitationSource, link: SeedLink) -> None:
    """Validate + save a single ``CitationSourceLink`` on ``source``."""
    from apps.citation.models import CitationSourceLink

    obj = CitationSourceLink(
        citation_source=source,
        url=link["url"],
        label=link.get("label", ""),
        link_type=link["link_type"],
    )
    obj.full_clean()
    obj.save()


# ---------------------------------------------------------------------------
# Data-patch path: read-phase validation + additive get-or-create
# ---------------------------------------------------------------------------


def validate_root_source(node: SeedSource) -> None:
    """Field-validate a patch ``sources:`` node in memory (no writes).

    Builds the ``CitationSource`` and its ``CitationSourceLink`` rows and runs
    ``full_clean`` on them with **DB-uniqueness off** — a node that legitimately
    matches an existing row (the additive get-or-create's "found" case) must not
    be rejected, and an in-memory link's required FK is unset. Catches bad
    ``source_type``, out-of-range dates, invalid ``identifier_key``, malformed
    URL, invalid ``link_type``, and duplicate declared link URLs. Raises
    :class:`django.core.exceptions.ValidationError`; the patch adapter maps it to
    a ``PatchError`` (so it surfaces at ``--dry-run`` before shipping).
    """
    from django.core.exceptions import ValidationError

    from apps.citation.models import CitationSource, CitationSourceLink

    source = CitationSource(**_source_fields(node))
    source.full_clean(validate_unique=False)

    seen_urls: set[str] = set()
    for link in node.get("links", []):
        url = link["url"]
        if url in seen_urls:
            raise ValidationError({"links": f"duplicate declared link URL {url!r}"})
        seen_urls.add(url)
        obj = CitationSourceLink(
            url=url,
            label=link.get("label", ""),
            link_type=link["link_type"],
        )
        obj.full_clean(exclude=["citation_source"], validate_unique=False)


def ensure_root_source(
    node: SeedSource,
    *,
    warnings: list[str],
) -> SourceUpsertResult:
    """Additively get-or-create a flat (root) citation source. Never overwrites.

    Look up by the soft natural key (``isbn`` / ``(name, source_type)``),
    root-scoped on the name path so a same-named child can't shadow the root.
    On >1 match, operate on the first and warn. If absent, create the source +
    all its declared links (``parent=None``). If present, leave the row untouched
    (warn if declared fields diverge) and ensure each declared link additively —
    create a missing URL, no-op an identical one, warn on a
    same-URL/different-type-or-label one. Never raises on a collision; the caller
    tallies the returned counts.
    """
    fields = _source_fields(node)
    name = fields["name"]
    source_type = fields["source_type"]
    obj, match_count = _lookup_source(fields)

    if match_count > 1:
        warnings.append(
            f"Citation source ({name!r}, {source_type!r}) matched {match_count} "
            f"rows; operated on the first."
        )

    links = node.get("links", [])

    if obj is None:
        obj = _create_source({**fields, "parent": None})
        for link in links:
            _create_link(obj, link)
        return SourceUpsertResult(source_created=True, links_created=len(links))

    # Found: never overwrite the row; warn on any declared-field divergence.
    divergent = sorted(k for k, v in fields.items() if getattr(obj, k) != v)
    if divergent:
        warnings.append(
            f"Citation source {name!r} already exists; declared fields "
            f"{divergent} differ from the stored values and were left unchanged."
        )

    # Additive links: create a missing URL, warn on a divergent same-URL link.
    existing = {link.url: link for link in obj.links.all()}
    links_created = 0
    for link in links:
        url = link["url"]
        current = existing.get(url)
        if current is None:
            _create_link(obj, link)
            links_created += 1
        elif current.link_type != link["link_type"] or current.label != link.get(
            "label", ""
        ):
            warnings.append(
                f"Citation source {name!r} link {url!r} already exists with a "
                f"different type/label; left unchanged."
            )
    return SourceUpsertResult(source_created=False, links_created=links_created)
