"""Pre-signup pending-session helpers.

After a successful WorkOS callback for a brand-new user we don't have a
local `User` row yet — the user still has to pick a handle. The WorkOS-side
identity (workos_user_id, email, name) is stashed in the Django session
under `PENDING_SESSION_KEY` and the user is redirected to `/signup`. The
onboarding endpoints (`/pending`, `/check`, `/submit`, `/cancel`) read or
clear this payload.

Server-side sessions are already in use for the OAuth `state` round-trip,
so this doesn't put PII in a browser cookie.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Protocol, TypedDict

from django.http import HttpRequest

from apps.accounts.types import WorkOsUserId


class WorkOSUser(Protocol):
    """The subset of the WorkOS SDK's user object we depend on.

    Defined here (a leaf module) rather than `api.py` so `pending.py` stays
    importable from `api.py` without circularity. The SDK's concrete type
    duck-conforms — no adapter needed.
    """

    id: WorkOsUserId
    email: str
    email_verified: bool
    first_name: str | None
    last_name: str | None


log = logging.getLogger(__name__)

PENDING_SESSION_KEY = "auth_pending_signup"
PENDING_TTL = timedelta(minutes=30)


class PendingPayload(TypedDict):
    workos_user_id: WorkOsUserId
    email: str
    email_verified: bool
    first_name: str
    last_name: str
    next_url: str
    created_at: str  # ISO 8601 — Django's JSONSerializer can't serialize datetime.
    # WorkOS session id (`sid` claim from the access_token JWT). Used to
    # build the IdP-side logout URL on cancel. May be empty string when
    # the callback couldn't extract one (test fixtures, future SDK shape
    # changes) — cancel falls back to the local return URL in that case.
    workos_session_id: str


def ensure_session_key(request: HttpRequest) -> str:
    """Return `request.session.session_key`, calling `save()` first if None.

    Anonymous requests don't get a session row until something is written.
    Pre-auth handlers that key off `session_key` (rate limiting, the
    pending stash) need a stable id, so force-persist on entry.
    """
    if request.session.session_key is None:
        request.session.save()
    key = request.session.session_key
    assert key is not None
    return key


def extract_workos_session_id(access_token: str) -> str:
    """Pull the `sid` claim from a WorkOS access-token JWT. Returns "" on failure.

    The token was just issued to us in the same callback, so we don't
    re-verify the signature — we only need a value to feed back to WorkOS
    when building the logout URL. Any malformed input falls back to "" and
    cancel degrades to a local-only redirect.
    """
    import base64
    import json

    try:
        payload_b64 = access_token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload_b64))
        sid = claims.get("sid", "")
        return sid if isinstance(sid, str) else ""
    except ValueError, IndexError, KeyError:
        return ""


def put_pending(
    request: HttpRequest,
    workos_user: WorkOSUser,
    next_url: str,
    *,
    workos_session_id: str = "",
) -> None:
    """Stash the WorkOS identity in the session for the onboarding flow.

    `next_url` is trusted here: the callback popped it from session storage
    where it was placed by the sign-in entry point ([api.py auth_login] runs
    `url_has_allowed_host_and_scheme` and falls back to `/` on rejection).
    Do not re-validate — and do not reintroduce a check here, since a stricter
    second pass would silently override the sign-in entry's contract.
    """
    ensure_session_key(request)
    payload: PendingPayload = {
        "workos_user_id": workos_user.id,
        "email": workos_user.email,
        "email_verified": workos_user.email_verified,
        "first_name": workos_user.first_name or "",
        "last_name": workos_user.last_name or "",
        "next_url": next_url,
        "created_at": datetime.now(UTC).isoformat(),
        "workos_session_id": workos_session_id,
    }
    request.session[PENDING_SESSION_KEY] = payload


def get_pending(request: HttpRequest) -> PendingPayload | None:
    """Return the payload if present and fresh, else None.

    Clears expired payloads as a side effect, and logs missing-vs-expired
    distinctly for ops visibility. The distinction has diagnostic value
    but no UX value (both lead the user to the same "sign-in expired,
    please start over" outcome), so the wire returns a single code.
    """
    raw = request.session.get(PENDING_SESSION_KEY)
    if raw is None:
        # DEBUG, not INFO: every unauthenticated hit to a signup endpoint
        # lands here, including scrapers and bots. The interesting signal
        # is `expired` (real user whose flow stalled), not `missing`.
        log.debug("pending: missing")
        return None
    payload: PendingPayload = raw
    created_at = datetime.fromisoformat(payload["created_at"])
    if datetime.now(UTC) - created_at > PENDING_TTL:
        log.info("pending: expired (created_at=%s)", payload["created_at"])
        clear_pending(request)
        return None
    return payload


def clear_pending(request: HttpRequest) -> None:
    """Remove the pending payload if any. Idempotent."""
    if PENDING_SESSION_KEY in request.session:
        del request.session[PENDING_SESSION_KEY]
