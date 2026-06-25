"""Signup (onboarding) endpoints: pending, check, submit, cancel."""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.auth import login
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import HttpRequest
from ninja import Router

from apps.accounts.auth_errors import (
    PendingInvalidError,
    UsernameRejectedError,
    UsernameTakenError,
)
from apps.accounts.models import User
from apps.accounts.pending import (
    PendingPayload,
    clear_pending,
    get_pending,
)
from apps.accounts.reserved import is_reserved
from apps.accounts.schemas import (
    PendingInvalidErrorSchema,
    SignupCancelResponseSchema,
    SignupCheckResponseSchema,
    SignupPendingResponseSchema,
    SignupSubmitRequestSchema,
    SignupSubmitResponseSchema,
    UsernameRejectedErrorSchema,
    UsernameTakenErrorSchema,
)
from apps.accounts.usernames import UsernameFormatRejectReason, validate_username_format
from apps.accounts.workos_client import get_workos_client
from apps.core.authz.markers import public_mutation
from apps.core.rate_limits import (
    RateLimitSpec,
    check_and_record_ip,
    check_and_record_session,
)
from apps.core.schemas import RateLimitErrorSchema

log = logging.getLogger(__name__)

signup_router = Router(tags=["auth", "private"])


# Rate-limit specs are built per-request from settings, NOT cached at
# module-load. That preserves the design intent ("tunable without code
# change") — overriding `settings.SIGNUP_*_RATELIMIT_*` at runtime
# (env, pytest's `settings` fixture, future constance) takes effect on
# the next request without a process restart. Spec construction is a
# frozen-dataclass with three fields; the cost is negligible.
def _spec(bucket: str, setting_key: str) -> RateLimitSpec:
    limit, window = getattr(settings, setting_key)
    return RateLimitSpec(bucket, limit, window)


def _require_pending(request: HttpRequest) -> PendingPayload:
    """Return the pending payload, or raise `PendingInvalidError` (401).

    **New pre-auth endpoints MUST call this before any rate-limit call or
    other code that writes the session.** The ordering is load-bearing
    (see below).

    Deliberately does NOT call `ensure_session_key`. A valid pending payload
    implies the callback already wrote a session row (that's where
    `put_pending` calls `ensure_session_key`), so on the success path the
    session_key is non-None. On the failure path, raising before any
    session write means anonymous probes to /pending, /check, /submit do
    NOT create a `django_session` row — closing the session-flood vector
    a pre-auth `ensure_session_key()` would have opened.

    The downstream rate-limiter assert (`session_key is not None`) still
    holds because rate-limiting only runs after this guard succeeds.
    """
    payload = get_pending(request)
    if payload is None:
        raise PendingInvalidError()
    return payload


def _format_reject_reason(username: str) -> UsernameFormatRejectReason | None:
    """Return the format reject reason, or None when valid.

    The validator carries a `code` matching `UsernameFormatRejectReason`
    on every raise. Missing code = bug in the validator, not a wire-format
    degradation, so fail loud rather than masking with a fake "bad_charset".

    Callers that want to surface the reason as an error (the submit
    endpoint) raise `UsernameRejectedError(reason=...)` on a non-None return.
    The availability check uses the reason directly in its 200 body.
    """
    try:
        validate_username_format(username)
    except ValidationError as exc:
        # PT017 is a pytest-only lint rule about test structure;
        # the assert is correct here in app code.
        assert exc.code is not None, (  # noqa: PT017
            "validate_username_format raised without code"
        )
        reason: UsernameFormatRejectReason = exc.code  # type: ignore[assignment]
        return reason
    return None


@signup_router.get(
    "/pending/",
    response={200: SignupPendingResponseSchema, 401: PendingInvalidErrorSchema},
)
def signup_pending(request: HttpRequest) -> SignupPendingResponseSchema:
    """Return identity fields for the onboarding-page header.

    Source is the pending session payload; missing/expired raises
    `PendingInvalidError` (401).
    """
    pending = _require_pending(request)
    return SignupPendingResponseSchema(
        first_name=pending["first_name"],
        last_name=pending["last_name"],
        email=pending["email"],
    )


@signup_router.get(
    "/check/",
    response={
        200: SignupCheckResponseSchema,
        401: PendingInvalidErrorSchema,
        429: RateLimitErrorSchema,
    },
)
def signup_check(request: HttpRequest, username: str) -> SignupCheckResponseSchema:
    """Availability check for a candidate username.

    Always 200 (when session is valid). Every outcome — format-invalid,
    reserved, taken, available — is a normal answer to "can the user
    use this handle?" The typed `reason` carries the discriminator;
    callers don't have to branch on status code.

    The pending guard runs before rate limiting, short-circuiting requests
    without a legitimate session shape so they don't consume rate-limit slots;
    for real users whose session just expired, the typed `pending_invalid` is
    more informative than a 429.
    """
    _require_pending(request)
    check_and_record_session(
        request, _spec("signup_check_session", "SIGNUP_CHECK_RATELIMIT_SESSION")
    )
    check_and_record_ip(request, _spec("signup_check_ip", "SIGNUP_CHECK_RATELIMIT_IP"))

    reason = _format_reject_reason(username)
    if reason is not None:
        return SignupCheckResponseSchema(available=False, reason=reason)
    if is_reserved(username):
        return SignupCheckResponseSchema(available=False, reason="reserved")
    if User.objects.filter(username=username).exists():
        return SignupCheckResponseSchema(available=False, reason="taken")
    return SignupCheckResponseSchema(available=True, reason=None)


@signup_router.post(
    "/",
    response={
        200: SignupSubmitResponseSchema,
        400: UsernameRejectedErrorSchema,
        401: PendingInvalidErrorSchema,
        409: UsernameTakenErrorSchema,
        429: RateLimitErrorSchema,
    },
)
@public_mutation(
    "Pre-auth signup; gated by pending session payload, not @requires() "
    "because no User exists yet."
)
def signup_submit(
    request: HttpRequest, payload: SignupSubmitRequestSchema
) -> SignupSubmitResponseSchema:
    """Create the User row from pending payload + chosen username, then log in.

    Two races handled inline (callback no longer issues a User INSERT):
    - `workos_user_id` race (two tabs of the same signup): re-query the
      winner by `workos_user_id` and log the loser's session in as the
      winner. The loser's typed handle is silently dropped — acceptable
      per Usernames.md §Race. Logging in on the loser side (rather than
      returning 409 and trusting the winner's cookie) is deterministic:
      Django's `login()` rotates `session_key` via `cycle_key()`, so the
      losing tab's in-flight submit may not pick up the rotated cookie
      depending on response ordering.
    - `username` race (two users picking the same handle simultaneously):
      raises `UsernameTakenError` (409); pending payload stays intact so
      the user can pick again.
    """
    pending = _require_pending(request)
    check_and_record_session(
        request, _spec("signup_submit_session", "SIGNUP_SUBMIT_RATELIMIT_SESSION")
    )
    check_and_record_ip(
        request, _spec("signup_submit_ip", "SIGNUP_SUBMIT_RATELIMIT_IP")
    )

    username = payload.username
    if (reason := _format_reject_reason(username)) is not None:
        raise UsernameRejectedError(reason=reason) from None
    if is_reserved(username):
        raise UsernameRejectedError(reason="reserved")

    try:
        with transaction.atomic():
            user = User.objects.create_user(
                email=pending["email"],
                username=username,
                first_name=pending["first_name"],
                last_name=pending["last_name"],
                workos_user_id=pending["workos_user_id"],
                email_verified=pending["email_verified"],
            )
    except IntegrityError:
        # Disambiguate by re-query, not by inspecting the exception:
        # psycopg's diag.constraint_name attribute isn't portable across
        # backends and SQLite tests would need a parallel code path.
        winner = User.objects.filter(workos_user_id=pending["workos_user_id"]).first()
        if winner is not None:
            # Sibling tab won the workos_user_id race. The winner was just
            # created from the same pending payload (same WorkOS callback,
            # same session), so first_name / last_name / email_verified
            # already match — do NOT call _refresh_mirrored_fields here.
            clear_pending(request)
            login(request, winner, backend="apps.accounts.backends.WorkOSBackend")
            return SignupSubmitResponseSchema(redirect_url=pending["next_url"])
        # Username collision against a different account.
        # `from None`: the IntegrityError is implementation detail; chaining
        # it onto the wire-shaped exception would leak the constraint
        # message into logs without informing the response. Same rationale
        # at the earlier UsernameRejectedError raise.
        raise UsernameTakenError() from None

    clear_pending(request)
    login(request, user, backend="apps.accounts.backends.WorkOSBackend")
    return SignupSubmitResponseSchema(redirect_url=pending["next_url"])


def _absolute_return_to(request: HttpRequest, path: str) -> str:
    """Resolve a relative return URL to absolute, since WorkOS requires that.

    The setting accepts either form so dev/test can use a bare path.
    """
    if path.startswith(("http://", "https://")):
        return path
    return request.build_absolute_uri(path)


@signup_router.post(
    "/cancel/",
    response={200: SignupCancelResponseSchema, 429: RateLimitErrorSchema},
)
@public_mutation(
    "Pre-auth signup cancel — clears pending state and returns the WorkOS "
    "logout URL. Idempotent; no editorial action is being authorized."
)
def signup_cancel(request: HttpRequest) -> SignupCancelResponseSchema:
    """Clear pending state and return a WorkOS logout URL.

    Idempotent — missing pending still returns a valid logout URL because
    the user's intent is "get me out." Rate-limited by IP only; a
    session-key limit would force a carve-out around ensure_session_key
    and only catch the absurd "user click-spams Not-you?" case.
    """
    check_and_record_ip(
        request, _spec("signup_cancel_ip", "SIGNUP_CANCEL_RATELIMIT_IP")
    )
    payload = get_pending(request)
    clear_pending(request)

    return_to = settings.SIGNUP_CANCEL_RETURN_URL
    if (
        payload is not None
        and payload["workos_session_id"]
        and settings.WORKOS_API_KEY
        and settings.WORKOS_CLIENT_ID
    ):
        try:
            client = get_workos_client()
            logout_url = client.user_management.get_logout_url(
                session_id=payload["workos_session_id"],
                return_to=_absolute_return_to(request, return_to),
            )
            return SignupCancelResponseSchema(logout_url=logout_url)
        except Exception:
            log.exception("Failed to build WorkOS logout URL; falling back")
    return SignupCancelResponseSchema(logout_url=return_to)
