"""Edge diagnostics API.

``GET /api/edge/echo/`` — what the proxy chain delivered to Django for
this request: the client IP Caddy promoted into ``X-Real-IP``, the raw
``X-Client-IP`` Bunny injected, Railway's ``X-Forwarded-For``, and whether
``X-Origin-Auth`` was present (never its value). Gated by
``Activity.OBSERVABILITY_DEBUG``.

The chain is described in docs/Hosting.md § Client IP trust. Its failure
mode is silent: if a hop stops carrying the visitor's address, every
visitor lands in one rate-limit bucket and nothing else changes. This
endpoint is the only place that failure is observable, so it is what gets
probed after any change to the chain — enabling Origin Shield, moving
hosts, adding a CDN hop.
"""

from __future__ import annotations

from django.http import HttpRequest, HttpResponse
from ninja import Router, Schema
from ninja.security import django_auth

from apps.core.authz.markers import requires
from apps.core.authz.types import Activity

edge_router = Router(auth=django_auth)


class EdgeEchoSchema(Schema):
    """Request headers as Django received them, after Caddy's rewriting."""

    # What the rate limiter keys on. Caddy promotes X-Client-IP into this
    # only when X-Origin-Auth matches ORIGIN_SHARED_SECRET.
    x_real_ip: str | None
    # Bunny's %{User.IP}, forwarded verbatim by Railway.
    x_client_ip: str | None
    # Caddy overwrites this with X-Real-IP inside reverse_proxy, so it
    # should always equal x_real_ip; a difference means that rewrite broke.
    x_forwarded_for: str | None
    # Presence only; the value is the shared secret and is never serialized.
    x_origin_auth_present: bool
    # Always Caddy's loopback address in production; anything else means
    # Django is reachable without Caddy in front.
    remote_addr: str
    host: str


@edge_router.get("echo/", response=EdgeEchoSchema)
@requires(Activity.OBSERVABILITY_DEBUG)
def edge_echo(request: HttpRequest, response: HttpResponse) -> EdgeEchoSchema:
    response["Cache-Control"] = "private, no-store"
    meta = request.META
    return EdgeEchoSchema(
        x_real_ip=meta.get("HTTP_X_REAL_IP"),
        x_client_ip=meta.get("HTTP_X_CLIENT_IP"),
        x_forwarded_for=meta.get("HTTP_X_FORWARDED_FOR"),
        x_origin_auth_present="HTTP_X_ORIGIN_AUTH" in meta,
        remote_addr=str(meta.get("REMOTE_ADDR", "")),
        host=request.get_host(),
    )
