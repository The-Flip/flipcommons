"""Image-field license denormalization, shared by the resolve write paths.

Image claim values (``opdb.images``, ``ipdb.image_urls``, ``image_urls``) land
in ``extra_data`` rather than a typed column. The read API gates and attributes
those images by a denormalized license, so resolution stamps the winning claim's
effective license beside the value.

This lives in a leaf module — not ``resolve/__init__.py`` — so ``_entities.py``
can import it without an import cycle (``__init__`` already imports ``_entities``).
"""

from __future__ import annotations

from apps.core.types import JsonBody
from apps.provenance.licensing import SourceFieldLicenseMap, resolve_effective_license
from apps.provenance.models import Claim

# Claim field_names whose values are images. License metadata for these fields
# gets denormalized into extra_data so the read API can gate by
# permissiveness_rank without joining back through claims.
IMAGE_FIELDS = frozenset({"opdb.images", "ipdb.image_urls", "image_urls"})


def _stamp_image_license(
    extra_data: JsonBody, claim: Claim, sfl_map: SourceFieldLicenseMap | None
) -> None:
    """Denormalize *claim*'s effective license into *extra_data*, for image fields.

    Writes ``{field}.__license_slug`` and ``{field}.__permissiveness_rank``
    beside the already-stored image value; a no-op for non-image claims. Shared
    by the MachineModel path (``_apply_resolution``) and the generic path
    (``_entities._resolve_single`` / ``_resolve_bulk``) so both stamp
    identically.
    """
    if claim.field_name not in IMAGE_FIELDS:
        return
    lic = resolve_effective_license(claim, sfl_map)
    extra_data[f"{claim.field_name}.__license_slug"] = lic.slug if lic else None
    extra_data[f"{claim.field_name}.__permissiveness_rank"] = (
        lic.permissiveness_rank if lic else None
    )
