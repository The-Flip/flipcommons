"""Per-user rolling-window rate limiting.

Used to enforce caps on record creates, edits, and deletes. Backed by the
Django cache (any cache backend works; a persistent backend is preferable in
production so limits survive process restarts).

Semantics:

* Rolling window — not calendar-aligned. Sliding timestamps are pruned on
  each check.
* Per user. Anonymous users never hit this code path (endpoints are auth-gated
  upstream).
* Some users bypass all limits. Who qualifies is decided by the
  ``rate_limit.exempt`` activity in :mod:`apps.core.authz`, not by
  this module — today that resolves to verified staff, but the
  predicate is no longer this file's concern. Look in
  ``core/authz/rules.py`` to change who is exempt.
* Both successful and validation-rejected attempts consume a slot. The
  consuming call is :func:`check_and_record`; mutating routes invoke it
  declaratively via :func:`rate_limited` (once per request, before the
  route body runs), or — for inline cases — at the top of the body.
* 429 refusals do NOT consume a slot. If a rejection bumped the horizon
  forward on every retry, the window would never drain.

Inventory contract (see ``apps/core/tests/test_route_inventory.py``):
the rate-limit bucket a route consumes is dictated 1:1 by the route's
``@requires`` (or ``@gated_inline``) activity — ``CATALOG_CREATE`` →
``CREATE_RATE_LIMIT_SPEC``, ``CATALOG_EDIT`` → ``EDIT_RATE_LIMIT_SPEC``,
``CATALOG_DELETE`` → ``DELETE_RATE_LIMIT_SPEC``. There is no override
table; the inventory test fails if a route's stamped spec disagrees
with its activity. To exempt a mutating route gated by one of these
activities, stamp ``@rate_limit_exempt(reason)`` instead.
"""

from __future__ import annotations

import functools
import math
import time
import types
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar, cast

from django.contrib.auth.models import AbstractBaseUser, AnonymousUser
from django.core.cache import cache

from apps.core.authz import Activity, Allow, check, policy_user
from apps.core.exceptions import StructuredApiError
from apps.core.types import JsonBody

from .constants import (
    CREATE_RATE_LIMIT,
    CREATE_WINDOW_SECONDS,
    DELETE_RATE_LIMIT,
    DELETE_WINDOW_SECONDS,
    EDIT_RATE_LIMIT,
    EDIT_WINDOW_SECONDS,
)

_CACHE_TTL_FUDGE_SECONDS = 60


class RateLimitExceededError(StructuredApiError):
    """Raised when a user has exceeded a rate-limit bucket."""

    kind = "rate_limit"
    status = 429

    def __init__(self, *, bucket: str, retry_after: int) -> None:
        super().__init__("Rate limit exceeded.")
        self.bucket = bucket
        self.retry_after = max(1, retry_after)

    def __str__(self) -> str:
        # Server-side repr (logs / tracebacks) keeps the bucket; the wire
        # ``message`` is the user-facing string set via ``super().__init__``.
        return f"Rate limit exceeded for bucket {self.bucket!r}"

    def to_body(self) -> JsonBody:
        return {"bucket": self.bucket, "retry_after": self.retry_after}

    def extra_headers(self) -> dict[str, str]:
        return {"Retry-After": str(self.retry_after)}


@dataclass(frozen=True)
class RateLimitSpec:
    bucket: str
    limit: int
    window_seconds: int


# Shared bucket for user-driven record creation (Title, Model, …). All record
# types share one bucket so that a burst of creates is capped in aggregate,
# not per-record-type. Restore uses this same bucket (it is semantically a
# create — a fresh ``status=active`` claim that brings a record back).
CREATE_RATE_LIMIT_SPEC = RateLimitSpec(
    bucket="create",
    limit=CREATE_RATE_LIMIT,
    window_seconds=CREATE_WINDOW_SECONDS,
)

# Shared bucket for user-driven record edits. All record types share one
# bucket so that a burst of edits across types is capped in aggregate. Every
# PATCH-claim route consumes one slot per request (including requests that
# fail validation — see ``check_and_record``).
EDIT_RATE_LIMIT_SPEC = RateLimitSpec(
    bucket="edit",
    limit=EDIT_RATE_LIMIT,
    window_seconds=EDIT_WINDOW_SECONDS,
)

# Shared bucket for user-driven record deletion. A cascading delete counts as
# one ChangeSet and consumes one slot here — not one per hidden child.
# Inverting one's own ChangeSet (Undo) is exempt and does not consume a slot.
DELETE_RATE_LIMIT_SPEC = RateLimitSpec(
    bucket="delete",
    limit=DELETE_RATE_LIMIT,
    window_seconds=DELETE_WINDOW_SECONDS,
)


def _cache_key(user_id: int, bucket: str) -> str:
    return f"ratelimit:{bucket}:user:{user_id}"


def check_and_record(
    user: AbstractBaseUser | AnonymousUser | None, spec: RateLimitSpec
) -> None:
    """Consume one slot in the user's bucket, or raise if the bucket is full.

    Exempt users (per the ``rate_limit.exempt`` policy activity) bypass
    the check entirely and nothing is recorded for them.
    """
    if user is None or not user.is_authenticated:
        raise RateLimitExceededError(bucket=spec.bucket, retry_after=1)
    if isinstance(check(policy_user(user), Activity.RATE_LIMIT_EXEMPT), Allow):
        return

    now = time.time()
    cutoff = now - spec.window_seconds
    key = _cache_key(user.pk, spec.bucket)

    timestamps = cache.get(key, []) or []
    pruned = [ts for ts in timestamps if ts > cutoff]

    if len(pruned) >= spec.limit:
        oldest = min(pruned)
        retry_after = math.ceil(oldest + spec.window_seconds - now)
        cache.set(key, pruned, timeout=spec.window_seconds + _CACHE_TTL_FUDGE_SECONDS)
        raise RateLimitExceededError(bucket=spec.bucket, retry_after=retry_after)

    pruned.append(now)
    cache.set(key, pruned, timeout=spec.window_seconds + _CACHE_TTL_FUDGE_SECONDS)


def reset_for_user(user: AbstractBaseUser, bucket: str) -> None:
    """Test helper: clear a user's bucket."""
    cache.delete(_cache_key(user.pk, bucket))


# ── Decorators ───────────────────────────────────────────────────────
#
# Mirror ``apps.core.authz.markers``: a wrapping decorator that both
# enforces at request time and stamps a marker the inventory walker can
# read off the wrapped callable. The ``FunctionType`` rebuild trick is
# the same one ``@requires`` uses — Ninja resolves forward-ref
# annotations through ``view.__globals__``, and a plain wrapper would
# carry *this* module's globals, breaking annotation resolution for
# closure-built views (e.g. the ``entity_crud`` factory).

F = TypeVar("F", bound=Callable[..., object])

RATE_LIMITED_ATTR = "_rate_limit_spec"
RATE_LIMIT_EXEMPT_ATTR = "_rate_limit_exempt"


def rate_limited(spec: RateLimitSpec) -> Callable[[F], F]:
    """Wrap the view to consume one slot in `spec` and stamp the marker.

    Must be inside ``@router.<verb>`` (Ninja registers the wrapped
    callable). Either order relative to ``@requires`` works at runtime
    — markers propagate through ``update_wrapper``'s ``__dict__`` copy
    in both directions; pick one order per file for readability.
    """

    def decorator(func: F) -> F:
        # Promote ``check_and_record`` from a global into a closure cell.
        # Load-bearing: the wrapper below is rebuilt with ``func.__globals__``
        # (the view's module), which doesn't import ``check_and_record`` —
        # a bare global reference would NameError at request time. Mirrors
        # ``_enforce = enforce`` in ``apps.core.authz.markers.requires``.
        _check_and_record = check_and_record

        def template(request, *args, **kwargs):  # type: ignore[no-untyped-def]
            _check_and_record(request.user, spec)
            return func(request, *args, **kwargs)

        # See ``apps.core.authz.markers.requires`` for the rationale —
        # rebuild the wrapper with the wrapped function's globals so
        # Ninja's forward-ref annotation resolution still works for
        # closure-built views.
        wrapper = types.FunctionType(
            template.__code__,
            func.__globals__,
            name=template.__name__,
            argdefs=template.__defaults__,
            closure=template.__closure__,
        )
        functools.update_wrapper(wrapper, func)
        setattr(wrapper, RATE_LIMITED_ATTR, spec)
        return cast(F, wrapper)

    return decorator


def rate_limit_exempt(reason: str) -> Callable[[F], F]:
    """Declare a mutating route as deliberately not rate-limited.

    `reason` is required and must be non-empty after `.strip()` — an
    empty or whitespace-only rationale fails at decoration time so a
    missing reason can't slip into the inventory output. Mirrors
    ``@public_mutation``.
    """
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError(
            "@rate_limit_exempt requires a non-empty reason string. "
            "The reason is captured in the inventory output so a future "
            "reviewer can audit 'do we still want this exempt?'."
        )

    def decorator(func: F) -> F:
        setattr(func, RATE_LIMIT_EXEMPT_ATTR, reason)
        return func

    return decorator


# ── Typed marker read accessors ──────────────────────────────────────


def get_rate_limit_spec(view: object) -> RateLimitSpec | None:
    """Return the ``RateLimitSpec`` stamped by ``@rate_limited``, or ``None``."""
    value = getattr(view, RATE_LIMITED_ATTR, None)
    return value if isinstance(value, RateLimitSpec) else None


def get_rate_limit_exempt_reason(view: object) -> str | None:
    """Return the rationale stamped by ``@rate_limit_exempt``, or ``None``."""
    value = getattr(view, RATE_LIMIT_EXEMPT_ATTR, None)
    return value if isinstance(value, str) else None
