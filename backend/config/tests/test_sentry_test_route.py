"""Tests for ``/api/sentry_test`` — the staff-gated exception trigger.

The route exists to verify the Sentry pipeline end-to-end after a
deploy. These tests
pin both the authz gate and the actual capture behavior so a future
change that breaks either is a CI failure, not a silent regression
discovered the next time someone runs the verification step.
"""

from __future__ import annotations

import pytest
from django.test import Client

from apps.accounts.models import User
from config.api import _SentryTestError
from conftest import SentryRecordingTransport


@pytest.mark.django_db
class TestSentryTestRoute:
    def test_anonymous_is_denied(self, client: Client) -> None:
        resp = client.get("/api/sentry_test")
        assert resp.status_code in (401, 403)

    def test_non_staff_is_denied(self, client: Client, user: User) -> None:
        client.force_login(user)
        resp = client.get("/api/sentry_test")
        assert resp.status_code == 403

    def test_staff_triggers_the_exception(self, client: Client, staff: User) -> None:
        client.force_login(staff)
        # Django's test Client re-raises view exceptions by default.
        # That's exactly what we want — the route's contract is
        # "raise an uncaught exception so DjangoIntegration captures it."
        with pytest.raises(
            _SentryTestError, match="Deliberate exception from /api/sentry_test"
        ):
            client.get("/api/sentry_test")

    def test_staff_request_captures_exactly_one_event(
        self,
        client: Client,
        staff: User,
        sentry_recording: SentryRecordingTransport,
    ) -> None:
        client.force_login(staff)
        with pytest.raises(_SentryTestError):
            client.get("/api/sentry_test")

        # DjangoIntegration captures the exception synchronously through
        # the request-handling middleware. Exactly one event should
        # land — duplicate capture or zero capture would both be
        # regressions.
        assert len(sentry_recording.events) == 1
        event = sentry_recording.events[0]
        exception_values = event["exception"]["values"]
        assert any(v.get("type") == "_SentryTestError" for v in exception_values), (
            exception_values
        )
