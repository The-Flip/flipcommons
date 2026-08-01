"""Attach per-request Sentry scope data: user (id+username) and tags.

Sits after ``AuthenticationMiddleware`` so ``request.user`` is resolved.
For authenticated requests the scope carries the user's id and username;
for anonymous requests no user is attached. Tags (``auth_state``,
``ua_family``) are set on every request so the issue stream is
filterable for both anonymous and authenticated traffic.

The ``{id, username}`` keep-list is **load-bearing** for the privacy
contract. There is no ``before_send`` scrubber to catch a mistake here
— the only other safeguards are ``send_default_pii=False`` (which
prevents ``DjangoIntegration`` from auto-attaching the email) and
Sentry's server-side scrubbing rules. Adding ``user.email`` or
``user.ip_address`` to the ``set_user`` call below ships them. The
test ``test_authenticated_user_has_no_email_or_ip_in_scope`` is the
regression guard; do not weaken it.

Relies on ``DjangoIntegration``'s per-request scope isolation: each
incoming request gets a fresh scope, so the user/tags set here don't
leak into the next request.
"""

from __future__ import annotations

from collections.abc import Callable

import sentry_sdk
from django.http import HttpRequest, HttpResponseBase

from apps.accounts.models import User


def _ua_family(user_agent: str) -> str:
    """Coarse User-Agent family for filtering issues.

    Substring sniff rather than a parser library — the goal is a
    handful of filterable values, not accurate version detection.
    The ``"bot"`` bucket is broad on purpose: it catches both
    self-identified crawlers (``"bot"``, ``"crawl"``, ``"spider"``,
    ``"slurp"``) and non-browser HTTP clients (``"http"``,
    ``"fetch"``, ``"curl"``, ``"wget"``) — node-fetch, python-
    requests, monitoring probes all bucket here. Real browsers
    don't carry those substrings.

    Order matters: bot signatures are checked first because many
    crawlers self-identify in a UA string that also contains a
    real browser name (e.g. Googlebot's Chrome UA).
    """
    ua = user_agent.lower()
    if not ua:
        return "unknown"
    bot_markers = ("bot", "crawl", "spider", "slurp", "fetch", "http", "curl", "wget")
    if any(m in ua for m in bot_markers):
        return "bot"
    if "edg/" in ua:
        return "edge"
    if "chrome/" in ua:
        return "chrome"
    if "firefox/" in ua:
        return "firefox"
    if "safari/" in ua:
        return "safari"
    return "other"


class SentryScopeMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponseBase]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponseBase:
        # Gate on an active SDK client: with SENTRY_DSN unset (local
        # dev, CI, tests) scope mutations still write to the in-process
        # isolation scope even though no events flow. A later
        # in-process Sentry init — e.g. a recording transport in a
        # test — would inherit that stale state. Skipping when the SDK
        # isn't listening keeps the scope clean.
        if sentry_sdk.get_client().is_active():
            if request.user.is_authenticated:
                assert isinstance(request.user, User)
                sentry_sdk.set_user(
                    {"id": request.user.id, "username": request.user.username}
                )
                sentry_sdk.set_tag("auth_state", "auth")
            else:
                sentry_sdk.set_tag("auth_state", "anon")
            sentry_sdk.set_tag(
                "ua_family", _ua_family(request.META.get("HTTP_USER_AGENT", ""))
            )
        return self.get_response(request)
