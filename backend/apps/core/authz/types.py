"""Activity-authorization types: Activity enum and the Decision algebra."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class Activity(StrEnum):
    """Named editorial activities the policy gates.

    Values are pinned explicitly because they are wire- and log-load-
    bearing; StrEnum's auto-derived values would normalize to
    `"catalog_edit"`, not the dotted form callers and audit logs use.
    """

    CATALOG_EDIT = "catalog.edit"
    CATALOG_CREATE = "catalog.create"
    CATALOG_DELETE = "catalog.delete"
    CLAIM_REVERT = "claim.revert"
    CHANGESET_UNDO = "changeset.undo"
    CITATION_EDIT = "citation.edit"
    MEDIA_EDIT = "media.edit"
    KIOSK_EDIT = "kiosk.edit"
    # User-state predicate, not a route-gated CRUD activity. Answers
    # "is this user exempt from per-user rate limits."
    RATE_LIMIT_EXEMPT = "rate_limit.exempt"
    # Tooling-surface activity, not a route-gated CRUD activity. Answers
    # "may this user reach the Django admin." Django itself gates `/djadmin/`
    # on `is_staff`; this activity exists so the SPA can decide whether to
    # render the nav link without the schema exposing the underlying flag.
    DJANGO_ADMIN_ACCESS = "django_admin.access"
    # Operator-surface activity gating the on-demand exception-trigger
    # route used to verify the Sentry pipeline end-to-end. Staff-only.
    OBSERVABILITY_DEBUG = "observability.debug"
    # Operator-surface activity gating the admin SPA area (`/admin/*`) and
    # its supporting page-API endpoints. Verb-led `VIEW_` makes the
    # read-only scope explicit; any future mutating admin action gets
    # its own activity rather than riding on this one.
    VIEW_ADMIN_AREA = "admin_area.view"


class DenialCode(StrEnum):
    """Stable wire identifiers for denial reasons.

    The SPA renders user-facing copy keyed off these. Adding or removing
    a member is a breaking API change.
    """

    AUTH_REQUIRED = "auth_required"
    # `is_active=False` covers any currently-inactive state (self-
    # deactivated, dormant cleanup, etc.). Real banning is a separate
    # predicate with its own code (added when banning ships), so the
    # SPA can render different copy.
    ACCOUNT_DEACTIVATED = "account_deactivated"
    ROLE_REQUIRED = "role_required"
    OWNER_REQUIRED = "owner_required"
    VERIFICATION_REQUIRED = "verification_required"
    EXPERIENCE_REQUIRED = "experience_required"
    RATE_LIMITED = "rate_limited"


# Index = priority (lower = more fundamental). The evaluator picks the
# lowest-indexed failure when multiple predicates deny — telling a
# deactivated user to verify their email is the wrong UX. VERIFICATION
# sits below ROLE because an unverified non-moderator should hear
# "moderator only," not "verify your email." OWNER sits between ROLE
# and VERIFICATION for the same reason: an unverified non-author trying
# to undo someone else's changeset should hear "not yours," not "verify
# your email" — verifying won't grant ownership. OWNER sits below ROLE
# so a future moderator-override path (if ever added) can still surface
# "moderator only" copy when relevant. EXPERIENCE sits below VERIFICATION
# because verification is more actionable (one-click confirm vs. accumulate
# N edits) — an unverified user with too few edits should hear "verify
# your email" first.
DENIAL_PRIORITY: tuple[DenialCode, ...] = (
    DenialCode.AUTH_REQUIRED,
    DenialCode.ACCOUNT_DEACTIVATED,
    DenialCode.ROLE_REQUIRED,
    DenialCode.OWNER_REQUIRED,
    DenialCode.VERIFICATION_REQUIRED,
    DenialCode.EXPERIENCE_REQUIRED,
    DenialCode.RATE_LIMITED,
)


@dataclass(frozen=True)
class Allow:
    """Decision: the activity is permitted."""


@dataclass(frozen=True)
class Deny:
    """Decision: the activity is denied, with a structured reason."""

    code: DenialCode
    context: Mapping[str, Any] = field(default_factory=dict)


Decision = Allow | Deny


class PolicyUser(Protocol):
    """Attribute surface the engine may read during a check.

    `is_authenticated` / `is_active` / `email_verified` run for every
    launch activity. `is_staff` / `is_superuser` only run when a rule
    includes the matching role predicate. Covers both authenticated
    `User` and `AnonymousUser` — the latter already has
    `is_authenticated=False` and `is_active=False`.

    Attributes are declared as `@property` (not variable annotations) so
    mypy treats them as read-only. Variable annotations would reject
    Django's `User.is_authenticated` and `AnonymousUser.is_authenticated`
    because both are read-only on those classes.
    """

    @property
    def id(self) -> int | None: ...

    @property
    def actor_id(self) -> int | None: ...

    @property
    def is_authenticated(self) -> bool: ...

    @property
    def is_active(self) -> bool: ...

    @property
    def email_verified(self) -> bool: ...

    @property
    def is_staff(self) -> bool: ...

    @property
    def is_superuser(self) -> bool: ...


@dataclass(frozen=True)
class PolicyContext:
    """Caller-assembled ambient state (rate-limit signals, etc.)."""
