"""Claim resolution — the provenance-local resolve-dispatch seam.

Today this package holds only the dispatch registry (`_dispatch`): the two
entry points (`resolve_after_mutation`, `resolve_entities_bulk`) every write
path and `revert` call, the `ResolveHandlers` contract a domain registers per
model at `AppConfig.ready()`, and the registration function. The generic
projection engine (scalar / FK / relationship resolution) is slated to hoist
here from `catalog/resolve/` as sibling modules — see
`docs/plans/model_driven_metadata/ModelDrivenClaimResolution.md`. Consumers
import the public surface from this package, not the submodules.
"""

from __future__ import annotations

from ._dispatch import (
    BulkResolver,
    PerEntityResolver,
    ResolveHandlers,
    register_resolve_handlers,
    resolve_after_mutation,
    resolve_entities_bulk,
)

__all__ = [
    "BulkResolver",
    "PerEntityResolver",
    "ResolveHandlers",
    "register_resolve_handlers",
    "resolve_after_mutation",
    "resolve_entities_bulk",
]
