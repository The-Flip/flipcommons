"""The mint primitive for CitationInstance rows.

The single write path for individual citation instances, shared by the two
consumers of the content-spec schema: the standalone create endpoint (inline
``[[cite:slug]]`` cites, which need the slug immediately) and the claim save
handler (edit cites, which ride the save payload's ``citations`` list). Bulk
ingest minting stays on ``CitationInstance.objects.mint_many``.
"""

from __future__ import annotations

from apps.citation.models import CitationInstance

from .schemas import CitationInstanceCreateSchema


def create_citation_instance(spec: CitationInstanceCreateSchema) -> CitationInstance:
    """Mint one immutable ``CitationInstance`` from a content spec.

    Raises ``ValidationError`` when the spec is invalid (including an unknown
    ``citation_source_id`` — the FK existence check runs in ``full_clean``) and
    ``IntegrityError`` on the vanishingly rare slug collision; callers map
    those to their surface's error shape.
    """
    instance = CitationInstance(
        citation_source_id=spec.citation_source_id,
        locator=spec.locator,
        quote=spec.quote,
    )
    # slug is assigned in CitationInstance.save(); exclude it from validation,
    # which runs first and would otherwise see it blank.
    instance.full_clean(exclude=["slug"])
    instance.save()
    return instance
