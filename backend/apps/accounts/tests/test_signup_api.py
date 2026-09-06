"""Tests for the signup (onboarding) endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

import pytest
from django.core.cache import cache
from django.test import Client

from apps.accounts.models import User
from apps.accounts.pending import PENDING_SESSION_KEY, PENDING_TTL
from apps.accounts.test_factories import make_user


def _stash_pending(
    client: Client,
    *,
    workos_user_id: str = "user_01",
    email: str = "alice@example.com",
    first_name: str = "Alice",
    last_name: str = "Smith",
    email_verified: bool = True,
    next_url: str = "/dashboard",
    workos_session_id: str = "",
    created_at: datetime | None = None,
) -> None:
    """Plant a pending payload directly into the test client's session."""
    session = client.session
    session[PENDING_SESSION_KEY] = {
        "workos_user_id": workos_user_id,
        "email": email,
        "email_verified": email_verified,
        "first_name": first_name,
        "last_name": last_name,
        "next_url": next_url,
        "created_at": (created_at or datetime.now(UTC)).isoformat(),
        "workos_session_id": workos_session_id,
    }
    session.save()


@pytest.fixture(autouse=True)
def _clear_cache():
    """Rate-limit buckets live in cache — wipe between tests so a hot bucket
    from one test doesn't leak into the next."""
    cache.clear()


# ── /pending/ ────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestSignupPending:
    def test_returns_identity_fields_from_pending(self, client):
        _stash_pending(client)
        resp = client.get("/api/auth/signup/pending/")
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == "alice@example.com"
        assert body["first_name"] == "Alice"
        assert body["last_name"] == "Smith"

    def test_returns_401_when_pending_missing(self, client):
        resp = client.get("/api/auth/signup/pending/")
        assert resp.status_code == 401
        assert resp.json()["detail"]["kind"] == "pending_invalid"

    def test_returns_401_when_pending_expired(self, client):
        stale = datetime.now(UTC) - PENDING_TTL - timedelta(seconds=1)
        _stash_pending(client, created_at=stale)
        resp = client.get("/api/auth/signup/pending/")
        assert resp.status_code == 401
        assert resp.json()["detail"]["kind"] == "pending_invalid"


# ── /check/ ──────────────────────────────────────────────────────────


@pytest.mark.django_db
class TestSignupCheck:
    def _check(self, client, username):
        return client.get(f"/api/auth/signup/check/?username={username}")

    def test_available_when_valid_and_unused(self, client):
        _stash_pending(client)
        resp = self._check(client, "freshhandle")
        assert resp.status_code == 200
        assert resp.json() == {"available": True, "reason": None}

    def test_too_short(self, client):
        _stash_pending(client)
        resp = self._check(client, "ab")
        assert resp.status_code == 200
        assert resp.json() == {"available": False, "reason": "too_short"}

    def test_too_long(self, client):
        _stash_pending(client)
        resp = self._check(client, "a" * 21)
        assert resp.status_code == 200
        assert resp.json() == {"available": False, "reason": "too_long"}

    def test_bad_charset(self, client):
        _stash_pending(client)
        resp = self._check(client, "Bad_Name")
        assert resp.status_code == 200
        assert resp.json() == {"available": False, "reason": "bad_charset"}

    def test_leading_trailing_hyphen(self, client):
        _stash_pending(client)
        resp = self._check(client, "-bad")
        assert resp.status_code == 200
        assert resp.json() == {
            "available": False,
            "reason": "leading_or_trailing_hyphen",
        }

    def test_consecutive_hyphens(self, client):
        _stash_pending(client)
        resp = self._check(client, "a--b")
        assert resp.status_code == 200
        assert resp.json() == {"available": False, "reason": "consecutive_hyphens"}

    def test_reserved(self, client):
        _stash_pending(client)
        resp = self._check(client, "admin")
        assert resp.status_code == 200
        assert resp.json() == {"available": False, "reason": "reserved"}

    def test_taken(self, client):
        _stash_pending(client)
        make_user(username="claimed")
        resp = self._check(client, "claimed")
        assert resp.status_code == 200
        assert resp.json() == {"available": False, "reason": "taken"}

    def test_no_pending_returns_401(self, client):
        resp = self._check(client, "anything")
        assert resp.status_code == 401
        assert resp.json()["detail"]["kind"] == "pending_invalid"

    def test_expired_pending_returns_401(self, client):
        stale = datetime.now(UTC) - PENDING_TTL - timedelta(seconds=1)
        _stash_pending(client, created_at=stale)
        resp = self._check(client, "anything")
        assert resp.status_code == 401
        assert resp.json()["detail"]["kind"] == "pending_invalid"

    def test_session_rate_limit(self, client, settings):
        # Tight budget so the test runs fast. Specs are built from settings
        # on each request, so overriding here propagates without any
        # module-internal monkey-patching.
        settings.SIGNUP_CHECK_RATELIMIT_SESSION = (3, 60)

        _stash_pending(client)
        for _ in range(3):
            assert self._check(client, "ok").status_code == 200
        resp = self._check(client, "ok")
        assert resp.status_code == 429


# ── POST / (submit) ──────────────────────────────────────────────────


@pytest.mark.django_db
class TestSignupSubmit:
    def _submit(self, client, username, csrf=True):
        kwargs = {}
        if csrf:
            client.cookies["csrftoken"] = "x" * 32
            kwargs["HTTP_X_CSRFTOKEN"] = "x" * 32
        return client.post(
            "/api/auth/signup/",
            data={"username": username},
            content_type="application/json",
            **kwargs,
        )

    def test_success_creates_user_and_logs_in(self, client):
        _stash_pending(client, next_url="/dashboard")
        resp = self._submit(client, "alice")
        assert resp.status_code == 200
        assert resp.json() == {"redirect_url": "/dashboard"}

        user = User.objects.get(workos_user_id="user_01")
        assert user.username == "alice"
        assert user.email == "alice@example.com"
        assert user.email_verified is True

        # Pending should be cleared.
        assert PENDING_SESSION_KEY not in client.session
        # Session is authenticated.
        assert client.session.get("_auth_user_id") == str(user.pk)

    def test_success_notifies_admins_without_the_email(
        self, client, settings, monkeypatch, django_capture_on_commit_callbacks
    ):
        settings.SITE_ORIGIN = "https://flipcommons.example"
        notify = MagicMock()
        monkeypatch.setattr("apps.accounts.api.signup.notify_admins", notify)
        _stash_pending(client, email="alice@example.com")

        with django_capture_on_commit_callbacks(execute=True):
            resp = self._submit(client, "alice")
        assert resp.status_code == 200

        notify.assert_called_once()
        code, message = notify.call_args.args
        assert code == "account.created"
        assert "alice" in message
        assert "https://flipcommons.example/users/alice" in message
        # The channel has no scrubbing; the address must never reach it.
        assert "alice@example.com" not in message
        assert "@" not in message

    def test_failing_webhook_does_not_break_signup(
        self, client, settings, monkeypatch, django_capture_on_commit_callbacks
    ):
        settings.ADMIN_NOTIFICATION_WEBHOOK_URL = "https://discord.example.test/hook"
        monkeypatch.setattr(
            "apps.core.admin_notifications.urlopen",
            MagicMock(side_effect=OSError("unreachable")),
        )
        _stash_pending(client, next_url="/dashboard")

        with django_capture_on_commit_callbacks(execute=True):
            resp = self._submit(client, "alice")

        assert resp.status_code == 200
        assert resp.json() == {"redirect_url": "/dashboard"}
        assert User.objects.filter(username="alice").exists()

    def test_username_race_returns_409_taken(self, client):
        make_user(username="claimed")
        _stash_pending(client)
        resp = self._submit(client, "claimed")
        assert resp.status_code == 409
        assert resp.json()["detail"]["kind"] == "username_taken"
        # Pending stays intact so the user can pick another.
        assert PENDING_SESSION_KEY in client.session

    def test_username_race_notifies_nothing(
        self, client, monkeypatch, django_capture_on_commit_callbacks
    ):
        notify = MagicMock()
        monkeypatch.setattr("apps.accounts.api.signup.notify_admins", notify)
        make_user(username="claimed")
        _stash_pending(client)
        with django_capture_on_commit_callbacks(execute=True):
            resp = self._submit(client, "claimed")
        assert resp.status_code == 409
        notify.assert_not_called()

    def test_workos_user_id_race_logs_loser_in_as_winner(self, client):
        """Sibling tab won the workos_user_id race; loser is signed in as winner."""
        # Sibling tab already created the row with the SAME workos_user_id.
        winner = make_user(
            email="alice@example.com",
            username="alice-winner",
            workos_user_id="user_01",
        )
        _stash_pending(client, next_url="/dashboard")
        pre_session_key = client.session.session_key

        # Loser tab submits a different handle. The username race wouldn't
        # fire (handle is unique); the workos_user_id race does.
        resp = self._submit(client, "alice-loser")
        assert resp.status_code == 200
        assert resp.json() == {"redirect_url": "/dashboard"}

        # Loser's handle was dropped — only the winner row exists.
        assert User.objects.filter(workos_user_id="user_01").count() == 1
        assert not User.objects.filter(username="alice-loser").exists()
        # Loser's session is now authenticated as the winner.
        assert client.session.get("_auth_user_id") == str(winner.pk)
        # Pending cleared.
        assert PENDING_SESSION_KEY not in client.session
        # `login()` rotated the session key — the load-bearing property
        # that makes "log loser in as winner" deterministic vs trusting
        # the winning tab's cookie (whose rotation may not reach the
        # losing tab in time).
        assert client.session.session_key != pre_session_key

    def test_format_invalid_returns_400(self, client):
        _stash_pending(client)
        resp = self._submit(client, "Bad_Name")
        assert resp.status_code == 400
        body = resp.json()
        assert body["detail"]["kind"] == "username_rejected"
        assert body["detail"]["reason"] == "bad_charset"
        # No row created.
        assert not User.objects.filter(workos_user_id="user_01").exists()

    def test_reserved_returns_400(self, client):
        _stash_pending(client)
        resp = self._submit(client, "admin")
        assert resp.status_code == 400
        body = resp.json()
        assert body["detail"]["kind"] == "username_rejected"
        assert body["detail"]["reason"] == "reserved"

    def test_oversize_payload_rejected_by_pydantic_as_422(self, client):
        """`max_length=200` is the DoS guard; the typed `too_long` path is
        for handles between 21 and 200 chars (the realistic typo range)."""
        _stash_pending(client)
        resp = self._submit(client, "a" * 201)
        assert resp.status_code == 422

    def test_oversize_but_under_dos_guard_yields_typed_too_long(self, client):
        _stash_pending(client)
        resp = self._submit(client, "a" * 50)
        assert resp.status_code == 400
        body = resp.json()
        assert body["detail"]["kind"] == "username_rejected"
        assert body["detail"]["reason"] == "too_long"

    def test_no_pending_returns_401(self, client):
        resp = self._submit(client, "alice")
        assert resp.status_code == 401
        assert resp.json()["detail"]["kind"] == "pending_invalid"

    def test_expired_pending_returns_401(self, client):
        stale = datetime.now(UTC) - PENDING_TTL - timedelta(seconds=1)
        _stash_pending(client, created_at=stale)
        resp = self._submit(client, "alice")
        assert resp.status_code == 401
        assert resp.json()["detail"]["kind"] == "pending_invalid"


# ── POST /cancel/ ────────────────────────────────────────────────────


@pytest.mark.django_db
class TestSignupCancel:
    def _cancel(self, client, **extra):
        client.cookies["csrftoken"] = "x" * 32
        return client.post(
            "/api/auth/signup/cancel/",
            HTTP_X_CSRFTOKEN="x" * 32,
            **extra,
        )

    def test_clears_pending_and_returns_local_url_without_sid(self, client, settings):
        settings.SIGNUP_CANCEL_RETURN_URL = "/"
        _stash_pending(client)
        resp = self._cancel(client)
        assert resp.status_code == 200
        # No workos_session_id → fall back to local return URL.
        assert resp.json() == {"logout_url": "/"}
        assert PENDING_SESSION_KEY not in client.session

    def test_idempotent_when_no_pending(self, client, settings):
        settings.SIGNUP_CANCEL_RETURN_URL = "/"
        resp = self._cancel(client)
        assert resp.status_code == 200
        assert resp.json() == {"logout_url": "/"}

    def test_builds_workos_logout_url_when_sid_present(
        self, client, settings, monkeypatch
    ):
        settings.WORKOS_API_KEY = "sk_test"  # pragma: allowlist secret
        settings.WORKOS_CLIENT_ID = "client_x"
        settings.SIGNUP_CANCEL_RETURN_URL = "/"
        settings.SITE_ORIGIN = "https://flipcommons.org"
        _stash_pending(client, workos_session_id="session_xyz")

        captured: dict[str, object] = {}

        class _FakeUserManagement:
            def get_logout_url(self, *, session_id, return_to):
                captured["session_id"] = session_id
                captured["return_to"] = return_to
                return "https://auth.workos.com/sessions/logout?token=fake"

        class _FakeClient:
            user_management = _FakeUserManagement()

        monkeypatch.setattr(
            "apps.accounts.api.signup.get_workos_client", lambda: _FakeClient()
        )
        resp = self._cancel(client)
        assert resp.status_code == 200
        assert resp.json()["logout_url"].startswith("https://auth.workos.com/")
        assert captured["session_id"] == "session_xyz"
        # The setting accepts a relative path; we expand to absolute since
        # WorkOS rejects bare paths.
        assert captured["return_to"] == "https://flipcommons.org/"

    def test_logout_return_to_ignores_the_request_host(
        self, client, settings, monkeypatch
    ):
        """The CDN sends its origin hostname; the return URL must not follow it."""
        settings.WORKOS_API_KEY = "sk_test"  # pragma: allowlist secret
        settings.WORKOS_CLIENT_ID = "client_x"
        settings.SIGNUP_CANCEL_RETURN_URL = "/"
        settings.SITE_ORIGIN = "https://flipcommons.org"
        settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "cdn-origin.example"]
        _stash_pending(client, workos_session_id="session_xyz")

        captured: dict[str, object] = {}

        class _FakeUserManagement:
            def get_logout_url(self, *, session_id, return_to):
                captured["return_to"] = return_to
                return "https://auth.workos.com/sessions/logout?token=fake"

        class _FakeClient:
            user_management = _FakeUserManagement()

        monkeypatch.setattr(
            "apps.accounts.api.signup.get_workos_client", lambda: _FakeClient()
        )
        resp = self._cancel(client, HTTP_HOST="cdn-origin.example")
        assert resp.status_code == 200
        assert captured["return_to"] == "https://flipcommons.org/"

    def test_absolute_return_url_passes_through(self, client, settings, monkeypatch):
        settings.WORKOS_API_KEY = "sk_test"  # pragma: allowlist secret
        settings.WORKOS_CLIENT_ID = "client_x"
        settings.SIGNUP_CANCEL_RETURN_URL = "https://elsewhere.test/bye"
        settings.SITE_ORIGIN = "https://flipcommons.org"
        _stash_pending(client, workos_session_id="session_xyz")

        captured: dict[str, object] = {}

        class _FakeUserManagement:
            def get_logout_url(self, *, session_id, return_to):
                captured["return_to"] = return_to
                return "https://auth.workos.com/sessions/logout?token=fake"

        class _FakeClient:
            user_management = _FakeUserManagement()

        monkeypatch.setattr(
            "apps.accounts.api.signup.get_workos_client", lambda: _FakeClient()
        )
        resp = self._cancel(client)
        assert resp.status_code == 200
        assert captured["return_to"] == "https://elsewhere.test/bye"

    def test_workos_logout_failure_falls_back_to_local_return(
        self, client, settings, monkeypatch
    ):
        settings.WORKOS_API_KEY = "sk_test"  # pragma: allowlist secret
        settings.WORKOS_CLIENT_ID = "client_x"
        settings.SIGNUP_CANCEL_RETURN_URL = "/"
        _stash_pending(client, workos_session_id="session_xyz")

        class _FakeUserManagement:
            def get_logout_url(self, **kwargs):
                raise RuntimeError("WorkOS unreachable")

        class _FakeClient:
            user_management = _FakeUserManagement()

        monkeypatch.setattr(
            "apps.accounts.api.signup.get_workos_client", lambda: _FakeClient()
        )
        resp = self._cancel(client)
        assert resp.status_code == 200
        assert resp.json() == {"logout_url": "/"}
