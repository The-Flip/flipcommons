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
  consuming call is :func:`check_and_record` and endpoints invoke it once at
  the top of the request.
* 429 refusals do NOT consume a slot. If a rejection bumped the horizon
  forward on every retry, the window would never drain.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

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
