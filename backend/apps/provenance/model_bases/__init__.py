"""The abstract claim-control base layer — see :mod:`.models`.

Re-exports the bases and the relationship declaration vocabulary so callers
import ``from apps.provenance.model_bases import …`` (and the legacy
``from apps.provenance.models import …`` re-export keeps working) without
reaching into the submodules.
"""

from .claim_relationships import (
    ClaimRelationshipBinding,
    ClaimRelationshipSpec,
    EmptyTargetPolicy,
    MemberField,
    MemberXor,
    PayloadField,
    ScopePolicy,
    SingleSubject,
    SubjectSpec,
    XorSubject,
    all_relationship_bindings,
    relationships_for,
)
from .models import (
    ClaimControlledModel,
    ClaimThroughModel,
    LinkableClaimModel,
    LinkableLifecycleClaimModel,
)

__all__ = [
    "ClaimControlledModel",
    "ClaimRelationshipBinding",
    "ClaimRelationshipSpec",
    "ClaimThroughModel",
    "EmptyTargetPolicy",
    "LinkableClaimModel",
    "LinkableLifecycleClaimModel",
    "MemberField",
    "MemberXor",
    "PayloadField",
    "ScopePolicy",
    "SingleSubject",
    "SubjectSpec",
    "XorSubject",
    "all_relationship_bindings",
    "relationships_for",
]
