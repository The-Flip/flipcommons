"""Auth endpoints: login redirect, OAuth callback, logout, /me."""

from __future__ import annotations

import logging
import secrets

from django.conf import settings
from django.contrib.auth import login, logout
from django.contrib.auth.models import AnonymousUser
from django.http import (
    HttpRequest,
    HttpResponse,
    HttpResponseRedirect,
)
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.csrf import ensure_csrf_cookie
from ninja import Router

from apps.accounts.models import User
from apps.accounts.pending import extract_workos_session_id, put_pending
from apps.accounts.schemas import AuthStatusSchema
from apps.accounts.workos_client import get_workos_client
from apps.core.authz import compute_capability_map, policy_user
from apps.core.authz.markers import public_mutation

from .auth_codes import AuthErrorCode, LoginRefusedError
from .workos_match import _try_match_existing

log = logging.getLogger(__name__)

auth_router = Router()


@auth_router.get("/me/", response=AuthStatusSchema)
def auth_me(request: HttpRequest) -> AuthStatusSchema:
    """Return current session's authentication state.

    Always succeeds (no auth required). Returns is_authenticated=False for
    anonymous users.
    """
    user = request.user
    if isinstance(user, User):
        return AuthStatusSchema(
            is_authenticated=True,
            id=user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name,
            capabilities=compute_capability_map(policy_user(user)),
        )
    assert isinstance(user, AnonymousUser)
    return AuthStatusSchema(
        is_authenticated=False,
        capabilities=compute_capability_map(policy_user(user)),
    )


@auth_router.get("/login/", url_name="workos_login", include_in_schema=False)
def auth_login(request: HttpRequest) -> HttpResponse:
    """Redirect to WorkOS AuthKit hosted login UI."""
    if not settings.WORKOS_API_KEY or not settings.WORKOS_CLIENT_ID:
        return HttpResponse(
            "WorkOS is not configured. Set WORKOS_API_KEY and WORKOS_CLIENT_ID.",
            status=503,
        )

    next_url = request.GET.get("next", "/")
    if not url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}
    ):
        next_url = "/"

    state = secrets.token_urlsafe(32)
    request.session[f"auth_{state}"] = next_url

    try:
        client = get_workos_client()
        authorization_url = client.user_management.get_authorization_url(
            provider="authkit",
            redirect_uri=settings.WORKOS_REDIRECT_URI,
            state=state,
        )
    except Exception:
        log.exception("Failed to generate WorkOS authorization URL")
        return HttpResponse(
            "Sign-in is temporarily unavailable. Please try again later.",
            status=503,
        )
    return HttpResponseRedirect(authorization_url)


def _refuse(reason: AuthErrorCode, detail: str) -> HttpResponseRedirect:
    """Log and redirect to the styled /auth/error page with a typed reason.

    Centralizes the log-then-redirect pattern so every refusal path emits a
    structured line (with the AuthErrorCode) rather than relying on web-server
    access logs to recover the failure mode from a query string.
    """
    log.warning("Auth callback refused: reason=%s detail=%s", reason, detail)
    return HttpResponseRedirect(f"/auth/error?reason={reason}")


@auth_router.get("/callback/", url_name="workos_callback", include_in_schema=False)
@ensure_csrf_cookie
def auth_callback(request: HttpRequest) -> HttpResponse:
    """Handle the OAuth callback from WorkOS.

    The `@ensure_csrf_cookie` decorator mints a csrftoken cookie on the
    response. Required for the no-match branch (put_pending + redirect to
    /signup): that branch does NOT call `login()`, so it skips the
    implicit `rotate_token()` call that login() performs. Without the
    decorator the browser lands at /signup with only `sessionid`, and the
    first pre-auth POST (Continue or Not you?) fails CSRF because
    client.ts can't include `X-CSRFToken` without the cookie. The
    matched-user branch still gets csrftoken via `login()` → the decorator
    is harmless on that path.
    """
    code = request.GET.get("code")
    state = request.GET.get("state")
    if not code or not state:
        return _refuse("state_invalid", "Missing code or state parameter.")

    next_url = request.session.pop(f"auth_{state}", None)
    if next_url is None:
        return _refuse("state_invalid", "Invalid or expired state parameter.")

    try:
        client = get_workos_client()
        auth_response = client.user_management.authenticate_with_code(
            code=code,
        )
    except Exception:
        log.exception("WorkOS code exchange failed (reason=code_exchange_failed)")
        return HttpResponseRedirect("/auth/error?reason=code_exchange_failed")

    try:
        user = _try_match_existing(auth_response.user)
    except LoginRefusedError as exc:
        return _refuse(exc.code, str(exc))
    if user is not None:
        login(request, user, backend="apps.accounts.backends.WorkOSBackend")
        return HttpResponseRedirect(next_url)

    # Brand-new user — stash WorkOS identity in the session and redirect
    # to onboarding so they can pick a handle. No User INSERT happens here,
    # so the retry-on-IntegrityError loop the old callback wore is gone;
    # the submit endpoint inherits the workos_user_id and username races.
    put_pending(
        request,
        auth_response.user,
        next_url,
        workos_session_id=extract_workos_session_id(auth_response.access_token),
    )
    return HttpResponseRedirect("/signup")


@auth_router.post("/logout/", response=AuthStatusSchema)
@public_mutation(
    "Session teardown — caller may already be partially logged out; "
    "no editorial action is being authorized."
)
def auth_logout(request: HttpRequest) -> AuthStatusSchema:
    """End the current session."""
    logout(request)
    # `request.user` is `AnonymousUser` after `logout()`. Populate the
    # capability map explicitly so the response shape matches `/me/`'s
    # anonymous branch — both bodies represent the same state.
    return AuthStatusSchema(
        is_authenticated=False,
        capabilities=compute_capability_map(policy_user(request.user)),
    )
