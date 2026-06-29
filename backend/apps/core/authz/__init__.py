"""Authorization engine."""

from .capabilities import compute_capability_map, compute_row_capabilities
from .enforce import enforce
from .evaluator import check, policy_user
from .exceptions import PolicyDeniedError
from .types import (
    DENIAL_PRIORITY,
    Activity,
    Allow,
    Decision,
    DenialCode,
    Deny,
    PolicyActivities,
    PolicyContext,
    PolicyUser,
)

__all__ = [
    "DENIAL_PRIORITY",
    "Activity",
    "Allow",
    "Decision",
    "DenialCode",
    "Deny",
    "PolicyActivities",
    "PolicyContext",
    "PolicyDeniedError",
    "PolicyUser",
    "check",
    "compute_capability_map",
    "compute_row_capabilities",
    "enforce",
    "policy_user",
]
