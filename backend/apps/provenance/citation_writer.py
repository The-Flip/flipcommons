"""The mint primitive for CitationInstance rows.

The single write path for individual citation instances, shared by the two
save-payload channels of the content-spec schema: edit cites (the ``citations``
evidence list, minted with a fresh slug) and inline cites (the
``inline_citations`` list, minted under the reserved slug their
``[[cite:slug]]`` marker already carries). Bulk ingest minting stays on
``CitationInstance.objects.mint_many``.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError

from apps.citation.locators import normalized_locator
from apps.citation.models import CitationInstance, CitationSource

from .schemas import CitationInstanceCreateSchema


def create_citation_instance(
    spec: CitationInstanceCreateSchema, *, slug: str = ""
) -> CitationInstance:
    """Mint one immutable ``CitationInstance`` from a content spec.

    Pass *slug* to mint under a reserved citation slug (the inline-cite path);
    leave it empty for a fresh generated slug (the evidence path). The locator
    is validated and canonicalized against the cited source's citation-type
    contract (a video cite's timestamp is normalized; freeform types pass
    through). Raises ``ValidationError`` when the spec is invalid (including
    an unknown ``citation_source_id`` — checked here for the locator lookup,
    and again by ``full_clean``'s FK existence check) and ``IntegrityError``
    on the vanishingly rare slug collision; callers map those to their
    surface's error shape.
    """
    source_type = (
        CitationSource.objects.filter(pk=spec.citation_source_id)
        .values_list("source_type", flat=True)
        .first()
    )
    if source_type is None:
        raise ValidationError({"citation_source_id": "Citation source does not exist."})
    instance = CitationInstance(
        citation_source_id=spec.citation_source_id,
        locator=normalized_locator(source_type, spec.locator),
        quote=spec.quote,
        slug=slug,
    )
    # An empty slug is assigned in CitationInstance.save(); exclude it from
    # validation, which runs first and would otherwise see it blank. An
    # explicit slug is validated by save() (grammar) and the unique constraint.
    instance.full_clean(exclude=["slug"])
    instance.save()
    return instance
