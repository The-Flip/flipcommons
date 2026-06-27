"""Claim- and source-aware license resolution."""

from __future__ import annotations

from typing import NamedTuple

from apps.core.models import License
from apps.core.types import ClaimFieldName
from apps.provenance.attribution import source_backing
from apps.provenance.models import Claim, SourceFieldLicense


class SourceField(NamedTuple):
    """A (source, claim-field) pair — the granularity at which a source
    declares a license."""

    source_id: int
    field_name: ClaimFieldName


# Prefetched SourceField → license lookup, built once per request by
# build_source_field_license_map() to avoid N+1 queries when resolving effective
# licenses for many claims.
type SourceFieldLicenseMap = dict[SourceField, License | None]


def build_source_field_license_map() -> SourceFieldLicenseMap:
    """Prefetch all SourceFieldLicense rows into a SourceField → license lookup."""
    return {
        SourceField(sfl.source_id, sfl.field_name): sfl.license
        for sfl in SourceFieldLicense.objects.select_related("license").all()
    }


def resolve_effective_license(
    claim: Claim,
    sfl_map: SourceFieldLicenseMap | None = None,
) -> License | None:
    """Resolve the effective license for a claim.

    Resolution order:
    1. claim.license (per-claim override)
    2. SourceFieldLicense for (source backing the claim's actor, claim.field_name)
    3. the backing source's default_license (source-wide default)
    4. None (unknown)

    Still source-only: user-backed actors have no source, so steps 2-3 are
    skipped and the claim resolves to its per-claim override or None — exactly
    the old ``claim.source is None`` behavior.
    """
    if claim.license_id:
        return claim.license
    source = source_backing(claim.actor)
    if source is not None:
        if sfl_map is not None:
            sfl_license = sfl_map.get(SourceField(source.pk, claim.field_name))
            if sfl_license:
                return sfl_license
        return source.default_license
    return None
