"""End-to-end check that ``IGNORE_ERRORS`` actually suppresses events.

Boots Sentry with the same ``ignore_errors`` list ``settings.py``
uses in production plus a recording transport, then captures
instances of each ignored class and an unrelated class. The
ignored classes must produce zero envelopes; the control class
must produce one. A regression where the list is overwritten or
the SDK changes its filter semantics fails this test.

Also pins the ``StructuredApiError`` subclass invariant — see
``test_all_structured_api_error_subclasses_are_4xx`` below.
"""

from __future__ import annotations

import sentry_sdk

from apps.core.exceptions import StructuredApiError
from config.sentry_options import IGNORE_ERRORS
from conftest import SentryRecordingTransport


def _all_subclasses(cls: type[StructuredApiError]) -> set[type[StructuredApiError]]:
    direct = cls.__subclasses__()
    return set(direct) | {sub for d in direct for sub in _all_subclasses(d)}


def test_ignore_errors_drops_each_listed_class() -> None:
    transport = SentryRecordingTransport()
    sentry_sdk.init(
        dsn="https://public@example.test/1",
        transport=transport,
        ignore_errors=IGNORE_ERRORS,
    )
    try:
        for exc_class in IGNORE_ERRORS:
            try:
                raise exc_class("test")
            except BaseException:
                sentry_sdk.capture_exception()
        assert transport.events == [], (
            f"ignore_errors did not drop: "
            f"{[e.get('exception') for e in transport.events]}"
        )

        # Control: an unrelated exception must still be captured,
        # otherwise the test would pass on a broken transport.
        try:
            raise RuntimeError("control — should be captured")
        except RuntimeError:
            sentry_sdk.capture_exception()
        assert len(transport.events) == 1
    finally:
        sentry_sdk.get_client().close()
        sentry_sdk.Scope.get_global_scope().set_client(None)


def test_all_structured_api_error_subclasses_are_4xx() -> None:
    """``IGNORE_ERRORS`` suppresses every subclass of ``StructuredApiError``.

    The base class is on the ignore list because every structured
    error today is a 4xx (rate-limit, validation, policy denial).
    Sentry's ``ignore_errors`` matches by ``isinstance``, so a 5xx
    subclass would silently disappear from the issue stream — the
    opposite of what we want for "the server actually broke."

    This test walks all imported subclasses (Django loads every app
    during pytest setup, so production subclasses are all reachable
    via ``__subclasses__``). If you add a 5xx ``StructuredApiError``
    subclass, this test fails — either fix the status, or refactor
    the ignore list to enumerate the 4xx subclasses explicitly
    instead of relying on the base.
    """
    # Exclude test-only subclasses: ``test_structured_errors.py``
    # defines deliberately-malformed ``StructuredApiError`` subclasses
    # to test the base's invariants (e.g. classes that don't set
    # ``status`` at all). Those aren't shipped in production and
    # aren't subject to the Sentry-ignore contract.
    production_subclasses = [
        sub
        for sub in _all_subclasses(StructuredApiError)
        if ".tests." not in sub.__module__
    ]
    offenders = [sub for sub in production_subclasses if not (400 <= sub.status < 500)]
    assert not offenders, (
        "Non-4xx StructuredApiError subclasses leak into ignore_errors: "
        + ", ".join(
            f"{c.__module__}.{c.__name__}(status={c.status})" for c in offenders
        )
    )
