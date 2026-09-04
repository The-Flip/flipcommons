"""Tests for ``GET /api/edge/echo/`` — the proxy-chain header echo.

Pins the auth matrix (anon / non-staff / unverified-staff / verified-staff)
and that the body reflects the headers Django received, with the shared
secret reduced to presence.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.accounts.models import User
from apps.accounts.test_factories import make_user

ECHO_URL = "/api/edge/echo/"


@pytest.mark.django_db
class TestAuthMatrix:
    def test_anonymous_is_denied(self, client: Client) -> None:
        # `django_auth` is configured on the Router and rejects before
        # `@requires` ever fires, so anonymous deterministically gets 401.
        resp = client.get(ECHO_URL)
        assert resp.status_code == 401

    def test_non_staff_is_denied(self, client: Client, user: User) -> None:
        client.force_login(user)
        resp = client.get(ECHO_URL)
        assert resp.status_code == 403

    def test_unverified_staff_is_denied(self, client: Client) -> None:
        unverified_staff = make_user(is_staff=True, email_verified=False)
        client.force_login(unverified_staff)
        resp = client.get(ECHO_URL)
        assert resp.status_code == 403

    def test_verified_staff_gets_200(self, client: Client, staff: User) -> None:
        client.force_login(staff)
        resp = client.get(ECHO_URL)
        assert resp.status_code == 200


@pytest.mark.django_db
class TestEcho:
    def test_reflects_the_headers_django_received(
        self, client: Client, staff: User
    ) -> None:
        client.force_login(staff)
        resp = client.get(
            ECHO_URL,
            HTTP_X_REAL_IP="203.0.113.7",
            HTTP_X_CLIENT_IP="203.0.113.7",
            HTTP_X_FORWARDED_FOR="203.0.113.7",
            HTTP_X_ORIGIN_AUTH="the-shared-secret",
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["x_real_ip"] == "203.0.113.7"
        assert body["x_client_ip"] == "203.0.113.7"
        assert body["x_forwarded_for"] == "203.0.113.7"
        assert body["x_origin_auth_present"] is True
        assert body["remote_addr"] == "127.0.0.1"
        assert body["host"] == "testserver"

    def test_never_echoes_the_secret_value(self, client: Client, staff: User) -> None:
        client.force_login(staff)
        resp = client.get(ECHO_URL, HTTP_X_ORIGIN_AUTH="the-shared-secret")
        assert "the-shared-secret" not in resp.content.decode()

    def test_absent_headers_are_null_and_auth_false(
        self, client: Client, staff: User
    ) -> None:
        client.force_login(staff)
        body = client.get(ECHO_URL).json()
        assert body["x_real_ip"] is None
        assert body["x_client_ip"] is None
        assert body["x_forwarded_for"] is None
        assert body["x_origin_auth_present"] is False

    def test_is_never_cacheable(self, client: Client, staff: User) -> None:
        # The body is per-request by construction; the Caddy backstop stamps
        # `private, no-store` in production, and Bunny bypasses /api/, but the
        # endpoint should not depend on either.
        client.force_login(staff)
        resp = client.get(ECHO_URL)
        assert "no-store" in resp.get("Cache-Control", "")
