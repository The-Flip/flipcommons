"""Tests for the admin notification channel (``apps.core.admin_notifications``)."""

from __future__ import annotations

import json
from http.client import HTTPResponse
from unittest.mock import MagicMock

import pytest

from apps.core import admin_notifications
from apps.core.admin_notifications import _MAX_CONTENT_LEN, notify_admins
from apps.core.user_agent import USER_AGENT

WEBHOOK = "https://discord.example.test/api/webhooks/1/abc"


def _fake_response() -> MagicMock:
    resp = MagicMock(spec=HTTPResponse)
    resp.status = 204
    resp.read.return_value = b""
    resp.__enter__ = lambda s: s
    resp.__exit__ = MagicMock(return_value=False)
    return resp


@pytest.fixture
def urlopen(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Patch ``urlopen`` where the module imports it, returning the mock."""
    fake = MagicMock(return_value=_fake_response())
    monkeypatch.setattr(admin_notifications, "urlopen", fake)
    return fake


class TestNotifyAdmins:
    def test_unset_webhook_is_a_noop(self, settings, urlopen):
        settings.ADMIN_NOTIFICATION_WEBHOOK_URL = ""
        notify_admins("account.created", "hello")
        urlopen.assert_not_called()

    def test_posts_json_content_to_the_webhook(self, settings, urlopen):
        settings.ADMIN_NOTIFICATION_WEBHOOK_URL = WEBHOOK
        notify_admins("account.created", "New account: alice")

        urlopen.assert_called_once()
        req = urlopen.call_args.args[0]
        assert req.full_url == WEBHOOK
        assert req.get_method() == "POST"
        assert json.loads(req.data) == {"content": "New account: alice"}
        assert req.get_header("Content-type") == "application/json"
        assert req.get_header("User-agent") == USER_AGENT

    def test_call_carries_an_explicit_timeout(self, settings, urlopen):
        """Losing the timeout is the one change that could quietly hurt capacity."""
        settings.ADMIN_NOTIFICATION_WEBHOOK_URL = WEBHOOK
        notify_admins("account.created", "hello")
        timeout = urlopen.call_args.kwargs["timeout"]
        assert 0 < timeout <= 5

    def test_truncates_overlong_messages(self, settings, urlopen):
        settings.ADMIN_NOTIFICATION_WEBHOOK_URL = WEBHOOK
        notify_admins("account.created", "x" * (_MAX_CONTENT_LEN + 500))
        body = json.loads(urlopen.call_args.args[0].data)
        assert len(body["content"]) == _MAX_CONTENT_LEN

    def test_delivery_failure_is_swallowed_and_reported(
        self, settings, urlopen, sentry_recording, caplog
    ):
        settings.ADMIN_NOTIFICATION_WEBHOOK_URL = WEBHOOK
        urlopen.side_effect = TimeoutError("timed out")

        notify_admins("account.created", "hello")  # must not raise

        assert [
            e["exception"]["values"][0]["type"] for e in sentry_recording.events
        ] == ["AdminNotificationError"]
        assert sentry_recording.events[0]["exception"]["values"][0]["value"] == (
            "TimeoutError: timed out"
        )
        failed = [
            r for r in caplog.records if r.getMessage() == "admin_notification.failed"
        ]
        assert len(failed) == 1
        assert failed[0].code == "account.created"
        assert failed[0].error == "TimeoutError: timed out"

    def test_sentry_report_never_carries_the_webhook_url(
        self, settings, urlopen, sentry_recording
    ):
        """The URL is a credential, and Sentry records frame locals by default."""
        settings.ADMIN_NOTIFICATION_WEBHOOK_URL = WEBHOOK
        urlopen.side_effect = OSError("unreachable")

        notify_admins("account.created", "hello")

        assert len(sentry_recording.events) == 1
        assert "webhooks/1/abc" not in json.dumps(sentry_recording.events)
