"""Sentry SDK init guard.

The test environment does not set ``SENTRY_DSN``, so the init block in
:mod:`config.settings` must have left the SDK without an active client.
Weakening the empty-DSN guard would cause this test to fail.
"""

from __future__ import annotations

import os

import sentry_sdk


def test_sentry_is_inactive_without_dsn() -> None:
    # Defensive assertion that the test environment is what we think it is:
    # if some other fixture sets SENTRY_DSN, this test's premise breaks
    # before it can catch a real regression.
    assert os.environ.get("SENTRY_DSN", "").strip() == ""

    # The modern (2.x) replacement for ``Hub.current.client is None``:
    # ``get_client()`` returns a ``NonRecordingClient`` whose
    # ``is_active()`` is False when no init has run.
    client = sentry_sdk.get_client()
    assert not client.is_active(), (
        "Sentry SDK has an active client even though SENTRY_DSN is unset. "
        "The empty-DSN guard in config/settings.py is the master switch; a "
        "weakened guard would emit events from local dev, CI, and tests."
    )
