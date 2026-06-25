"""Rich-text rendering helpers for the generic entity HTTP surface.

Domain-neutral: builds the ``RichTextSchema`` (authoring text, rendered HTML,
plain projection, inline citations and winning-claim attribution) for any text
field on any model. The per-entity detail/list serializers in the domain routers
call these downward (domain → engine, the sanctioned edge).
"""

from __future__ import annotations

from collections.abc import Iterable

from django.db import models

from apps.core.markdown import convert_storage_to_authoring, render_markdown_field
from apps.provenance.attribution import source_backing
from apps.provenance.helpers import active_claims
from apps.provenance.licensing import (
    build_source_field_license_map,
    resolve_effective_license,
)
from apps.provenance.models import Claim, ClaimControlledModel
from apps.provenance.schemas import (
    AttributionSchema,
    InlineCitationSchema,
    RichTextSchema,
)

__all__ = ["build_rich_text", "describe"]


def _extract_description_attribution(
    active_claims: Iterable[Claim],
) -> AttributionSchema | None:
    """Return AttributionSchema for the winning description claim, or None.

    Expects active_claims to be ordered by claim_key, -priority, -created_at
    (the standard prefetch ordering).
    """
    sfl_map = None
    for claim in active_claims:
        if claim.field_name == "description":
            if sfl_map is None:
                sfl_map = build_source_field_license_map()
            lic = resolve_effective_license(claim, sfl_map)
            src = source_backing(claim.actor)
            return AttributionSchema(
                license_slug=lic.slug if lic else None,
                license_name=lic.short_name if lic else None,
                license_url=lic.url if lic else None,
                permissiveness_rank=lic.permissiveness_rank if lic else None,
                requires_attribution=lic.requires_attribution if lic else False,
                source_name=src.name if src else None,
                source_url=src.url if src else None,
                attribution_text=claim.citation or None,
            )
    return None


def build_rich_text(
    obj: models.Model,
    field_name: str,
    active_claims: Iterable[Claim] | None = None,
) -> RichTextSchema:
    """Build a RichTextSchema for a text field with attribution.

    Reads the raw text from obj.{field_name}, renders HTML via
    render_markdown_field, and extracts attribution from the winning claim.

    The ``text`` value is returned in authoring format (``[[type:slug]]``)
    so edit forms show human-readable link references.  The ``html`` value
    is rendered from the storage format and is display-ready.  The ``plain``
    value is the flattened, token-free projection for meta descriptions and
    machine-readable consumers.
    """
    raw_text = getattr(obj, field_name, "") or ""
    text = convert_storage_to_authoring(raw_text) if raw_text else raw_text
    rendered = render_markdown_field(obj, field_name)
    citations = [InlineCitationSchema.model_validate(c) for c in rendered.citations]

    attribution = None
    if active_claims is not None:
        attribution = _extract_description_attribution(active_claims)

    return RichTextSchema(
        text=text,
        html=rendered.html,
        plain=rendered.plain,
        citations=citations,
        attribution=attribution,
    )


def describe(obj: ClaimControlledModel) -> RichTextSchema:
    """Build the description RichTextSchema for any claim-controlled entity.

    Bound to ``ClaimControlledModel`` — what ``active_claims(obj)`` requires.
    The entity must also carry a ``description`` field (``DescribedModel``),
    read dynamically by ``build_rich_text``; the two capabilities have no
    common base below catalog, and inventing a one-off ABC to conjoin them for
    this single caller isn't worth it.
    """
    return build_rich_text(obj, "description", active_claims(obj))
